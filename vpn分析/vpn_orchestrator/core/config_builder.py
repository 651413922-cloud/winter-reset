"""
sing-box 配置文件生成器。
从 ProfileItem 数据构建完整的 binConfigs/config.json。
格式兼容 sing-box 核心。
"""

import json
import logging
import shutil
import sys, os
from typing import Optional
from pathlib import Path

_orch_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _orch_root not in sys.path:
    sys.path.insert(0, _orch_root)

from config import CONFIG_JSON, BACKUP_CONFIG_JSON
from models.profile import ProfileItem

logger = logging.getLogger(__name__)


# ========== 完整配置模板 ==========
# 不再依赖 v2rayN 生成的 config.json。
# v2rayN 仅作为节点数据源（SQLite），完整 sing-box 配置由我们生成。

def _build_base_config(proxy_outbound: dict, socks_port: int = 10808) -> dict:
    """用我们自己的干净模板构建完整 sing-box config.json。"""
    return {
        "log": {
            "level": "warning",
        },
        "dns": {
            "servers": [
                {
                    "tag": "dns-remote",
                    "address": "https://1.1.1.1/dns-query",
                    "detour": "proxy",
                },
                {
                    "tag": "dns-direct",
                    "address": "223.5.5.5",
                    "detour": "direct",
                },
            ],
            "rules": [
                {
                    "domain_suffix": "cn",
                    "server": "dns-direct",
                },
                {
                    "geosite": "cn",
                    "server": "dns-direct",
                },
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
            {
                "type": "direct",
                "tag": "direct",
            },
            {
                "type": "dns",
                "tag": "dns-out",
            },
            {
                "type": "block",
                "tag": "block",
            },
        ],
        "routing": {
            "rules": [
                {
                    "protocol": "dns",
                    "outbound": "dns-out",
                },
                {
                    "ip_is_private": True,
                    "outbound": "direct",
                },
            ],
            "auto_detect_interface": True,
        },
    }

def _build_vless_outbound_grpc(profile: ProfileItem) -> dict:
    """构建 ConfigType=11: VLESS + gRPC + TLS"""
    return {
        "tag": "proxy",
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": profile.address,
                "port": profile.port,
                "users": [{
                    "id": profile.password,
                    "email": "t@t.tt",
                    "security": "auto",
                    "encryption": "none",
                }]
            }]
        },
        "streamSettings": {
            "network": "grpc",
            "security": profile.stream_security or "tls",
            "tlsSettings": {
                "allowInsecure": profile.allow_insecure == "true",
                "fingerprint": profile.fingerprint or "chrome",
                "serverName": profile.sni or profile.address,
            },
            "grpcSettings": {
                "serviceName": profile.effective_path.lstrip('/'),
            }
        },
        "mux": {"enabled": False, "concurrency": -1}
    }


def _build_vless_outbound_vision(profile: ProfileItem) -> dict:
    """构建 ConfigType=5: VLESS + Vision + httpupgrade + TLS"""
    enc = profile.vless_encryption
    return {
        "tag": "proxy",
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": profile.address,
                "port": profile.port,
                "users": [{
                    "id": profile.password,
                    "email": "t@t.tt",
                    "security": "auto",
                    "encryption": enc if enc else "none",
                    "flow": profile.effective_flow or "xtls-rprx-vision",
                }]
            }]
        },
        "streamSettings": {
            "network": "httpupgrade",
            "security": profile.stream_security or "tls",
            "tlsSettings": {
                "allowInsecure": profile.allow_insecure == "true",
                "fingerprint": profile.fingerprint or "chrome",
                "serverName": profile.sni or profile.address,
            },
            "httpupgradeSettings": {
                "path": profile.effective_path or "/",
                "host": profile.effective_host or "",
            }
        },
        "mux": {"enabled": False, "concurrency": -1}
    }


def _build_vmess_outbound(profile: ProfileItem) -> dict:
    """构建 ConfigType=1: VMess + httpupgrade"""
    return {
        "tag": "proxy",
        "protocol": "vmess",
        "settings": {
            "vnext": [{
                "address": profile.address,
                "port": profile.port,
                "users": [{
                    "id": profile.password,
                    "security": profile.security or "auto",
                    "alterId": profile.alter_id or 0,
                }]
            }]
        },
        "streamSettings": {
            "network": profile.network or "tcp",
            "security": profile.stream_security or "",
            "tlsSettings": {
                "allowInsecure": profile.allow_insecure == "true",
                "serverName": profile.sni or profile.address,
            } if profile.stream_security == "tls" else {},
            "httpupgradeSettings": {
                "path": profile.effective_path or "/",
                "host": profile.effective_host or "",
            } if profile.network == "httpupgrade" else {},
        },
        "mux": {"enabled": False, "concurrency": -1}
    }


def build_outbound_for_profile(profile: ProfileItem) -> dict:
    """根据 ConfigType 选择对应的 outbound 构建器"""
    if profile.config_type == 11:
        return _build_vless_outbound_grpc(profile)
    elif profile.config_type == 5:
        return _build_vless_outbound_vision(profile)
    elif profile.config_type == 1:
        return _build_vmess_outbound(profile)
    else:
        # 默认走 VLESS Vision（最常见）
        return _build_vless_outbound_vision(profile)


def read_current_config() -> dict:
    """读取当前运行的 config.json"""
    with open(CONFIG_JSON, 'r', encoding='utf-8') as f:
        return json.load(f)


def backup_config():
    """备份当前配置文件"""
    src = Path(CONFIG_JSON)
    if src.exists():
        shutil.copy2(src, BACKUP_CONFIG_JSON)
        logger.info("备份保存至 %s", BACKUP_CONFIG_JSON)


def restore_config():
    """从备份恢复配置文件"""
    bak = Path(BACKUP_CONFIG_JSON)
    if bak.exists():
        shutil.copy2(bak, CONFIG_JSON)
        logger.info("从备份还原 %s", CONFIG_JSON)
        return True
    logger.error("无备份文件可恢复")
    return False


def apply_profile_to_config(profile: ProfileItem) -> str:
    """
    用我们自己的模板 + 节点数据生成完整 config.json。
    v2rayN 仅作为节点数据源，不再依赖它生成的旧配置文件。

    Returns:
        config.json 的路径
    """
    backup_config()

    proxy_outbound = build_outbound_for_profile(profile)
    config = _build_base_config(proxy_outbound)

    with open(CONFIG_JSON, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    logger.info("已切换至节点: %s (%s:%s)", profile.remarks, profile.address, profile.port)
    logger.debug("写入 %s", CONFIG_JSON)
    return CONFIG_JSON