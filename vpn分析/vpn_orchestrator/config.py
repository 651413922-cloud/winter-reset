"""VPN Orchestrator - 配置常量"""

import os

# === 项目根目录 ===
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

# === 路径 ===
GUI_DB = os.path.join(BASE_DIR, 'guiConfigs', 'guiNDB.db')
CONFIG_JSON = os.path.join(BASE_DIR, 'binConfigs', 'config.json')
BACKUP_CONFIG_JSON = os.path.join(BASE_DIR, 'binConfigs', 'config.json.bak')
SING_BOX_EXE = os.path.join(BASE_DIR, 'bin', 'sing_box', 'sing-box.exe')
XRAY_EXE = os.path.join(BASE_DIR, 'bin', 'xray', 'xray.exe')

# === 代理端口 ===
SOCKS5_HOST = '127.0.0.1'
SOCKS5_PORT = 10808
SOCKS5_PROXY = f'socks5://{SOCKS5_HOST}:{SOCKS5_PORT}'
HTTP_PROXY = f'http://{SOCKS5_HOST}:{SOCKS5_PORT}'

# === 连通性检测 ===
CHECK_URL = 'https://www.google.com/generate_204'
TIMEOUT = 10          # 秒
SPEED_TEST_URL = 'https://cachefly.cachefly.net/50mb.test'

# === 浏览器目标 ===
BROWSER_TARGETS = [
    'https://chatgpt.com',
    'https://gemini.google.com',
]

# === 节点切换 ===
CONFIG_TYPE_VLESS_GRPC = 11   # ConfigType=11: VLESS+gRPC
CONFIG_TYPE_VLESS_VISION = 5  # ConfigType=5: VLESS+Vision+httpupgrade
CONFIG_TYPE_VMESS = 1         # ConfigType=1: VMess
CORE_TYPE_SING_BOX = 24       # CoreType=24: sing-box