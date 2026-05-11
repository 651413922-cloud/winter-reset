"""
行为级 VPN 识别引擎核心 — Behavior Analyzer
完全基于流量结构性变化, 不依赖任何关键词匹配
"""

import time
from typing import Optional, List, Dict, Set, Tuple
from datetime import datetime, timezone

from . import config as cfg
from .models import FlowSignature, VPNEvent, VPNState, ConnectionGroup
from .flow_tracker import FlowTracker


class BehaviorAnalyzer:
    """
    行为分析引擎 — 核心检测逻辑
    完全基于流量结构性变化:
    - 连接爆发 (burst/new_ip)
    - 聚簇出现/消失 (cluster lifecycle)
    - 图结构变化 (density/entropy)
    """

    def __init__(self, tracker: FlowTracker):
        self.tracker = tracker
        # 已知实体 (用于新颖度计算)
        self._known_ips: Set[str] = set()
        self._known_clusters: Set[str] = set()
        # 特征签名
        self._baseline: Optional[FlowSignature] = None
        self._last_sig: Optional[FlowSignature] = None
        # 事件冷却
        self._cooldowns: Dict[str, float] = {}
        # 状态机
        self.state = VPNState.IDLE
        self.current_server = ""
        self.previous_server = ""
        self._state_since = time.time()
        self._state_history: List[Tuple[float, VPNState, str]] = []
        # 统计
        self.n_processed = 0
        self.n_analyzed = 0

    # ── 状态机 ──

    def _transition(self, s: VPNState, server: str = ""):
        self._state_history.append((time.time(), self.state, self.current_server))
        self.state = s
        self._state_since = time.time()
        if s in (VPNState.IDLE, VPNState.DISCONNECTED):
            self.previous_server = self.current_server
            self.current_server = ""
        else:
            self.current_server = server

    @property
    def _in_state(self) -> float:
        return time.time() - self._state_since

    def _can(self, s: VPNState) -> bool:
        return self.state == s

    def _cool(self, tag: str) -> bool:
        return (time.time() - self._cooldowns.get(tag, 0)) < cfg.COOLDOWN_SAME

    def _mark(self, tag: str):
        self._cooldowns[tag] = time.time()

    # ── 特征签名 ──

    def _sig(self, now: float) -> FlowSignature:
        af = self.tracker.get_active_flows(now - cfg.WINDOW_BURST)
        ips = self.tracker.get_unique_dst_ips(now - cfg.WINDOW_BURST)
        cs = self.tracker.get_ip_clusters(now - cfg.WINDOW_BURST)
        ni = ips - self._known_ips
        gs = self.tracker.graph.snapshot()
        tc = self.tracker.get_ttl_changes(now - cfg.WINDOW_BURST)
        tv = sum(tc.values()) / max(len(tc), 1)
        dr = [f.duration for f in af if f.duration > 0]
        return FlowSignature(now, len(ips), len(af), self.tracker.total_dns,
            self.tracker.total_tls, len(ips), gs["density"], gs["entropy"],
            len(cs), len(ni)/max(len(ips),1), tv, sum(dr)/max(len(dr),1))

    # ── CONNECT: 爆发检测 ──

    def _burst(self, now: float) -> Tuple[float, dict]:
        si = self.tracker.get_unique_dst_ips(now - cfg.WINDOW_BURST)
        li = self.tracker.get_unique_dst_ips(now - cfg.WINDOW_LONG)
        self._known_ips.update(li)
        ni = si - self._known_ips
        br = len(si) / max(len(li)-len(si), 1)
        nr = len(ni) / max(len(si), 1)
        ab = max(len(ni), len(si))
        d = {"short":len(si),"long":len(li),"new":len(ni),"burst_r":round(br,2),"novel_r":round(nr,2),"abs":ab}
        s = 0.0
        if br >= cfg.BURST_MULTIPLIER and ab >= cfg.BURST_MIN_ABS: s += 0.5
        if nr >= 0.5: s += 0.3
        if ab >= cfg.NOVEL_IP_MIN: s += 0.2
        return min(s, 1.0), d

    def _clusters(self, now: float) -> Tuple[float, list]:
        cs = self.tracker.get_ip_clusters(now - cfg.WINDOW_BURST)
        nc = []; sc = 0.0
        for cid, ips in cs.items():
            if cid not in self._known_clusters:
                ni = ips - self._known_ips
                if len(ni) >= cfg.CLUSTER_MIN_SIZE:
                    nc.append(cid); sc += min(len(ni)*0.15, 0.8)
        self._known_clusters.update(cs.keys())
        self._known_ips.update(self.tracker.get_unique_dst_ips())
        return min(sc, 1.0), nc

    def _surge(self, now: float) -> float:
        cur = self._sig(now)
        bl = self._baseline or cur
        return max(0.0, 1.0 - cur.similarity_to(bl)*2)

    def detect_connect(self, now: float) -> Optional[VPNEvent]:
        if self.state not in (VPNState.IDLE, VPNState.DISCONNECTED): return None
        if self._cool("connect"): return None
        bs, _ = self._burst(now)
        if bs < 0.3: return None
        cs, nc = self._clusters(now)
        sg = self._surge(now)
        ts = bs*0.45 + cs*0.35 + sg*0.20
        if ts < cfg.MIN_CONFIDENCE_CONNECT: return None
        sv = self._extract(nc, now)
        self._mark("connect"); self._transition(VPNState.CONNECTING, sv)
        return VPNEvent("vpn_connect", datetime.now(timezone.utc).isoformat(),
            now, sv, round(ts,3), {}, f"爆发{bs:.2f}+聚簇{cs:.2f}+图{sg:.2f}",
            self.state.value, VPNState.CONNECTING.value,
            {"burst":round(bs,3),"cluster":round(cs,3),"surge":round(sg,3),"total":round(ts,3)})

    def detect_disconnect(self, now: float) -> Optional[VPNEvent]:
        if self.state != VPNState.CONNECTED: return None
        if self._cool("disconnect"): return None
        cs = self.tracker.get_ip_clusters(now - cfg.WINDOW_BURST)
        cc = len(cs)
        gg = 1 if (self._known_clusters and cc < len(self._known_clusters)*0.5) else 0
        gs = self.tracker.graph.snapshot()
        me = max(self._last_sig.unique_dst_ips*2, 1) if self._last_sig else 1
        ed = gs["edges"]/me
        si = self.tracker.get_unique_dst_ips(now - cfg.WINDOW_BURST)
        li = self.tracker.get_unique_dst_ips(now - cfg.WINDOW_LONG)
        dd = 1.0 - (len(si)/max(len(li),1))
        tc = self.tracker.get_ttl_changes(now - cfg.WINDOW_BURST)
        tr = len([v for v in tc.values() if v >= cfg.TTL_HOP_THRESHOLD])/max(len(tc),1)
        s = (gg*0.4)+(ed<cfg.GRAPH_EDGE_DECAY)*0.3+(dd>0.5)*0.2+(tr>cfg.TTL_CHANGE_RATIO)*0.1
        if s < cfg.MIN_CONFIDENCE_DISCONNECT: return None
        self._mark("disconnect")
        ps = self.current_server; self._transition(VPNState.DISCONNECTED)
        return VPNEvent("vpn_disconnect", datetime.now(timezone.utc).isoformat(),
            now, ps, round(s,3), {},
            f"组消失(prev={len(self._known_clusters)},cur={cc})+拓扑(ed={ed:.2f})",
            VPNState.CONNECTED.value, VPNState.DISCONNECTED.value,
            {"groups_gone":gg,"edge_decay":round(ed,3),"ip_drop":round(dd,3),"ttl":round(tr,3),"total":round(s,3)})

    def detect_switch(self, now: float) -> Optional[VPNEvent]:
        if self.state != VPNState.CONNECTED: return None
        if self._cool("switch"): return None
        cs = self.tracker.get_ip_clusters(now - cfg.WINDOW_MEDIUM)
        oc = self._known_clusters.copy() or set()
        cc = set(cs.keys()); vn = oc-cc; ap = cc-oc
        if len(vn)<1 or len(ap)<1: return None
        cur = self._sig(now)
        ec = abs(cur.graph_entropy-self._last_sig.graph_entropy) if self._last_sig else 0.0
        cr = len(ap)/max(len(cc),1)
        s = 0.4 + (cr>=cfg.CLUSTER_SHIFT_THRESH)*0.3 + (ec>0.3)*0.3
        if s < cfg.MIN_CONFIDENCE_SWITCH: return None
        ns = self._extract(list(ap), now); ps = self.current_server
        self._mark("switch"); self._transition(VPNState.SWITCHING, ns)
        return VPNEvent("vpn_switch", datetime.now(timezone.utc).isoformat(),
            now, ns, round(s,3), {}, f"切换(vn={len(vn)},ap={len(ap)})+熵Δ{ec:.2f}",
            VPNState.CONNECTED.value, VPNState.SWITCHING.value, {"vanished":len(vn),"appeared":len(ap),
            "entropy_delta":round(ec,3),"shift_ratio":round(cr,3),"total":round(s,3)})

    def detect_reconnect(self, now: float) -> Optional[VPNEvent]:
        if self.state != VPNState.DISCONNECTED: return None
        if self._cool("reconnect"): return None
        ok = False
        for ts, st, _ in reversed(self._state_history):
            if st == VPNState.DISCONNECTED: ok = (time.time()-ts) <= cfg.RECONNECT_MAX; break
        if not ok: return None
        cs = self.tracker.get_ip_clusters(now - cfg.WINDOW_BURST)
        rc = sum(1 for c in self._known_clusters if c in cs)
        if rc == 0: return None
        bs, _ = self._burst(now)
        if bs < 0.3: return None
        s = min(bs+0.2*rc, 1.0)
        if s < cfg.MIN_CONFIDENCE_RECONNECT: return None
        sv = self._extract(list(cs.keys()&self._known_clusters), now)
        self._mark("reconnect"); self._transition(VPNState.CONNECTING, sv)
        return VPNEvent("vpn_reconnect", datetime.now(timezone.utc).isoformat(),
            now, sv, round(s,3), {}, f"断开后{self._in_state:.0f}s聚簇重现({rc}个)",
            VPNState.DISCONNECTED.value, VPNState.CONNECTING.value,
            {"reconnected":rc,"burst":round(bs,3),"total":round(s,3)})

    def _extract(self, cids: list, now: float) -> str:
        if not cids: return "unknown"
        for h in self.tracker.get_tls_hosts().values():
            if h.last_seen >= now-cfg.WINDOW_BURST: return h.sni
        dc = self.tracker.get_dns_cache()
        if dc: return max(dc.values(), key=lambda e:e.last_seen).domain
        ips = self.tracker.get_unique_dst_ips(now-cfg.WINDOW_BURST)
        return list(ips)[0] if ips else f"c_{cids[0]}"

    # ── 状态机维护 ──

    def _maintain(self, now: float) -> Optional[VPNEvent]:
        if self.state == VPNState.CONNECTING:
            if self._in_state >= cfg.CONFIRM_DELAY:
                af = self.tracker.get_active_flows(now-cfg.WINDOW_BURST)
                if len(af)>=2:
                    sv=self.current_server; self._transition(VPNState.CONNECTED,sv)
                    return VPNEvent("vpn_connected",datetime.now(timezone.utc).isoformat(),
                        now,sv,1.0,{},f"延迟确认连接",VPNState.CONNECTING.value,VPNState.CONNECTED.value,{})
                if self._in_state >= cfg.CONFIRM_TIMEOUT:
                    self._transition(VPNState.IDLE)
        elif self.state == VPNState.SWITCHING:
            if self._in_state >= cfg.CONFIRM_DELAY:
                sv=self.current_server; self._transition(VPNState.CONNECTED,sv)
                return VPNEvent("vpn_switched",datetime.now(timezone.utc).isoformat(),
                    now,sv,1.0,{},f"切换确认",VPNState.SWITCHING.value,VPNState.CONNECTED.value,{})
        elif self.state == VPNState.CONNECTED:
            if self._in_state >= cfg.STALE_TIMEOUT:
                cs=self.tracker.get_ip_clusters(now-cfg.WINDOW_BURST)
                if not cs: self._transition(VPNState.DISCONNECTED)
        return None

    # ── 主入口 ──

    def analyze(self, now: float) -> Optional[VPNEvent]:
        self.n_analyzed += 1
        self._baseline = self._sig(now-cfg.WINDOW_LONG)
        ev = self._maintain(now)
        if ev: return ev
        if self._can(VPNState.CONNECTED):
            ev = self.detect_disconnect(now)
            if ev: return ev
            ev = self.detect_switch(now)
            if ev: return ev
        if self.state == VPNState.DISCONNECTED:
            ev = self.detect_reconnect(now)
            if ev: return ev
        ev = self.detect_connect(now)
        if ev: return ev
        self._last_sig = self._sig(now)
        return None

    def on_signal(self):
        self.n_processed += 1