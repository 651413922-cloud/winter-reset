"""VPN Orchestrator - 配置常量 + 核心自动检测"""

import os
import json
import logging

logger = logging.getLogger(__name__)

# === v2rayN 客户端根目录 ===
BASE_DIR = os.environ.get('V2RAYN_ROOT', r"d:\useful\加速器\v2rayn")

# === 路径 ===
GUI_DB = os.path.join(BASE_DIR, 'guiConfigs', 'guiNDB.db')
GUI_NCONFIG_PATH = os.path.join(BASE_DIR, 'guiConfigs', 'guiNConfig.json')
CONFIG_JSON = os.path.join(BASE_DIR, 'binConfigs', 'config.json')
SING_BOX_CONFIG = os.path.join(BASE_DIR, 'binConfigs', 'configPre.json')
SING_BOX_EXE = os.path.join(BASE_DIR, 'bin', 'sing_box', 'sing-box.exe')
XRAY_EXE = os.path.join(BASE_DIR, 'bin', 'xray', 'xray.exe')

# === 核心类型 ===
CORE_TYPE_XRAY = 2
CORE_TYPE_SING_BOX = 24


def _read_gui_config() -> dict:
    """Read v2rayN GUI config to detect core type."""
    try:
        with open(GUI_NCONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def get_active_core_type() -> int:
    """
    Detect which core v2rayN is configured to use.

    Reads guiNConfig.json CoreTypeItem to find the core type for the
    active config. Falls back to Xray (2) if unreadable.

    Returns:
        CORE_TYPE_XRAY (2) or CORE_TYPE_SING_BOX (24)
    """
    gui = _read_gui_config()
    core_items = gui.get('CoreTypeItem', [])
    if core_items:
        # All items typically share the same CoreType
        ct = core_items[0].get('CoreType', CORE_TYPE_XRAY)
        return ct
    return CORE_TYPE_XRAY


def get_active_exe() -> str:
    """Get the correct proxy executable based on v2rayN's core type."""
    ct = get_active_core_type()
    if ct == CORE_TYPE_SING_BOX:
        return SING_BOX_EXE
    else:
        return XRAY_EXE


def get_active_config_format() -> str:
    """Get the config format matching the active core."""
    ct = get_active_core_type()
    if ct == CORE_TYPE_SING_BOX:
        return 'singbox'
    else:
        return 'xray'

# === 代理端口 ===
SOCKS5_HOST = '127.0.0.1'
SOCKS5_PORT = 10808  # fallback default


def get_socks_port_from_config() -> int:
    """Read the actual SOCKS inbound port from v2rayN's config.json."""
    try:
        with open(CONFIG_JSON, 'r', encoding='utf-8') as f:
            config = json.load(f)
        for ib in config.get('inbounds', []):
            if ib.get('protocol') in ('socks', 'mixed') or ib.get('type') in ('socks', 'mixed'):
                port = ib.get('port') or ib.get('listen_port', 0)
                if port:
                    return int(port)
    except Exception:
        pass
    return SOCKS5_PORT


def get_socks_proxy() -> str:
    """Get the SOCKS5 proxy URL with the actual port from config."""
    port = get_socks_port_from_config()
    return f'socks5://{SOCKS5_HOST}:{port}'


# === 连通性检测 ===
CHECK_URL = 'https://www.google.com/generate_204'
TIMEOUT = 20          # 秒

# === GUI 配置 ===
GUI_NCONFIG_PATH = os.path.join(BASE_DIR, 'guiConfigs', 'guiNConfig.json')

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