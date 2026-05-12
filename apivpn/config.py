"""
行为引擎配置 — 所有可调参数集中管理
"""

# ══════════════════════════════════════════════════════════════════════
#  tshark 路径
# ══════════════════════════════════════════════════════════════════════
TSHARK_PATH = r"D:\useful\Wireshark\tshark.exe"

# ══════════════════════════════════════════════════════════════════════
#  时间窗口参数 (秒)
# ══════════════════════════════════════════════════════════════════════
WINDOW_BURST   = 8     # 爆发检测窗口 — 检测连接突增
WINDOW_SWITCH  = 15    # 切换检测窗口 — 监测簇迁移
WINDOW_SESSION = 60    # 会话窗口 — TTL/通联性基线
WINDOW_GONE    = 300   # 断开判定 — 多久无VPN活动判断开

# ══════════════════════════════════════════════════════════════════════
#  状态机参数 (秒)
# ══════════════════════════════════════════════════════════════════════
CONFIRM_DELAY    = 4    # CONNECTING→CONNECTED 确认等待
SWITCH_SETTLE    = 4    # SWITCHING→CONNECTED 稳定等待
DISCONNECT_TTL   = 60   # 无VPN流量多久判定断开
RECONNECT_MAX    = 120  # 断开后多久内算"重连"
COOLDOWN_SAME    = 8    # 同类事件最小间隔

# ══════════════════════════════════════════════════════════════════════
#  行为检测阈值 (完全基于流量结构, 无关键词)
# ══════════════════════════════════════════════════════════════════════

# --- 连接爆发检测 ---
# 短期连接数 / 历史均值 超过此值 → 爆发
BURST_MULTIPLIER    = 3.0
BURST_MIN_ABS       = 5     # 爆发最少连接数
IP_DIVERSITY_FACTOR = 2.0   # 新IP / 旧IP 比例阈值
NOVEL_IP_MIN        = 3     # 最少新IP数

# --- IP聚类 ---
CLUSTER_MIN_SIZE    = 2     # 一个聚簇最少IP数
GROUP_STALE_SECONDS = 300   # 连接组静默多久后移除

# --- DNS检测 ---
DNS_BURST_MULTIPLIER = 2.0  # DNS查询爆发倍数
DNS_NOVEL_RATIO      = 0.4  # 新域名占比

# --- TTL变化 ---
TTL_HOP_THRESHOLD    = 3    # TTL变化>3认为路径改变
TTL_CHANGE_RATIO     = 0.3  # ≥30%连接TTL变化

# --- 图分析 ---
GRAPH_DENSITY_SURGE  = 1.8  # 连接密度激增倍数
GRAPH_EDGE_DECAY     = 0.3  # 边数衰减到30%认为断开

# --- 断开检测 ---
SILENCE_PACKET_MIN   = 3    # 窗口内至少这么多包才算"有网络"

# ══════════════════════════════════════════════════════════════════════
#  加权评分参数 (行为评分, 非关键词评分)
# ══════════════════════════════════════════════════════════════════════
SCORE_WEIGHTS = {
    "novelty":   0.30,  # 新IP/域名占比 → VPN连接时大量新目标
    "burst":     0.25,  # 流量爆发程度 → VPN连接瞬间大量连接
    "cluster":   0.20,  # IP聚类密度 → VPN服务器共享DNS解析
    "diversity": 0.15,  # TLS/DNS混合度 → VPN同时有TLS和DNS
    "ttl":       0.10,  # TTL一致性 → VPN服务器跳数稳定
}

# --- 置信度阈值 ---
MIN_CONFIDENCE_CONNECT    = 0.50
MIN_CONFIDENCE_DISCONNECT = 0.45
MIN_CONFIDENCE_SWITCH     = 0.50
MIN_CONFIDENCE_RECONNECT  = 0.55

# ══════════════════════════════════════════════════════════════════════
#  输出配置
# ══════════════════════════════════════════════════════════════════════
SUMMARY_INTERVAL = 60
OUTPUT_FILE      = "vpn_events.jsonl"
STATS_FILE       = "vpn_stats.json"

# Remote webhook for event forwarding (empty = disabled)
WEBHOOK_URL = ""
WEBHOOK_ENABLED = False
WEBHOOK_TIMEOUT = 5  # seconds

# ══════════════════════════════════════════════════════════════════════
#  通用排除 (仅排除公共CDN/基础服务, 不排除任何VPN关键词)
# ══════════════════════════════════════════════════════════════════════
EXCLUDE_DOMAINS = {
    # 公共CDN
    "cloudflare", "cloudflare-dns", "cloudfront", "akamai",
    "akamaiedge", "akamaihd", "fastly", "fastlylb",
    # 搜索引擎
    "google", "googleapis", "gstatic", "google-analytics",
    # 微软
    "microsoft", "live", "office", "office365", "azure",
    # 苹果
    "apple", "icloud", "apple-dns",
    # 社交
    "facebook", "fbcdn", "instagram", "whatsapp",
    "twitter", "twimg", "x",
    # 云
    "amazon", "amazonaws", "aws",
    # 视频
    "youtube", "ytimg", "googlevideo",
    "netflix", "nflxvideo", "nflxext",
    "bilibili", "bilivideo",
    # 国内
    "baidu", "bdstatic",
    "alibaba", "alicdn", "taobao", "tmall",
    "tencent", "qq", "weixin", "wechat",
    "bytedance", "tiktok", "douyin",
    # 开发
    "github", "githubassets", "githubusercontent",
    "stackoverflow", "stackexchange",
    # 其他
    "wikipedia", "wikimedia",
    "dropbox", "box",
    "digicert", "letsencrypt", "globalsign",
    "ntp", "pool.ntp",
    "localhost", "local",
    # 系统
    "msftncsi", "connectivitycheck",
}