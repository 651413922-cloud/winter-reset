"""VPN Orchestrator - 配置常量 + v2rayN 安装自动发现"""

import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# === 版本号（属性面板与托盘标题共用单一常量） ===
__version__ = "1.1.0819"

# === v2rayN 安装根目录 — 自动发现 ===

def _discover_v2rayn_root() -> str:
    """
    Auto-discover v2rayN installation directory.

    Probe order:
      1. V2RAYN_ROOT env var (explicit override)
      2. Search running sing-box.exe process path
      3. Windows Registry (v2rayN installer key)
      4. Common installation paths
      5. Hardcoded fallback
    """
    # 1. Explicit override
    env = os.environ.get('V2RAYN_ROOT')
    if env and Path(env).exists():
        logger.debug('v2rayN root from V2RAYN_ROOT: %s', env)
        return env

    # 2. Running process path
    try:
        import psutil
        for proc in psutil.process_iter(['name', 'exe']):
            try:
                name = (proc.info.get('name') or '').lower()
                if name in ('sing-box.exe', 'sing-box', 'v2rayn.exe', 'xray.exe'):
                    exe = proc.info.get('exe')
                    if exe:
                        # Walk up from bin/sing_box/sing-box.exe → root
                        p = Path(exe)
                        for _ in range(4):
                            p = p.parent
                            if (p / 'guiConfigs').exists():
                                logger.debug('v2rayN root from process: %s', p)
                                return str(p)
            except (Exception):
                continue
    except ImportError:
        pass

    # 3. Windows Registry
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for subkey in (
                r'SOFTWARE\v2rayN',
                r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\v2rayN',
            ):
                try:
                    with winreg.OpenKey(hive, subkey) as key:
                        install_path, _ = winreg.QueryValueEx(key, 'InstallPath')
                        if Path(install_path).exists():
                            logger.debug('v2rayN root from registry: %s', install_path)
                            return install_path
                except OSError:
                    continue
    except ImportError:
        pass

    # 4. Common paths
    common = [
        r'd:\newlife\v2rayN\v2rayn',
        r'd:\useful\加速器\v2rayN-Core\v2rayN-windows-64',
        r'd:\useful\加速器\v2rayn',
        r'd:\useful\加速器\v2rayN',
        os.path.expandvars(r'%LOCALAPPDATA%\v2rayN'),
        os.path.expandvars(r'%APPDATA%\v2rayN'),
        r'C:\Program Files\v2rayN',
        r'C:\v2rayN',
    ]
    for path in common:
        p = Path(path)
        if p.exists() and (p / 'guiConfigs').exists():
            logger.debug('v2rayN root from common paths: %s', p)
            return str(p)

    # 5. Fallback
    fallback = r'd:\useful\加速器\v2rayn'
    logger.warning('Could not auto-discover v2rayN. Using fallback: %s', fallback)
    return fallback


BASE_DIR = _discover_v2rayn_root()

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
    """Read the actual SOCKS inbound port from v2rayN's config.json.

    Falls back to guiNConfig.json Inbound.LocalPort when config.json
    doesn't exist (v2rayN hasn't been connected yet).
    """
    try:
        with open(CONFIG_JSON, 'r', encoding='utf-8') as f:
            config = json.load(f)
        for ib in config.get('inbounds', []):
            if ib.get('protocol') in ('socks', 'mixed') or ib.get('type') in ('socks', 'mixed'):
                port = ib.get('port') or ib.get('listen_port', 0)
                if port:
                    return int(port)
        for ib in config.get('inbounds', []):
            port = ib.get('listen_port') or ib.get('port', 0)
            if port and port not in (10808,):
                return int(port)
    except Exception:
        pass

    # Fallback: read from v2rayN's GUI config (always present)
    gui = _read_gui_config()
    inbound = gui.get('Inbound', {})
    if isinstance(inbound, list):
        # v2rayN V7+: Inbound 是数组，取第一个 socks/mixed 入站
        for item in inbound:
            if item.get('Protocol', '').lower() in ('socks', 'mixed') or not item.get('Protocol'):
                inbound = item
                break
        else:
            inbound = inbound[0] if inbound else {}
    local_port = inbound.get('LocalPort', 0)
    if local_port:
        logger.debug('SOCKS port from guiNConfig.json: %d', local_port)
        return int(local_port)

    return SOCKS5_PORT


def get_socks_proxy() -> str:
    """Get the SOCKS5 proxy URL with the actual port from config."""
    port = get_socks_port_from_config()
    return f'socks5://{SOCKS5_HOST}:{port}'


# === 连通性检测 ===
CHECK_URL = 'https://www.google.com/generate_204'
TIMEOUT = 20          # 秒

# === 浏览器目标 ===
BROWSER_TARGETS = [
    'https://chatgpt.com',
    'https://gemini.google.com',
]

# === 节点切换 ===
CONFIG_TYPE_VLESS_GRPC = 11   # ConfigType=11: VLESS+gRPC
CONFIG_TYPE_VLESS_VISION = 5  # ConfigType=5: VLESS+Vision+httpupgrade
CONFIG_TYPE_VMESS = 1         # ConfigType=1: VMess
