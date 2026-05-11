#!/usr/bin/env python3
"""
行为级 VPN 识别引擎 - 入口点
取代 apiwireshark.py 的旧版关键词检测
使用 apivpn/ 行为分析引擎 (无关键词, 基于流量结构变化)
"""

import sys
import os
import time
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Optional, Tuple

# 确保可以找到 apivpn 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apivpn.config import (
    TSHARK_PATH, OUTPUT_FILE, STATS_FILE,
    WINDOW_BURST, WINDOW_SWITCH, WINDOW_SESSION, WINDOW_GONE,
    CONFIRM_DELAY, SWITCH_SETTLE, DISCONNECT_TTL, RECONNECT_MAX,
    SUMMARY_INTERVAL,
)
from apivpn.models import VPNState, VPNEvent
from apivpn.signal_collector import SignalCollector, PacketSignal
from apivpn.flow_tracker import FlowTracker
from apivpn.behavior_analyzer import BehaviorAnalyzer


# ═══════════════════════════════════════════════════════════
#  tshark 接口 (从 apiwireshark.py 提取, 无修改)
# ═══════════════════════════════════════════════════════════

def list_interfaces() -> List[Tuple[int, str]]:
    """列出所有网卡"""
    result = subprocess.run(
        [TSHARK_PATH, "-D"],
        capture_output=True,
        text=False,
    )
    stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
    stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

    if not stdout:
        raise RuntimeError("tshark -D 无输出。请以管理员身份运行，并检查 Wireshark 安装路径。")

    interfaces = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            idx_str = line.split(".")[0]
            index = int(idx_str)
            desc = line[len(idx_str) + 2:].strip()
            interfaces.append((index, desc))
        except (ValueError, IndexError):
            continue
    return interfaces


def select_interface() -> int:
    """智能选择网卡"""
    interfaces = list_interfaces()

    print("\n[可用网卡]")
    for idx, desc in interfaces:
        tags = []
        dl = desc.lower()
        if any(k in dl for k in ("wlan", "wi-fi", "wireless", "无线")):
            tags.append("★ WIFI")
        if any(k in dl for k in ("tap", "tun", "vpn", "virtual", "openvpn", "wireguard")):
            tags.append("◇ VPN虚拟")
        if any(k in dl for k in ("ethernet", "以太网", "local")):
            tags.append("■ 有线")
        tag_str = " ".join(tags) if tags else ""
        print(f"  [{idx}] {desc}  {tag_str}")

    wlan_idx = vpn_idx = eth_idx = None
    for idx, desc in interfaces:
        dl = desc.lower()
        if any(k in dl for k in ("wlan", "wi-fi", "wireless", "无线")):
            wlan_idx = wlan_idx or idx
        if any(k in dl for k in ("tap", "tun", "vpn-virtual", "openvpn", "wireguard")):
            vpn_idx = vpn_idx or idx
        if any(k in dl for k in ("ethernet", "以太网")):
            eth_idx = eth_idx or idx

    chosen = wlan_idx or vpn_idx or eth_idx or interfaces[0][0]
    chosen_desc = next((d for i, d in interfaces if i == chosen), "?")
    print(f"\n[AUTO] 选择 [{chosen}] {chosen_desc}")
    return chosen


