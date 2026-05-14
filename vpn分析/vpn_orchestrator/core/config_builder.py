"""
sing-box 配置文件生成器 (native format for sing-box ≥1.13)。
从 ProfileItem 数据构建完整的 binConfigs/config.json。
v2rayN 仅作为节点数据源（SQLite），完整配置由我们生成。
"""

import json
import logging
import shutil
import sys, os
from pathlib import Path

_orch_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _orch_root not in sys.path:
    sys.path.insert(0, _orch_root)

from config import CONFIG_JSON, BACKUP_CONFIG_JSON
from models.profile import ProfileItem

logger = logging.getLogger(__name__)


# ========== 完整配置模板 (sing-box ≥1.13 native) ==========

def _build_base_config(proxy_outbound: dict, socks_port: int = 10808) -> dict:
    """用我们自己的干净模板构建完整 sing-box config.json。"""
    return {
        "log": {"level": "warning"},
        "dns": {
            "servers": [
                {
                    "tag": "dns-remote",
                    "address": "tls://1.1.1.1",
                    "detour": "proxy",
                },
                {
                    "tag": "dns-direct",
                    "address": "223.5.5.5",
                    "detour": "direct",
                },
            ],
            "rules": [
                {"domain_suffix": "cn", "server": "dns-direct"},
            ],
        },
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": socks_port,
                "sniff": True,
                "sniff_override_destination": False,
            }
        ],
        "outbounds": [
            proxy_outbound,
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
        ],
        "route": {
            "rules": [
                {"ip_is_private": True, "outbound": "direct"},
            ],
            "auto_detect_interface": True,
        },
    }


# ========== Outbound 构建器 (sing-box native format) ==========

def _build_vless_outbound_vision(profile: ProfileItem) -> dict:
    """ConfigType=5: VLESS + Vision + httpupgrade + TLS"""
    enc = profile.vless_encryption or "none"
    ob = {
        "type": "vless",
        "tag": "proxy",
        "server": profile.address,
        "server_port": profile.port,
        "uuid": profile.password,
        "flow": profile.effective_flow or "xtls-rprx-vision",
        "tls": {
            "enabled": True,
            "server_name": profile.sni or profile.address,
            "utls": {
                "enabled": True,
                "fingerprint": profile.fingerprint or "chrome",
            },
        },
        "transport": {
            "type": "httpupgrade",
            "path": profile.effective_path or "/",
            "host": profile.effective_host or "",
        },
    }
    if enc and enc != "none":
        ob["encryption"] = enc
    return ob


def _build_vless_outbound_grpc(profile: ProfileItem) -> dict:
    """ConfigType=11: VLESS + gRPC + TLS"""
    return {
        "type": "vless",
        "tag": "proxy",
        "server": profile.address,
        "server_port": profile.port,
        "uuid": profile.password,
        "tls": {
            "enabled": True,
            "server_name": profile.sni or profile.address,
            "utls": {
                "enabled": True,
                "fingerprint": profile.fingerprint or "chrome",
            },
        },
        "transport": {
            "type": "grpc",
            "service_name": (profile.effective_path or "").lstrip('/'),
        },
    }


def _build_vmess_outbound(profile: ProfileItem) -> dict:
    """ConfigType=1: VMess + httpupgrade"""
    ob = {
        "type": "vmess",
        "tag": "proxy",
        "server": profile.address,
        "server_port": profile.port,
        "uuid": profile.password,
        "security": profile.security or "auto",
        "alter_id": profile.alter_id or 0,
        "transport": {
            "type": profile.network or "tcp",
        },
    }
    if profile.network == "httpupgrade":
        ob["transport"]["path"] = profile.effective_path or "/"
        ob["transport"]["host"] = profile.effective_host or ""
    if profile.stream_security == "tls":
        ob["tls"] = {
            "enabled": True,
            "server_name": profile.sni or profile.address,
        }
    return ob


def build_outbound_for_profile(profile: ProfileItem) -> dict:
    """根据 ConfigType 选择对应的 outbound 构建器"""
    if profile.config_type == 11:
        return _build_vless_outbound_grpc(profile)
    elif profile.config_type == 5:
        return _build_vless_outbound_vision(profile)
    elif profile.config_type == 1:
        return _build_vmess_outbound(profile)
    else:
        return _build_vless_outbound_vision(profile)


# ========== 文件操作 ==========

def read_current_config() -> dict:
    """读取当前运行的 config.json"""
    with open(CONFIG_JSON, 'r', encoding='utf-8') as f:
        return json.load(f)


def backup_config():
    src = Path(CONFIG_JSON)
    if src.exists():
        shutil.copy2(src, BACKUP_CONFIG_JSON)
        logger.info("备份保存至 %s", BACKUP_CONFIG_JSON)


def restore_config():
    bak = Path(BACKUP_CONFIG_JSON)
    if bak.exists():
        shutil.copy2(bak, CONFIG_JSON)
        logger.info("从备份还原 %s", CONFIG_JSON)
        return True
    logger.error("无备份文件可恢复")
    return False


def apply_profile_to_config(profile: ProfileItem) -> str:
    """用我们自己的模板 + 节点数据生成完整 config.json。"""
    backup_config()

    proxy_outbound = build_outbound_for_profile(profile)
    config = _build_base_config(proxy_outbound)

    with open(CONFIG_JSON, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    logger.info("已切换至节点: %s (%s:%s)", profile.remarks, profile.address, profile.port)
    logger.debug("写入 %s", CONFIG_JSON)
    return CONFIG_JSON
