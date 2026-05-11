"""
Flow Tracker — IP流追踪 + DNS映射 + TLS绑定

这是"数据管道"的底层:
  tshark raw packets → PacketSignal → FlowTracker → 结构化流/缓存

核心功能:
  1. IP五元组流追踪 (src→dst, 含端口/协议)
  2. DNS解析缓存 (domain → [IPs])
  3. TLS SNI绑定 (IP:port → sni)
  4. IP→域名反向查找
  5. TTL历史追踪
  6. IP聚类 (通过共享DNS解析关系)
"""

import time
from collections import defaultdict, Counter
from typing import Optional, List, Dict, Set, Tuple

from .models import (
    PacketSignal, IPFlow, DNSCacheEntry, TLSHost,
    ConnectionGroup, ConnectionGraph, FlowSignature
)


class FlowTracker:
    """
    IP流追踪器 — 管理所有网络流、DNS缓存、TLS绑定

    这是行为分析的数据基础, 所有高层分析都基于此。
    """

    def __init__(self):
        # ── 数据存储 ──
        self._flows: Dict[str, IPFlow] = {}
        self._dns_cache: Dict[str, DNSCacheEntry] = {}
        self._tls_hosts: Dict[str, TLSHost] = {}
        self._graph = ConnectionGraph()
        self._ip_ttl_history: Dict[str, List[int]] = defaultdict(list)

        # ── 统计 ──
        self.total_signals = 0
        self.total_dns = 0
        self.total_tls = 0
        self.total_packets = 0

    def process_packet(self, sig: PacketSignal) -> Optional[IPFlow]:
        """
        处理一个包信号, 更新流/DNS/TLS/图

        Args:
            sig: 从tshark解析的包信号

        Returns:
            更新后的IPFlow对象, 如果数据无效返回None
        """
        if not sig.ip_src or not sig.ip_dst:
            return None

        self.total_signals += 1
        self.total_packets += 1

        # ── 构建流Key ──
        flow_key = f"{sig.ip_src}|{sig.ip_dst}|{sig.ip_proto}|{sig.src_port}|{sig.dst_port}"
        now = sig.ts_epoch

        # ── 创建或更新流 ──
        if flow_key not in self._flows:
            flow = IPFlow(
                flow_key=flow_key,
                src_ip=sig.ip_src,
                dst_ip=sig.ip_dst,
                proto=sig.ip_proto,
                src_port=sig.src_port,
                dst_port=sig.dst_port,
                first_seen=now,
                last_seen=now,
            )
            self._flows[flow_key] = flow
        else:
            flow = self._flows[flow_key]

        flow.last_seen = now
        flow.packets += 1

        # ── TCP标志跟踪 ──
        if sig.tcp_flags:
            for flag in ("SYN", "ACK", "FIN", "RST"):
                if flag in sig.tcp_flags:
                    flow.tcp_flags_seen.add(flag)

        # ── TTL跟踪 ──
        if sig.ip_ttl > 0:
            flow.ttl_values.append(sig.ip_ttl)
            flow.avg_ttl = sum(flow.ttl_values) / len(flow.ttl_values)
            self._ip_ttl_history[sig.ip_dst].append(sig.ip_ttl)

        # ── TLS SNI绑定 ──
        if sig.tls_sni:
            flow.tls_sni = sig.tls_sni
            self.total_tls += 1
            host_key = f"{sig.ip_dst}:{sig.dst_port}"
            if host_key not in self._tls_hosts:
                self._tls_hosts[host_key] = TLSHost(
                    sni=sig.tls_sni,
                    ip=sig.ip_dst,
                    port=sig.dst_port,
                    first_seen=now,
                )
            host = self._tls_hosts[host_key]
            host.last_seen = now
            host.connection_count += 1

        # ── DNS缓存更新 ──
        if sig.dns_query:
            domain = sig.dns_query.lower().rstrip(".")
            self.total_dns += 1
            if domain not in self._dns_cache:
                self._dns_cache[domain] = DNSCacheEntry(
                    domain=domain,
                    first_seen=now,
                )
            entry = self._dns_cache[domain]
            entry.last_seen = now
            entry.query_count += 1
            if sig.dns_answers:
                entry.resolved_ips.update(sig.dns_answers)
            if sig.dns_response and not sig.dns_answers:
                entry.is_nxdomain = True
            flow.dns_names.add(domain)

        # ── 更新连接图 ──
        self._update_graph(flow, sig)

        return flow

    def _update_graph(self, flow: IPFlow, sig: PacketSignal):
        """
        更新连接图谱

        节点命名规则:
        - IP节点: "ip:1.2.3.4"
        - DNS节点: "dns:example.com"
        - SNI节点: "sni:example.com"
        """
        node_src = f"ip:{flow.src_ip}"

        # 优先使用DNS域名作为目标节点
        dns_names = self._resolve_dns_for_ip(flow.dst_ip)
        if dns_names:
            node_dst = f"dns:{dns_names[0]}"
        elif flow.tls_sni:
            node_dst = f"sni:{flow.tls_sni}"
        else:
            node_dst = f"ip:{flow.dst_ip}"

        self._graph.add_edge(node_src, node_dst)

    def _resolve_dns_for_ip(self, ip: str) -> List[str]:
        """反向查找: IP → 域名列表"""
        domains = []
        for domain, entry in self._dns_cache.items():
            if ip in entry.resolved_ips:
                domains.append(domain)
        return domains

    # ══════════════════════════════════════════════════════════════════
    #  查询接口
    # ══════════════════════════════════════════════════════════════════

    def get_flow(self, key: str) -> Optional[IPFlow]:
        return self._flows.get(key)

    def get_all_flows(self) -> Dict[str, IPFlow]:
        return dict(self._flows)

    def get_active_flows(self, since: float) -> List[IPFlow]:
        """获取指定时间后活跃的所有流"""
        return [f for f in self._flows.values()
                if f.last_seen >= since]

    def get_dns_cache(self) -> Dict[str, DNSCacheEntry]:
        return dict(self._dns_cache)

    def get_tls_hosts(self) -> Dict[str, TLSHost]:
        return dict(self._tls_hosts)

    @property
    def graph(self) -> ConnectionGraph:
        return self._graph

    def get_unique_dst_ips(self, since: float = 0) -> Set[str]:
        """获取指定时间后的唯一目标IP集合"""
        if since == 0:
            return {f.dst_ip for f in self._flows.values()}
        return {f.dst_ip for f in self._flows.values()
                if f.last_seen >= since}

    def get_flow_count(self) -> int:
        return len(self._flows)

    # ══════════════════════════════════════════════════════════════════
    #  IP聚类 (通过共享DNS解析关系)
  # ══════════════════════════════════════════════════════════════════

    def get_ip_clusters(self, since: float = 0) -> Dict[str, Set[str]]:
        """
        IP聚类 — 通过DNS共享关系将IP分组

        原理:
            如果两个IP被同一个域名解析到, 它们属于同一个服务。
            例如: 小熊加速器的所有服务器IP共享相同的域名, 会聚为一类。

        Returns:
            {"cluster_0": {ip1, ip2, ...}, "cluster_1": {...}}
        """
        # DNS → IP 映射
        dns_to_ips = defaultdict(set)
        for domain, entry in self._dns_cache.items():
            dns_to_ips[domain].update(entry.resolved_ips)

        # IP → DNS 反向映射
        ip_to_domains = defaultdict(set)
        for domain, ips in dns_to_ips.items():
            for ip in ips:
                ip_to_domains[ip].add(domain)

        # 通过共享DNS广度优先搜索聚类
        target_ips = self.get_unique_dst_ips(since)
        visited = set()
        clusters = []

        for ip in target_ips:
            if ip in visited:
                continue
            cluster = set()
            stack = [ip]
            while stack:
                cur = stack.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                cluster.add(cur)
                # 找到所有共享DNS的兄弟IP
                for domain in ip_to_domains.get(cur, set()):
                    for sibling_ip in dns_to_ips.get(domain, set()):
                        if sibling_ip not in visited:
                            stack.append(sibling_ip)
            if cluster:
                clusters.append(cluster)

        return {f"cluster_{i}": c for i, c in enumerate(clusters)}

    # ══════════════════════════════════════════════════════════════════
    #  TTL变化检测
    # ══════════════════════════════════════════════════════════════════

    def get_ttl_changes(self, since: float = 0) -> Dict[str, int]:
        """
        获取每个IP的TTL最大变化值

        TTL变化可能指示:
        - 路由路径改变 (VPN开启后走隧道)
        - 服务器切换 (走到不同服务器)
        """
        changes = {}
        for ip, ttls in self._ip_ttl_history.items():
            if len(ttls) >= 2:
                recent = [t for t in ttls]
                changes[ip] = max(recent) - min(recent)
        return changes

    # ══════════════════════════════════════════════════════════════════
    #  统计
    # ══════════════════════════════════════════════════════════════════

    def get_statistics(self) -> dict:
        now = time.time()
        active_60s = self.get_active_flows(now - 60)

        return {
            "total_signals": self.total_signals,
            "total_dns": self.total_dns,
            "total_tls": self.total_tls,
            "total_flows": len(self._flows),
            "active_flows_60s": len(active_60s),
            "dns_cache": len(self._dns_cache),
            "tls_hosts": len(self._tls_hosts),
            "graph_nodes": self._graph.snapshot()["nodes"],
            "graph_edges": self._graph.snapshot()["edges"],
            "graph_density": self._graph.snapshot()["density"],
            "graph_groups": self._graph.snapshot()["groups"],
            "graph_entropy": self._graph.snapshot()["entropy"],
        }