"""
╔══════════════════════════════════════════════════════════════════╗
║      APIVPN - 网络行为分析引擎                                  ║
║      Behavior-driven VPN Detection Engine                       ║
║      不依赖关键词 · 基于流量结构变化判断 VPN                    ║
╚══════════════════════════════════════════════════════════════════╝

核心原理:
  现代VPN(如小熊加速器)不会在域名/SNI中包含"vpn/proxy"等关键词。
  本引擎通过分析 **网络流量结构性变化** 来识别VPN:

  ▸ 连接爆发: 突然出现大量到未知IP的TCP/TLS连接
  ▸ IP聚簇: 共享相同DNS解析的IP集合形成"连接组"
  ▸ 图谱转移: 连接重心从一个组转移到另一个组 = 切换
  ▸ 拓扑收缩: 连接组突然消失 = 断开
  ▸ 组复活: 之前消失的连接组再次活跃 = 重连

  检测指标(全部基于行为, 无关键词):
    - Novelty Score: 新IP/域名占比
    - Burst Factor: 连接密度爆发程度
    - Cluster Density: IP解析聚类紧密度
    - Protocol Mix: TLS/DNS混合使用模式
    - TTL Consistency: TTL跳数一致性
"""
from .vpn_control import is_vpn_online, attempt_switch_and_verify, click_replace_line, select_free_line