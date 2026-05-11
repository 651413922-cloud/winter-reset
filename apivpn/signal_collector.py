"""
信号采集器 — 从tshark读取实时数据并解析为PacketSignal

与apiwireshark.py的区别:
  原版: process_line → 调用KeywordMatcher.analyze_domain → 标记is_vpn_related
  新版: process_line → 直接解析为PacketSignal → 存入FlowTracker
        不判断是否VPN相关! 只做结构化解析!
"""

from typing import Optional

from .models import PacketSignal, SignalType


class SignalCollector:
    """
    信号采集器 — tshark输出解析

    只做两件事:
    1. 解析tshark的字段输出 → PacketSignal
    2. 分类信号类型 (DNS/TLS/TCP...)

    不做任何VPN判断 — 那是BehaviorAnalyzer的工作
    """

    def __init__(self):
        self.total_lines = 0
        self.total_signals = 0
        self.signal_types = {
            "dns": 0,
            "tls": 0,
            "tcp": 0,
            "other": 0,
        }

    def process_line(self, line: str) -> Optional[PacketSignal]:
        """
        解析tshark输出行 → PacketSignal

        输入格式(由tshark -T fields输出, tab分隔):
          frame.time  ip.src  ip.dst  dns.qry.name  tls.sni  proto  tcp.flags  ip.ttl  dns.flags.response  ip.proto

        Returns:
            PacketSignal对象, 无效行返回None
        """
        self.total_lines += 1

        parts = line.strip().split("\t")
        if len(parts) < 6:
            return None

        ts      = parts[0].strip()
        ip_src  = parts[1].strip()
        ip_dst  = parts[2].strip()
        dns_qry = parts[3].strip()
        tls_sni = parts[4].strip()
        proto   = parts[5].strip()
        tcp_flags = parts[6].strip() if len(parts) > 6 else ""
        ip_ttl    = parts[7].strip() if len(parts) > 7 else ""
        dns_resp  = parts[8].strip() if len(parts) > 8 else ""
        ip_proto  = parts[9].strip() if len(parts) > 9 else ""

        if not ip_src or not ip_dst:
            return None

        # 时间戳: 使用当前时间(因为frame.time_epoch不在字段中)
        import time
        epoch = time.time()
        ts_epoch = epoch

        # 解析协议号
        proto_num = 0
        try:
            proto_num = int(ip_proto) if ip_proto else 0
        except ValueError:
            pass

        # 解析端口 (从IP中无法直接获取, 依赖proto字段判断)
        src_port = 0
        dst_port = 0
        if ":" in ip_src and "." in ip_src:
            # 包含端口格式 "ip:port"
            parts_src = ip_src.rsplit(":", 1)
            if len(parts_src) == 2:
                try:
                    src_port = int(parts_src[1])
                    ip_src = parts_src[0]
                except ValueError:
                    pass
        if ":" in ip_dst and "." in ip_dst:
            parts_dst = ip_dst.rsplit(":", 1)
            if len(parts_dst) == 2:
                try:
                    dst_port = int(parts_dst[1])
                    ip_dst = parts_dst[0]
                except ValueError:
                    pass

        # 判断信号类型
        sig_type = SignalType.OTHER
        dns_answers = []
        is_dns_response = False

        if dns_qry:
            sig_type = SignalType.DNS_QUERY
            if dns_resp:
                # 响应标志存在
                try:
                    resp_flag = int(dns_resp)
                    is_dns_response = resp_flag == 1
                    sig_type = SignalType.DNS_RESPONSE
                except ValueError:
                    pass

            # DNS查询中可能包含应答IP (实际tshark需要额外字段)
            # 此处仅标记类型, IP解析在FlowTracker中关联

        elif tls_sni:
            sig_type = SignalType.TLS_SNI

        elif proto.upper() == "TCP":
            sig_type = SignalType.TCP_DATA
            if "SYN" in tcp_flags and "ACK" not in tcp_flags:
                sig_type = SignalType.TCP_SYN
            elif "RST" in tcp_flags:
                sig_type = SignalType.TCP_RST
            elif "FIN" in tcp_flags:
                sig_type = SignalType.TCP_FIN

        # 构建TTL
        ttl_int = 0
        try:
            ttl_int = int(ip_ttl) if ip_ttl else 0
        except ValueError:
            pass

        signal = PacketSignal(
            ts_epoch=ts_epoch,
            ip_src=ip_src,
            ip_dst=ip_dst,
            ip_proto=proto_num,
            src_port=src_port,
            dst_port=dst_port,
            tcp_flags=tcp_flags,
            ip_ttl=ttl_int,
            dns_query=dns_qry,
            dns_response=is_dns_response,
            dns_answers=dns_answers,
            tls_sni=tls_sni,
            signal_type=sig_type,
            raw_line=line.strip(),
        )

        self.total_signals += 1
        if sig_type in (SignalType.DNS_QUERY, SignalType.DNS_RESPONSE):
            self.signal_types["dns"] += 1
        elif sig_type == SignalType.TLS_SNI:
            self.signal_types["tls"] += 1
        elif sig_type in (SignalType.TCP_SYN, SignalType.TCP_DATA,
                          SignalType.TCP_RST, SignalType.TCP_FIN):
            self.signal_types["tcp"] += 1
        else:
            self.signal_types["other"] += 1

        return signal

    def get_stats(self) -> dict:
        return {
            "total_lines": self.total_lines,
            "total_signals": self.total_signals,
            **self.signal_types,
        }