def start_tshark(interface_index: int) -> subprocess.Popen:
    """启动 tshark 实时抓包"""
    cmd = [
        TSHARK_PATH,
        "-i", str(interface_index),
        "-l", "-n",
        "-T", "fields",
        "-e", "frame.time",
        "-e", "ip.src",
        "-e", "ip.dst",
        "-e", "dns.qry.name",
        "-e", "tls.handshake.extensions_server_name",
        "-e", "_ws.col.Protocol",
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
#  事件输出
# ═══════════════════════════════════════════════════════════

EVENT_ICONS = {
    "vpn_connect":    ("\033[92m", "🔗 "),
    "vpn_disconnect": ("\033[91m", "🔌 "),
    "vpn_switch":     ("\033[93m", "🔄 "),
    "vpn_reconnect":  ("\033[96m", "♻ "),
}
RESET = "\033[0m"
BOLD = "\033[1m"

event_count = 0


def output_event(event: VPNEvent):
    """输出事件到控制台和JSONL"""
    global event_count
    event_count += 1

    color, icon = EVENT_ICONS.get(event.event_type, ("", ""))
    
    print(f"\n{color}{BOLD}{icon} {event.event_type.upper()}{RESET}")
    print(f"  Server:      {event.server}")
    if event.previous_server:
        print(f"  Previous:    {event.previous_server}")
    print(f"  Confidence:  {event.confidence:.3f}")
    print(f"  Reason:      {event.reason}")
    
    if event.signals:
        sigs = event.signals
        if sigs.get("dns"):
            print(f"  DNS:         {', '.join(sigs['dns'][:5])}")
        if sigs.get("sni"):
            print(f"  SNI:         {', '.join(sigs['sni'][:5])}")
        if sigs.get("ips"):
            print(f"  IPs:         {', '.join(sigs['ips'][:5])}")
    
    print(f"  Metrics:     novelty={event.metrics.get('novelty',0):.3f} "
          f"burst={event.metrics.get('burst_factor',0):.1f}x")
    
    print(f"  State:       {event.state_before} → {event.state_after}")
    print(f"{color}────────────────────────────────────{RESET}")

    # JSONL输出
    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.write(event.to_json() + "\n")


# ═══════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════

def run():
    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║     ⚡ 网络行为分析引擎 (Behavior Detection Engine)        ║")
    print("║     IPv4 Flow Tracking · Graph Clustering · Behavior Rules ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    print(f"  窗口: BURST={WINDOW_BURST}s SWITCH={WINDOW_SWITCH}s "
          f"GONE={WINDOW_GONE}s")
    print(f"  检测方式: IP流量追踪 + DNS/TLS绑定 + 连接图聚类")
    print(f"  无需VPN关键词 · 基于流量结构变化判断")
    print()

    # 初始化行为引擎
    flow_tracker = FlowTracker()
    analyzer = BehaviorAnalyzer(flow_tracker)
    collector = SignalCollector()

    # 选择网卡并启动tshark
    try:
        idx = select_interface()
    except RuntimeError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)

    print("\n[INFO] 启动 tshark 抓包...")
    proc = start_tshark(idx)

    last_summary = time.time()
    start_time = time.time()
    packet_count = 0
    analysis_interval = 1.0  # 每1秒分析一次
    last_analysis = time.time()

    try:
        for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace")
            if not line.strip():
                continue

            packet_count += 1

            # 解析tshark输出 → PacketSignal
            signal = collector.parse_line(line)
            if signal is None:
                continue

            # 注入信号到flow tracker
            flow_tracker.process_signal(signal)

            # 实时显示新IP/域名
            if isinstance(signal, PacketSignal) and signal.dst_ip:
                if signal.dns_query:
                    flow_tracker.dns_to_ip.setdefault(signal.dns_query, set()).add(signal.dst_ip)
            
            # 周期性分析 (1s间隔)
            now = time.time()
            if now - last_analysis >= analysis_interval:
                event = analyzer.analyze(now)
                if event:
                    output_event(event)
                
                # 状态机维护
                analyzer.state_machine.maintain(now)
                last_analysis = now

            # 定期摘要 (60s)
            if now - last_summary >= SUMMARY_INTERVAL:
                stats = flow_tracker.get_stats()
                g = analyzer.graph
                current_state = analyzer.state_machine.state.value
                print(f"\n{BOLD}╔══ SUMMARY (60s) ═══════════════════╗{RESET}")
                print(f"  State:       {current_state}")
                print(f"  Server:      {flow_tracker.current_vpn_server or 'N/A'}")
                print(f"  Nodes:       {len(g.nodes)} IPs")
                print(f"  Edges:       {len(g.edges)}")
                print(f"  Density:     {g.density:.4f}")
                print(f"  Clusters:    {len(g.clusters)}")
                print(f"  Entropy:     {g.entropy:.4f}")
                print(f"  Packets:     {packet_count}")
                print(f"  Events:      {event_count}")
                print(f"  Novelty:     {flow_tracker.novelty_score:.3f}")
                print(f"{BOLD}╚════════════════════════════════════╝{RESET}")
                last_summary = now

    except KeyboardInterrupt:
        print(f"\n\n[STOP] 用户中断")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

        # 最终统计
        final_stats()

        print(f"\n╔══════════════════════════════════════════╗")
        print(f"║  分析完成                               ║")
        print(f"║  收包总数: {packet_count:<29}║")
        print(f"║  事件总数: {event_count:<29}║")
        print(f"║  输出文件: {OUTPUT_FILE:<29}║")
        print(f"║  状态文件: {STATS_FILE:<29}║")
        print(f"╚══════════════════════════════════════════╝")


def final_stats():
    """输出最终统计"""
    stats = {
        "total_events": event_count,
        "output_file": OUTPUT_FILE,
        "analysis_mode": "behavior_based",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run()