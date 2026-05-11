#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║        VPN 行为识别系统 (VPN Behavior Recognition)          ║
║       基于 tshark 实时抓包 · 元数据分析 · 状态机驱动        ║
╚══════════════════════════════════════════════════════════════╝

识别目标:
  - vpn_connect     → 首次连接
  - vpn_disconnect  → 断开连接
  - vpn_switch      → 切换线路/服务器
  - vpn_reconnect   → 断后重连

分析维度: DNS查询 · TLS SNI · IP目标 · 时间窗口行为
"""

import subprocess
import json
import time
import sys
import os
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Set, Tuple
from enum import Enum
from datetime import datetime, timezone

# ═══════════════════════════════════════════════════════════
#  配置
# ═══════════════════════════════════════════════════════════

TSHARK_PATH = r"D:\useful\Wireshark\tshark.exe"
OUTPUT_FILE = "vpn_events.jsonl"

# --- 滑动窗口参数 (秒) ---
WINDOW_BURST   = 10    # 连接爆发检测
WINDOW_SWITCH  = 60    # 服务器切换检测
WINDOW_SESSION = 120   # 会话状态维护
WINDOW_GONE    = 300   # 断开连接判断

# --- 状态机参数 (秒) ---
CONFIRM_DELAY  = 5     # CONNECTING→CONNECTED 确认等待
SWITCH_SETTLE  = 5     # SWITCHING→CONNECTED 稳定等待
DISCONNECT_TTL = 60    # 无VPN流量多久判定断开
RECONNECT_MAX  = 120   # 断开后多久内算"重连"
COOLDOWN_SAME  = 10    # 同类事件最小间隔

# --- 置信度参数 ---
WEIGHT_HIGH = 0.3
WEIGHT_MED  = 0.2
WEIGHT_LOW  = 0.1
MIN_CONFIDENCE_CONNECT    = 0.6
MIN_CONFIDENCE_DISCONNECT = 0.5
MIN_CONFIDENCE_SWITCH     = 0.5
MIN_CONFIDENCE_RECONNECT  = 0.7

# --- 摘要间隔 (秒) ---
SUMMARY_INTERVAL = 60


# ═══════════════════════════════════════════════════════════
#  VPN 关键词库
# ═══════════════════════════════════════════════════════════

VPN_KEYWORDS_HIGH = {
    "vpn", "proxy", "secure", "privacy", "tunnel",
    "wireguard", "openvpn", "shadowsocks", "v2ray",
    "trojan", "clash", "hysteria", "tuic",
    "naiveproxy", "sing-box", "xray", "ssr",
    "nordvpn", "expressvpn", "surfshark", "mullvad",
    "protonvpn", "hidemy", "cyberghost", "vyprvpn",
    "fastestvpn", "ivpn", "privadovpn", "purevpn",
    "vpnbook", "vpngate", "softether", "arcai",
    "lantern", "psiphon", "ultrasurf", "freegate",
    "goflyway", "brook", "gost", "leaf",
}

VPN_KEYWORDS_MED = {
    "cloud", "cdn", "edge", "gateway", "relay",
    "forward", "speed", "fast", "node", "server",
    "endpoint", "api", "ws", "grpc", "cdnfast",
    "transit", "route", "exit", "entry", "hop",
    "boost", "turbo", "quick", "rapid",
}

# 公开CDN/公共服务 — 必然不是VPN
EXCLUDE_DOMAINS = {
    "google", "googleapis", "gstatic", "googleanalytics",
    "microsoft", "live", "office", "office365", "azure",
    "apple", "icloud", "apple-dns",
    "facebook", "fbcdn", "instagram", "whatsapp",
    "twitter", "twimg", "x",
    "amazon", "amazonaws", "aws", "cloudfront",
    "cloudflare", "cloudflare-dns",
    "akamai", "akamaiedge", "akamaihd",
    "fastly", "fastlylb",
    "netflix", "nflxvideo", "nflxext",
    "youtube", "ytimg", "googlevideo",
    "bilibili", "bilivideo",
    "baidu", "bdstatic",
    "taobao", "tmall", "alibaba", "alicdn",
    "tencent", "qq", "weixin", "wechat",
    "bytedance", "tiktok", "douyin",
    "github", "githubassets", "githubusercontent",
    "stackoverflow", "stackexchange",
    "reddit", "redd.it",
    "wikipedia", "wikimedia",
    "dropbox", "box",
    "salesforce", "zendesk",
    "akadns", "edgekey",
    "digicert", "letsencrypt", "globalsign",
    "ntp", "pool.ntp",
    "localhost", "local",
}


# ═══════════════════════════════════════════════════════════
#  数据模型
# ═══════════════════════════════════════════════════════════

class VPNState(Enum):
    """VPN连接状态枚举"""
    IDLE         = "idle"
    CONNECTING   = "connecting"
    CONNECTED    = "connected"
    SWITCHING    = "switching"
    DISCONNECTED = "disconnected"


@dataclass
class SignalRecord:
    """单条网络信号记录"""
    timestamp_epoch: float
    timestamp: str
    dns_query: str = ""
    tls_sni: str = ""
    ip_dst: str = ""
    ip_src: str = ""
    proto: str = ""
    tcp_flags: str = ""
    ip_ttl: str = ""
    is_vpn_related: bool = False
    vpn_keywords: List[str] = field(default_factory=list)
    vpn_level: str = ""  # "high" / "medium" / "low"


@dataclass
class VPNEvent:
    """VPN行为事件"""
    event_type: str          # vpn_connect / vpn_disconnect / vpn_switch / vpn_reconnect
    timestamp: str           # ISO 8601
    timestamp_epoch: float
    server: str              # 目标服务器标识
    server_previous: str = "" # switch时有值
    confidence: float = 0.0
    signals: Dict[str, List[str]] = field(default_factory=dict)
    trigger_reason: str = ""
    state_before: str = ""
    state_after: str = ""


# ═══════════════════════════════════════════════════════════
#  时间窗口容器
# ═══════════════════════════════════════════════════════════

class TimeWindow:
    """基于deque的滑动时间窗口"""
    def __init__(self, window_seconds: float):
        self.duration = window_seconds
        self._records: deque = deque()

    def add(self, record: SignalRecord):
        self._flush_expired()
        self._records.append(record)

    def get_active(self) -> List[SignalRecord]:
        """获取窗口内所有未过期记录"""
        self._flush_expired()
        return list(self._records)

    def count_vpn(self) -> int:
        """窗口内VPN相关信号数"""
        return sum(1 for r in self.get_active() if r.is_vpn_related)

    def count_high(self) -> int:
        """窗口内高置信度VPN信号数"""
        return sum(1 for r in self.get_active() if r.vpn_level == "high")

    def unique_vpn_servers(self) -> Set[str]:
        """窗口内不重复的VPN服务器标识"""
        servers = set()
        for r in self.get_active():
            if r.is_vpn_related:
                if r.tls_sni:
                    servers.add(r.tls_sni)
                elif r.dns_query:
                    servers.add(r.dns_query)
                elif r.ip_dst:
                    servers.add(r.ip_dst)
        return servers

    def last_vpn_time(self) -> Optional[float]:
        """窗口内最后一次VPN活动的时间戳"""
        records = self.get_active()
        vpn_records = [r for r in records if r.is_vpn_related]
        if vpn_records:
            return max(r.timestamp_epoch for r in vpn_records)
        return None

    def is_empty(self) -> bool:
        return len(self.get_active()) == 0

    def _flush_expired(self):
        """清理过期记录"""
        now = time.time()
        cutoff = now - self.duration
        while self._records and self._records[0].timestamp_epoch < cutoff:
            self._records.popleft()

    def __len__(self):
        self._flush_expired()
        return len(self._records)


# ═══════════════════════════════════════════════════════════
#  状态机
# ═══════════════════════════════════════════════════════════

class StateMachine:
    """VPN连接状态机"""

    def __init__(self):
        self.state = VPNState.IDLE
        self.state_history: List[Tuple[float, VPNState]] = []
        self.current_server: str = ""
        self.previous_server: str = ""
        self.state_since: float = time.time()  # 进入当前状态的时间
        self._mark_state(VPNState.IDLE)

    def _mark_state(self, state: VPNState):
        self.state = state
        self.state_since = time.time()
        self.state_history.append((self.state_since, state))

    @property
    def time_in_state(self) -> float:
        return time.time() - self.state_since

    def can_connect(self) -> bool:
        """是否允许connect事件"""
        return self.state in (VPNState.IDLE, VPNState.DISCONNECTED)

    def can_switch(self) -> bool:
        """是否允许switch事件"""
        return self.state == VPNState.CONNECTED

    def can_disconnect(self) -> bool:
        """是否允许disconnect事件"""
        return self.state == VPNState.CONNECTED

    def can_reconnect(self) -> bool:
        """是否允许reconnect事件"""
        if self.state != VPNState.DISCONNECTED:
            return False
        # 检查DISCONNECT事件发生时间
        for ts, st in reversed(self.state_history):
            if st == VPNState.DISCONNECTED:
                return (time.time() - ts) <= RECONNECT_MAX
        return False

    def transition(self, event_type: str, server: str, server_previous: str = "") -> VPNState:
        """执行状态转换，返回之前的状态"""
        before = self.state

        if event_type == "vpn_connect":
            if self.state in (VPNState.IDLE, VPNState.DISCONNECTED):
                self.current_server = server
                self._mark_state(VPNState.CONNECTING)

        elif event_type == "vpn_disconnect":
            self.previous_server = self.current_server
            self.current_server = ""
            self._mark_state(VPNState.DISCONNECTED)

        elif event_type == "vpn_switch":
            self.previous_server = self.current_server
            self.current_server = server
            self._mark_state(VPNState.SWITCHING)

        elif event_type == "vpn_reconnect":
            self.previous_server = self.current_server
            self.current_server = server
            self._mark_state(VPNState.CONNECTING)

        return before

    def confirm_connecting(self, server: str) -> bool:
        """确认连接稳定 → CONNECTED"""
        if self.state == VPNState.CONNECTING and self.time_in_state >= CONFIRM_DELAY:
            self.current_server = server
            self._mark_state(VPNState.CONNECTED)
            return True
        return False

    def confirm_switch(self, server: str) -> bool:
        """确认切换稳定 → CONNECTED"""
        if self.state == VPNState.SWITCHING and self.time_in_state >= SWITCH_SETTLE:
            self.current_server = server
            self._mark_state(VPNState.CONNECTED)
            return True
        return False

    def abort_connecting(self):
        """连接确认超时 → 回退IDLE"""
        if self.state == VPNState.CONNECTING and self.time_in_state > 15:
            self._mark_state(VPNState.IDLE)

    def check_disconnect(self, last_vpn_time: Optional[float]) -> bool:
        """检查是否需要断开"""
        if self.state == VPNState.CONNECTED:
            if last_vpn_time is None:
                return self.time_in_state > DISCONNECT_TTL
            return (time.time() - last_vpn_time) > DISCONNECT_TTL
        return False


# ═══════════════════════════════════════════════════════════
#  关键词匹配器
# ═══════════════════════════════════════════════════════════

class KeywordMatcher:
    """VPN关键词匹配与分类"""

    @staticmethod
    def analyze_domain(domain: str) -> Tuple[bool, str, List[str]]:
        """
        分析域名是否VPN相关
        Returns: (is_vpn, level, matched_keywords)
        """
        if not domain:
            return (False, "", [])

        domain_lower = domain.lower().rstrip(".")

        # 1. 先检查排除列表
        for ex in EXCLUDE_DOMAINS:
            if ex in domain_lower:
                # 进一步检查：排除词是否作为独立组件出现
                parts = domain_lower.split(".")
                if ex in parts:
                    return (False, "", [])

        # 2. 检查高置信度关键词
        matched_high = []
        for kw in VPN_KEYWORDS_HIGH:
            if kw in domain_lower:
                # 避免子串误匹配 (e.g. "svpn" matches "vpn" → valid)
                matched_high.append(kw)

        if matched_high:
            return (True, "high", matched_high)

        # 3. 检查中置信度关键词
        matched_med = []
        for kw in VPN_KEYWORDS_MED:
            if kw in domain_lower:
                matched_med.append(kw)

        if matched_med:
            # 中置信度需要 ≥2 个匹配才认定
            if len(matched_med) >= 2:
                return (True, "medium", matched_med)

        # 4. 无匹配
        return (False, "", [])

    @staticmethod
    def is_same_host(a: str, b: str) -> bool:
        """判断两个服务器标识是否属于同一主机"""
        if not a or not b:
            return False
        a = a.lower().rstrip(".")
        b = b.lower().rstrip(".")

        if a == b:
            return True

        # 提取主域名 (最后两段)
        def main_domain(s):
            parts = s.split(".")
            if len(parts) >= 2:
                return ".".join(parts[-2:])
            return s

        return main_domain(a) == main_domain(b)


# ═══════════════════════════════════════════════════════════
#  置信度计算器
# ═══════════════════════════════════════════════════════════

class ConfidenceCalculator:
    """加权置信度计算"""

    @staticmethod
    def calculate(signals: List[SignalRecord], known_servers: Set[str]) -> float:
        """
        计算一组信号的VPN置信度
        - weight: 高(0.3) / 中(0.2) / 低(0.1)
        - novelty_factor: 新信号=1.0, 已知=0.5
        """
        if not signals:
            return 0.0

        total_weight = 0.0
        max_possible = len(signals) * WEIGHT_HIGH

        for sig in signals:
            if not sig.is_vpn_related:
                continue

            # 基础权重
            if sig.vpn_level == "high":
                w = WEIGHT_HIGH
            elif sig.vpn_level == "medium":
                w = WEIGHT_MED
            else:
                w = WEIGHT_LOW

            # 新颖度因子
            server_id = sig.tls_sni or sig.dns_query or sig.ip_dst
            novelty = 1.0 if server_id not in known_servers else 0.5

            total_weight += w * novelty

        if max_possible == 0:
            return 0.0

        confidence = total_weight / max_possible
        return min(confidence, 1.0)

    @staticmethod
    def calculate_disconnect(vpn_activity_count: int, total_activity_count: int,
                              time_since_last_vpn: float) -> float:
        """计算断开的置信度"""
        if total_activity_count == 0:
            return 0.3  # 网络整体空闲，置信度低

        # VPN活动占比越低，断开可能性越高
        vpn_ratio = vpn_activity_count / max(total_activity_count, 1)
        inactivity_factor = 1.0 - vpn_ratio

        # 时间因素
        time_factor = min(time_since_last_vpn / DISCONNECT_TTL, 1.0)

        return min(0.3 * inactivity_factor + 0.7 * time_factor, 1.0)


# ═══════════════════════════════════════════════════════════
#  行为分析器
# ═══════════════════════════════════════════════════════════

class BehaviorAnalyzer:
    """VPN行为规则引擎"""

    def __init__(self, state_machine: StateMachine, keyword_matcher: KeywordMatcher):
        self.state = state_machine
        self.kw = keyword_matcher
        self.calc = ConfidenceCalculator()

        # 已知服务器集合 (用于新颖度)
        self.known_servers: Set[str] = set()

        # 事件冷却
        self.last_event_time: Dict[str, float] = {}

        # 整体流量统计
        self.total_signals_all_time: int = 0
        self.vpn_signals_all_time: int = 0

    def _is_cooling(self, event_type: str) -> bool:
        """检查事件是否在冷却期内"""
        last = self.last_event_time.get(event_type, 0)
        return (time.time() - last) < COOLDOWN_SAME

    def _mark_event(self, event_type: str):
        self.last_event_time[event_type] = time.time()

    def _extract_server_id(self, sig: SignalRecord) -> str:
        return sig.tls_sni or sig.dns_query or sig.ip_dst

    def _get_primary_server(self, signals: List[SignalRecord]) -> str:
        """从信号列表中提取主要服务器"""
        # 优先TLS SNI
        for sig in sorted(signals, key=lambda s: (
            3 if s.vpn_level == "high" else 2 if s.vpn_level == "medium" else 1
        ), reverse=True):
            sid = self._extract_server_id(sig)
            if sid:
                return sid
        return "unknown"

    # --- 检测规则 ---

    def detect_connect(self, burst_window: TimeWindow, session_window: TimeWindow) -> Optional[VPNEvent]:
        """检测VPN连接"""
        if not self.state.can_connect():
            return None
        if self._is_cooling("vpn_connect"):
            return None

        burst_signals = burst_window.get_active()
        vpn_signals = [s for s in burst_signals if s.is_vpn_related]

        # 条件1: BURST窗口 ≥2个高置信度VPN信号
        high_signals = [s for s in vpn_signals if s.vpn_level == "high"]

        # 条件2: 或单个高置信度TLS SNI + session窗口内有持续流量
        has_sustained = False
        if len(high_signals) == 1 and high_signals[0].tls_sni:
            session_vpn = session_window.count_vpn()
            has_sustained = session_vpn >= 3

        if len(high_signals) >= 2 or (len(high_signals) >= 1 and has_sustained):
            confidence = self.calc.calculate(vpn_signals, self.known_servers)

            if confidence >= MIN_CONFIDENCE_CONNECT:
                server = self._get_primary_server(high_signals)
                self.known_servers.add(server)
                self._mark_event("vpn_connect")

                dns_list = list({s.dns_query for s in vpn_signals if s.dns_query})
                sni_list = list({s.tls_sni for s in vpn_signals if s.tls_sni})
                ip_list  = list({s.ip_dst for s in vpn_signals if s.ip_dst})

                return VPNEvent(
                    event_type="vpn_connect",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    timestamp_epoch=time.time(),
                    server=server,
                    confidence=round(confidence, 3),
                    signals={"dns": dns_list, "tls_sni": sni_list, "ip_dst": ip_list},
                    trigger_reason=f"BURST窗口内{len(high_signals)}个高置信度VPN信号",
                    state_before=self.state.state.value,
                    state_after="connecting",
                )

        return None

    def detect_disconnect(self, gone_window: TimeWindow,
                           total_window: TimeWindow) -> Optional[VPNEvent]:
        """检测VPN断开"""
        if not self.state.can_disconnect():
            return None
        if self._is_cooling("vpn_disconnect"):
            return None

        vpn_count = gone_window.count_vpn()
        total_count = len(gone_window.get_active())

        last_vpn = gone_window.last_vpn_time()

        # 条件: GONE窗口内无VPN活动 且 整体网络有活动(排除网络空闲)
        if self.state.check_disconnect(last_vpn) and total_count > 0:
            confidence = self.calc.calculate_disconnect(
                vpn_count, total_count,
                time.time() - (last_vpn or time.time())
            )

            if confidence >= MIN_CONFIDENCE_DISCONNECT:
                self._mark_event("vpn_disconnect")
                server = self.state.current_server

                return VPNEvent(
                    event_type="vpn_disconnect",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    timestamp_epoch=time.time(),
                    server=server,
                    confidence=round(confidence, 3),
                    signals={"dns": [], "tls_sni": [], "ip_dst": []},
                    trigger_reason=f"GONE窗口({WINDOW_GONE}s)内无VPN活动",
                    state_before=self.state.state.value,
                    state_after="disconnected",
                )

        return None

    def detect_switch(self, switch_window: TimeWindow) -> Optional[VPNEvent]:
        """检测VPN服务器切换"""
        if not self.state.can_switch():
            return None
        if self._is_cooling("vpn_switch"):
            return None

        switch_signals = switch_window.get_active()
        vpn_signals = [s for s in switch_signals if s.is_vpn_related]

        if len(vpn_signals) < 2:
            return None

        # 提取新旧服务器
        current_server = self.state.current_server
        new_servers = set()
        for sig in vpn_signals:
            sid = self._extract_server_id(sig)
            if sid and sid != current_server:
                # 排除同主机
                if not self.kw.is_same_host(sid, current_server):
                    new_servers.add(sid)

        if new_servers:
            # 取最常见的服务器
            server_counts = defaultdict(int)
            for sig in vpn_signals:
                sid = self._extract_server_id(sig)
                if sid in new_servers:
                    server_counts[sid] += 1

            new_server = max(server_counts, key=server_counts.get)

            confidence = self.calc.calculate(vpn_signals, self.known_servers)

            if confidence >= MIN_CONFIDENCE_SWITCH:
                self.known_servers.add(new_server)
                self._mark_event("vpn_switch")

                dns_list = list({s.dns_query for s in vpn_signals if s.dns_query})
                sni_list = list({s.tls_sni for s in vpn_signals if s.tls_sni})
                ip_list  = list({s.ip_dst for s in vpn_signals if s.ip_dst})

                return VPNEvent(
                    event_type="vpn_switch",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    timestamp_epoch=time.time(),
                    server=new_server,
                    server_previous=current_server,
                    confidence=round(confidence, 3),
                    signals={"dns": dns_list, "tls_sni": sni_list, "ip_dst": ip_list},
                    trigger_reason=f"服务器从 {current_server} 切换到 {new_server}",
                    state_before=self.state.state.value,
                    state_after="switching",
                )

        return None

    def detect_reconnect(self, burst_window: TimeWindow) -> Optional[VPNEvent]:
        """检测VPN重连"""
        if not self.state.can_reconnect():
            return None
        if self._is_cooling("vpn_reconnect"):
            return None

        vpn_signals = [s for s in burst_window.get_active() if s.is_vpn_related]
        high_signals = [s for s in vpn_signals if s.vpn_level == "high"]

        if len(high_signals) >= 1:
            confidence = self.calc.calculate(vpn_signals, self.known_servers)

            if confidence >= MIN_CONFIDENCE_RECONNECT:
                server = self._get_primary_server(high_signals)
                prev = self.state.previous_server
                self._mark_event("vpn_reconnect")

                dns_list = list({s.dns_query for s in vpn_signals if s.dns_query})
                sni_list = list({s.tls_sni for s in vpn_signals if s.tls_sni})
                ip_list  = list({s.ip_dst for s in vpn_signals if s.ip_dst})

                return VPNEvent(
                    event_type="vpn_reconnect",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    timestamp_epoch=time.time(),
                    server=server,
                    server_previous=prev,
                    confidence=round(confidence, 3),
                    signals={"dns": dns_list, "tls_sni": sni_list, "ip_dst": ip_list},
                    trigger_reason=f"断开后{int(time.time()-self.state.state_since)}s重新检测到VPN流量",
                    state_before=self.state.state.value,
                    state_after="connecting",
                )

        return None


# ═══════════════════════════════════════════════════════════
#  信号采集器
# ═══════════════════════════════════════════════════════════

class SignalCollector:
    """信号收集 + 滑动窗口管理"""

    def __init__(self, kw_matcher: KeywordMatcher):
        self.kw = kw_matcher

        # 四个滑动窗口
        self.win_burst   = TimeWindow(WINDOW_BURST)
        self.win_switch  = TimeWindow(WINDOW_SWITCH)
        self.win_session = TimeWindow(WINDOW_SESSION)
        self.win_gone    = TimeWindow(WINDOW_GONE)

        # 总窗口(对比整体网络活动用)
        self.win_total   = TimeWindow(WINDOW_GONE)

        # 汇总统计
        self.total_dns = 0
        self.total_tls = 0
        self.total_vpn_signals = 0
        self.total_signals = 0

    def process_line(self, line: str) -> Optional[SignalRecord]:
        """解析tshark输出行，返回SignalRecord或None"""
        parts = line.strip().split("\t")

        if len(parts) < 6:
            return None

        ts, src, dst, dns, sni, proto = parts[:6]
        tcp_flags = parts[6] if len(parts) > 6 else ""
        ip_ttl    = parts[7] if len(parts) > 7 else ""

        # 时间解析
        timestamp = ts.strip() if ts else ""
        epoch = time.time()

        # 分类: DNS / TLS / 其他
        domain = dns.strip() if dns else sni.strip() if sni else ""
        is_vpn, level, keywords = self.kw.analyze_domain(domain)

        # 对IP目标的额外检查 (无DNS/SNI时的低置信度判断)
        if not domain and dst.strip():
            ip_dst = dst.strip()
            # 简单启发: 排除私有IP
            if not self._is_private_ip(ip_dst):
                # IP直接连接 + 无DNS → 可能是低置信度VPN
                pass  # 暂不做IP级别的判断，保留扩展点

        record = SignalRecord(
            timestamp_epoch=epoch,
            timestamp=timestamp,
            dns_query=dns.strip() if dns else "",
            tls_sni=sni.strip() if sni else "",
            ip_dst=dst.strip() if dst else "",
            ip_src=src.strip() if src else "",
            proto=proto.strip() if proto else "",
            tcp_flags=tcp_flags.strip() if tcp_flags else "",
            ip_ttl=ip_ttl.strip() if ip_ttl else "",
            is_vpn_related=is_vpn,
            vpn_keywords=keywords,
            vpn_level=level,
        )

        # 录入所有窗口和统计
        self.win_burst.add(record)
        self.win_switch.add(record)
        self.win_session.add(record)
        self.win_gone.add(record)
        self.win_total.add(record)

        self.total_signals += 1
        if dns:
            self.total_dns += 1
        if sni:
            self.total_tls += 1
        if is_vpn:
            self.total_vpn_signals += 1

        return record

    @staticmethod
    def _is_private_ip(ip: str) -> bool:
        """检查是否为私有IP"""
        if not ip:
            return False
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        try:
            octets = [int(p) for p in parts]
        except ValueError:
            return False
        if octets[0] == 10:
            return True
        if octets[0] == 172 and 16 <= octets[1] <= 31:
            return True
        if octets[0] == 192 and octets[1] == 168:
            return True
        if octets[0] == 127:
            return True
        return False

    def get_stats(self) -> dict:
        return {
            "total_signals": self.total_signals,
            "total_dns": self.total_dns,
            "total_tls": self.total_tls,
            "total_vpn_signals": self.total_vpn_signals,
            "burst_window": len(self.win_burst),
            "session_window": len(self.win_session),
            "gone_window": len(self.win_gone),
        }


# ═══════════════════════════════════════════════════════════
#  事件输出器
# ═══════════════════════════════════════════════════════════

class EventReporter:
    """事件格式化输出 (控制台 + JSONL)"""

    COLOR_RESET  = "\033[0m"
    COLOR_GREEN  = "\033[92m"
    COLOR_YELLOW = "\033[93m"
    COLOR_RED    = "\033[91m"
    COLOR_CYAN   = "\033[96m"
    COLOR_BOLD   = "\033[1m"

    EVENT_STYLES = {
        "vpn_connect":    (COLOR_GREEN,  "═══ VPN CONNECT ═══"),
        "vpn_disconnect": (COLOR_RED,    "═══ VPN DISCONNECT ═══"),
        "vpn_switch":     (COLOR_YELLOW, "═══ VPN SWITCH ═══"),
        "vpn_reconnect":  (COLOR_CYAN,   "═══ VPN RECONNECT ═══"),
    }

    def __init__(self, output_path: str):
        self.output_path = output_path
        self.event_count = 0
        self._ensure_file()

    def _ensure_file(self):
        """确保输出文件存在"""
        if not os.path.exists(self.output_path):
            with open(self.output_path, "w", encoding="utf-8") as f:
                pass

    def report(self, event: VPNEvent, sm: StateMachine, collector: SignalCollector):
        """输出事件到控制台和文件"""
        self.event_count += 1

        # 控制台输出
        style = self.EVENT_STYLES.get(event.event_type,
                                       (self.COLOR_RESET, f"=== {event.event_type.upper()} ==="))
        color, header = style

        print(f"\n{color}{self.COLOR_BOLD}{header}{self.COLOR_RESET}")
        print(f"  Server:      {event.server}")
        if event.server_previous:
            print(f"  Previous:    {event.server_previous}")
        print(f"  Confidence:  {event.confidence:.3f}")
        print(f"  Reason:      {event.trigger_reason}")
        print(f"  State:       {event.state_before} → {event.state_after}")

        # 信号详情
        sigs = event.signals
        if sigs.get("dns"):
            print(f"  DNS:         {', '.join(sigs['dns'][:5])}")
        if sigs.get("tls_sni"):
            print(f"  TLS SNI:     {', '.join(sigs['tls_sni'][:5])}")
        if sigs.get("ip_dst"):
            print(f"  IP Dst:      {', '.join(sigs['ip_dst'][:5])}")

        # 当前窗口统计
        stats = collector.get_stats()
        print(f"  ────────────────────────────────────")
        print(f"  Burst VPN:   {collector.win_burst.count_vpn()}/{len(collector.win_burst)}")
        print(f"  Session VPN: {collector.win_session.count_vpn()}/{len(collector.win_session)}")
        print(f"  Total:       {stats['total_signals']} signals, "
              f"{stats['total_vpn_signals']} VPN-related")
        print(f"{color}────────────────────────────────────{self.COLOR_RESET}")

        # 写入JSONL
        event_dict = asdict(event)
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event_dict, ensure_ascii=False) + "\n")

    def summary(self, sm: StateMachine, collector: SignalCollector):
        """输出阶段性摘要"""
        stats = collector.get_stats()
        color = self.COLOR_BOLD

        print(f"\n{color}╔══════ SUMMARY (60s) ══════════╗{self.COLOR_RESET}")
        print(f"  State:       {sm.state.value}")
        print(f"  Server:      {sm.current_server or 'N/A'}")
        print(f"  TimeInState: {sm.time_in_state:.0f}s")
        print(f"  Events:      {self.event_count}")
        print(f"  Signals:     {stats['total_signals']} "
              f"(DNS:{stats['total_dns']} TLS:{stats['total_tls']})")
        print(f"  VPN signals: {stats['total_vpn_signals']}")
        print(f"  Windows:     B={stats['burst_window']} "
              f"S={stats['session_window']} G={stats['gone_window']}")
        print(f"{color}╚════════════════════════════════╝{self.COLOR_RESET}")


# ═══════════════════════════════════════════════════════════
#  网卡自动选择
# ═══════════════════════════════════════════════════════════

def list_interfaces() -> List[Tuple[int, str]]:
    """列出所有网卡，返回 [(index, description), ...]"""
    result = subprocess.run(
        [TSHARK_PATH, "-D"],
        capture_output=True,
        text=False,
    )
    stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
    stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

    if not stdout:
        raise Exception("tshark -D 无输出。请以管理员身份运行，并检查 Wireshark 安装路径。")

    interfaces = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # 格式: "1. \Device\NPF_{...} (Wi-Fi)" 或 "1. ..."
        try:
            idx_str = line.split(".")[0]
            index = int(idx_str)
            desc = line[len(idx_str) + 2:].strip()  # 去掉 "1. "
            interfaces.append((index, desc))
        except (ValueError, IndexError):
            continue

    return interfaces


def select_interface() -> int:
    """智能选择抓包网卡"""
    interfaces = list_interfaces()

    print("\n[可用网卡]")
    for idx, desc in interfaces:
        # 标出推荐类型
        tags = []
        desc_lower = desc.lower()
        if any(k in desc_lower for k in ("wlan", "wi-fi", "wireless", "无线")):
            tags.append("★ WIFI")
        if any(k in desc_lower for k in ("tap", "tun", "vpn", "virtual", "openvpn", "wireguard")):
            tags.append("◇ VPN虚拟")
        if any(k in desc_lower for k in ("ethernet", "以太网", "local")):
            tags.append("■ 有线")
        tag_str = " ".join(tags) if tags else ""
        print(f"  [{idx}] {desc}  {tag_str}")

    # 自动选择策略：优先WLAN → VPN虚拟 → 有线
    wlan_idx = None
    vpn_idx = None
    eth_idx = None

    for idx, desc in interfaces:
        dl = desc.lower()
        if any(k in dl for k in ("wlan", "wi-fi", "wireless", "无线")):
            wlan_idx = wlan_idx or idx
        if any(k in dl for k in ("tap", "tun", "vpn-virtual", "openvpn", "wireguard")):
            vpn_idx = vpn_idx or idx
        if any(k in dl for k in ("ethernet", "以太网")) and eth_idx is None:
            eth_idx = eth_idx or idx

    chosen = wlan_idx or vpn_idx or eth_idx or interfaces[0][0]
    chosen_desc = next((d for i, d in interfaces if i == chosen), "?")

    print(f"\n[AUTO] 选择 [{chosen}] {chosen_desc}")
    print(f"[提示] VPN 连接前请先启动本工具，否则会错过连接建立时的 DNS/TLS 信号。")
    print(f"[提示] 如果仍无输出，请以管理员身份运行。\n")

    return chosen


def get_wlan_index() -> int:
    """兼容旧接口"""
    return select_interface()


# ═══════════════════════════════════════════════════════════
#  tshark 启动
# ═══════════════════════════════════════════════════════════

def start_tshark(interface_index: int) -> subprocess.Popen:
    """
    启动 tshark 实时抓包
    增强字段: 添加 frame.time_epoch, tcp.flags, ip.ttl, dns.flags.response, ip.proto
    """
    cmd = [
        TSHARK_PATH,
        "-i", str(interface_index),
        "-l", "-n",
        "-T", "fields",
        # 基本信息
        "-e", "frame.time",
        "-e", "ip.src",
        "-e", "ip.dst",
        "-e", "dns.qry.name",
        "-e", "tls.handshake.extensions_server_name",
        "-e", "_ws.col.Protocol",
        # 增强字段
        "-e", "tcp.flags",
        "-e", "ip.ttl",
        "-e", "dns.flags.response",
        "-e", "ip.proto",
    ]

    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=False,
        bufsize=1,
    )


# ═══════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════

def run():
    print("\n╔══════════════════════════════════════════╗")
    print("║   VPN 行为识别系统 v2.0                  ║")
    print("║   State-Machine Driven Analysis Engine  ║")
    print("╚══════════════════════════════════════════╝")
    print(f"\n  Windows: BURST={WINDOW_BURST}s SWITCH={WINDOW_SWITCH}s "
          f"GONE={WINDOW_GONE}s")
    print(f"  Confirm: {CONFIRM_DELAY}s | Cooldown: {COOLDOWN_SAME}s")

    # 初始化组件
    idx = get_wlan_index()
    kw_matcher = KeywordMatcher()
    state_machine = StateMachine()
    collector = SignalCollector(kw_matcher)
    analyzer = BehaviorAnalyzer(state_machine, kw_matcher)
    reporter = EventReporter(OUTPUT_FILE)

    print("\n[INFO] 启动 tshark 抓包...")
    proc = start_tshark(idx)

    last_summary = time.time()
    packet_count = 0
    start_time = time.time()

    try:
        for raw_line in proc.stdout:
            # Windows 二进制管道 → 手动 UTF-8 解码
            line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line
            if not line.strip():
                continue

            packet_count += 1

            # 启动10秒无包 → 警告
            if packet_count <= 3 and time.time() - start_time > 10:
                print("\n[!] 10秒内仅收到少量数据包，请检查:")
                print("[!]   1. 是否以管理员身份运行 (必需!)")
                print("[!]   2. 网卡是否选对 (检查上方 [可用网卡] 列表)")
                print("[!]   3. 有网络活动吗 (打开浏览器触发流量)")
                start_time = float("inf")  # 只警告一次

            # 1. 解析信号
            record = collector.process_line(line)
            if record is None:
                continue

            # 2. 控制台实时输出 (简化)
            if record.is_vpn_related:
                tag = "[VPN]" if record.vpn_level == "high" else "[~]"
                domain = record.tls_sni or record.dns_query or record.ip_dst
                print(f"  {tag} {domain}  ({record.vpn_level})")

            # 3. 运行检测规则 (每次最多产生一个事件，收集后立即处理)
            new_events: List[VPNEvent] = []

            event = analyzer.detect_connect(collector.win_burst, collector.win_session)
            if event:
                new_events.append(event)

            event = analyzer.detect_disconnect(collector.win_gone, collector.win_total)
            if event:
                new_events.append(event)

            event = analyzer.detect_switch(collector.win_switch)
            if event:
                new_events.append(event)

            event = analyzer.detect_reconnect(collector.win_burst)
            if event:
                new_events.append(event)

            # 4. 处理事件并更新状态机
            for evt in new_events:
                before_state = evt.state_before
                state_machine.transition(
                    evt.event_type,
                    evt.server,
                    evt.server_previous,
                )
                evt.state_before = before_state
                evt.state_after = state_machine.state.value
                reporter.report(evt, state_machine, collector)

            # 5. 状态机维护
            # 确认CONNECTING稳定 → CONNECTED
            if state_machine.state == VPNState.CONNECTING:
                current_server = analyzer._get_primary_server(
                    [s for s in collector.win_session.get_active() if s.is_vpn_related]
                )
                if current_server:
                    if state_machine.confirm_connecting(current_server):
                        print(f"\n  [STATE] ✓ CONNECTED → {current_server}")

            # 确认SWITCHING稳定 → CONNECTED
            if state_machine.state == VPNState.SWITCHING:
                current_server = analyzer._get_primary_server(
                    [s for s in collector.win_switch.get_active() if s.is_vpn_related]
                )
                if current_server:
                    if state_machine.confirm_switch(current_server):
                        print(f"\n  [STATE] ✓ SWITCH SETTLED → {current_server}")

            # 超时回退
            state_machine.abort_connecting()

            # 6. 定期摘要
            now = time.time()
            if now - last_summary >= SUMMARY_INTERVAL:
                reporter.summary(state_machine, collector)
                last_summary = now

    except KeyboardInterrupt:
        print("\n\n[STOP] 用户中断")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

        # 最终导出
        final_export(state_machine, collector, reporter)

        print("\n╔══════════════════════════════════════════╗")
        print("║  分析完成                               ║")
        print(f"║  事件总数: {reporter.event_count:<30}║")
        print(f"║  输出文件: {OUTPUT_FILE:<30}║")
        print("╚══════════════════════════════════════════╝")


def final_export(sm: StateMachine, collector: SignalCollector, reporter: EventReporter):
    """最终摘要输出"""
    # 如果有未完成的状态转换，记录下来
    if sm.state == VPNState.CONNECTING:
        print(f"\n[WARN] 结束时仍在 CONNECTING 状态 ({sm.time_in_state:.0f}s)")

    if sm.state == VPNState.SWITCHING:
        print(f"\n[WARN] 结束时仍在 SWITCHING 状态 ({sm.time_in_state:.0f}s)")

    reporter.summary(sm, collector)

    # 写出统计补充文件
    stats_data = {
        "final_state": sm.state.value,
        "final_server": sm.current_server,
        "state_history": [
            {"time": ts, "state": st.value}
            for ts, st in sm.state_history
        ],
        "signal_stats": collector.get_stats(),
        "total_events": reporter.event_count,
    }

    with open("vpn_stats.json", "w", encoding="utf-8") as f:
        json.dump(stats_data, f, indent=2, ensure_ascii=False)

    print(f"\n[✓] 统计文件: vpn_stats.json")


# ═══════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    run()
