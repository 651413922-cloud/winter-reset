"""
数据模型 — 从原始包信号到抽象行为模型的所有数据结构
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Set, Tuple
from enum import Enum
from datetime import datetime, timezone
import time
import math


# ══════════════════════════════════════════════════════════════════════
#  状态枚举
# ══════════════════════════════════════════════════════════════════════

class VPNState(Enum):
    """VPN连接状态枚举"""
    IDLE         = "idle"
    CONNECTING   = "connecting"
    CONNECTED    = "connected"
    SWITCHING    = "switching"
    DISCONNECTED = "disconnected"


class SignalType(Enum):
    """信号类型枚举"""
    DNS_QUERY    = "dns_query"
    DNS_RESPONSE = "dns_response"
    TLS_SNI      = "tls_sni"
    TCP_SYN      = "tcp_syn"
    TCP_RST      = "tcp_rst"
    TCP_FIN      = "tcp_fin"
    TCP_DATA     = "tcp_data"
    OTHER        = "other"


# ══════════════════════════════════════════════════════════════════════
#  核心数据模型
# ══════════════════════════════════════════════════════════════════════

@dataclass
class PacketSignal:
    """
    原始包信号 — 从tshark解析的单条记录

    这是最底层的数据单元, 包含从网络包中提取的所有原始字段。
    后续所有分析都基于这些原始信号。
    """
    ts_epoch: float
    ip_src: str
    ip_dst: str
    ip_proto: int = 0
    src_port: int = 0
    dst_port: int = 0
    tcp_flags: str = ""
    ip_ttl: int = 0
    dns_query: str = ""
    dns_response: bool = False
    dns_answers: List[str] = field(default_factory=list)
    tls_sni: str = ""
    signal_type: SignalType = SignalType.OTHER
    raw_line: str = ""


@dataclass
class IPFlow:
    """
    IP五元组流 — 网络连接的最小跟踪单元

    以 (src_ip, dst_ip, proto, src_port, dst_port) 唯一标识,
    跟踪该连接的生命周期、元数据和统计。
    """
    flow_key: str
    src_ip: str
    dst_ip: str
    proto: int
    src_port: int
    dst_port: int
    first_seen: float = 0.0
    last_seen: float = 0.0
    packets: int = 0
    tcp_flags_seen: Set[str] = field(default_factory=set)
    tls_sni: str = ""
    dns_names: Set[str] = field(default_factory=set)
    ttl_values: List[int] = field(default_factory=list)
    avg_ttl: float = 0.0
    is_active: bool = True

    @property
    def duration(self) -> float:
        return self.last_seen - self.first_seen

    @property
    def has_tls(self) -> bool:
        return bool(self.tls_sni)

    @property
    def has_dns(self) -> bool:
        return bool(self.dns_names)

    @property
    def is_terminated(self) -> bool:
        return any(f in self.tcp_flags_seen for f in ("FIN", "RST"))


@dataclass
class DNSCacheEntry:
    """DNS 解析缓存条目"""
    domain: str
    resolved_ips: Set[str] = field(default_factory=set)
    first_seen: float = 0.0
    last_seen: float = 0.0
    query_count: int = 0
    is_nxdomain: bool = False


@dataclass
class TLSHost:
    """TLS 服务器信息"""
    sni: str
    ip: str
    port: int = 443
    first_seen: float = 0.0
    last_seen: float = 0.0
    connection_count: int = 0


@dataclass
class ConnectionGroup:
    """
    连接组 — 最核心的抽象层!

    一组共享相同网络行为的IP/域名集合。
    例如: 小熊加速器的所有服务器IP和域名组成一个连接组。

    为什么需要连接组:
    - 一个VPN服务通常有多个IP/域名
    - 它们共享相同的DNS解析关系
    - 它们同时出现/消失
    - VPN切换 = 从组A迁移到组B
    - VPN连接 = 新连接组突然出现
    """
    group_id: str
    ips: Set[str] = field(default_factory=set)
    domains: Set[str] = field(default_factory=set)
    snis: Set[str] = field(default_factory=set)
    flows: Set[str] = field(default_factory=set)
    first_seen: float = 0.0
    last_seen: float = 0.0
    total_flows: int = 0
    total_packets: int = 0
    is_vpn_candidate: bool = False
    vpn_score: float = 0.0
    volume: int = 0      # 累计流量包数
    avg_ttl: float = 0.0

    @property
    def age(self) -> float:
        return self.last_seen - self.first_seen

    @property
    def size(self) -> int:
        return len(self.ips) + len(self.domains)


@dataclass
class ConnectionGraph:
    """
    连接图谱 — 全网的连接关系建模

    节点: IP / 域名 / SNI
    边: 连接关系 (权重=连接强度)
    聚类: 通过DNS解析关系形成的IP聚簇

    关键指标:
    - density: 图密度 = 边数/可能最大边数
    - cluster_count: 连接组数量
    - entropy: 连接分布的熵值 (均匀性指标)
    - edge_change_rate: 边变化速率
    """
    nodes: Set[str] = field(default_factory=set)
    edges: Dict[Tuple[str, str], int] = field(default_factory=dict)
    groups: Dict[str, ConnectionGroup] = field(default_factory=dict)
    timestamp: float = 0.0

    # 缓存指标
    _density: float = 0.0
    _cluster_count: int = 0
    _entropy: float = 0.0
    _total_edges: int = 0

    def add_edge(self, node_a: str, node_b: str, weight: int = 1):
        """添加或更新一条边"""
        self.nodes.add(node_a)
        self.nodes.add(node_b)
        key = (node_a, node_b) if node_a < node_b else (node_b, node_a)
        self.edges[key] = self.edges.get(key, 0) + weight
        self._rebuild_cache()

    def remove_node(self, node: str):
        """移除一个节点及其所有边"""
        self.nodes.discard(node)
        self.edges = {k: v for k, v in self.edges.items() if node not in k}
        self._rebuild_cache()

    def _rebuild_cache(self):
        """重新计算图指标"""
        n = len(self.nodes)
        e = len(self.edges)
        self._total_edges = e
        self._density = (2 * e) / max(n * (n - 1), 1)
        self._cluster_count = len(self.groups)

        # 连接分布熵
        if e > 0:
            counts = list(self.edges.values())
            total = sum(counts)
            self._entropy = -sum(
                (c / total) * math.log2(c / total) for c in counts if c > 0
            )
        else:
            self._entropy = 0.0

    def snapshot(self) -> dict:
        """获取图快照"""
        return {
            "nodes": len(self.nodes),
            "edges": self._total_edges,
            "density": round(self._density, 4),
            "groups": self._cluster_count,
            "entropy": round(self._entropy, 4),
        }

    @property
    def total_edges(self) -> int:
        return self._total_edges

    @property
    def density(self) -> float:
        return self._density


@dataclass
class VPNEvent:
    """VPN行为事件 — 引擎的输出"""
    event_type: str          # vpn_connect / vpn_disconnect / vpn_switch / vpn_reconnect
    timestamp: str
    timestamp_epoch: float
    server: str              # 主服务器标识
    server_previous: str = ""
    confidence: float = 0.0
    signals: Dict[str, List[str]] = field(default_factory=dict)
    trigger_reason: str = ""
    state_before: str = ""
    state_after: str = ""
    # 行为指标快照
    behavior_metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class FlowSignature:
    """
    流量特征签名 — 用于描述一段时间的网络行为

    这是行为识别的最小对比单元:
    - 两个时间窗口的签名对比 = 变化检测
    - 签名 = {特征向量}
    """
    timestamp: float
    ip_count: int = 0
    flow_count: int = 0
    dns_count: int = 0
    tls_count: int = 0
    unique_dst_ips: int = 0
    graph_density: float = 0.0
    graph_entropy: float = 0.0
    group_count: int = 0
    new_ip_ratio: float = 0.0
    ttl_variance: float = 0.0
    avg_flow_duration: float = 0.0

    def similarity_to(self, other: "FlowSignature") -> float:
        """
        计算两个签名的相似度 (0~1)
        相似度越低 = 行为变化越大 = 越可能是VPN事件
        """
        if not other:
            return 0.5

        diffs = []
        # IP数变化
        if max(self.ip_count, other.ip_count) > 0:
            diffs.append(abs(self.ip_count - other.ip_count) /
                         max(self.ip_count, other.ip_count))
        # 流数变化
        if max(self.flow_count, other.flow_count) > 0:
            diffs.append(abs(self.flow_count - other.flow_count) /
                         max(self.flow_count, other.flow_count))
        # DNS数变化
        if max(self.dns_count, other.dns_count) > 0:
            diffs.append(abs(self.dns_count - other.dns_count) /
                         max(self.dns_count, other.dns_count))
        # 图密度变化
        diffs.append(abs(self.graph_density - other.graph_density))
        # 图熵变化
        diffs.append(abs(self.graph_entropy - other.graph_entropy))

        if not diffs:
            return 1.0

        avg_diff = sum(diffs) / len(diffs)
        return max(0.0, 1.0 - avg_diff)