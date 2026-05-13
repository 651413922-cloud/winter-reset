"""
sing-box 配置文件生成器。
从 ProfileItem 数据构建完整的 binConfigs/config.json。
格式兼容 sing-box 核心。
"""

import json
import shutil
import sys, os
from typing import Optional
from pathlib import Path

_orch_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _orch_root not in sys.path:
    sys.path.insert(0, _orch_root)

from config import CONFIG_JSON, BACKUP_CONFIG_JSON
from models.profile import ProfileItem


# ========== 基座配置 ==========
# 保留 DNS、Inbounds、Routing 不变，只替换 outbounds 部分

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
        print(f"[备份] 保存至 {BACKUP_CONFIG_JSON}")


def restore_config():
    """从备份恢复配置文件"""
    bak = Path(BACKUP_CONFIG_JSON)
    if bak.exists():
        shutil.copy2(bak, CONFIG_JSON)
        print(f"[恢复] 从备份还原 {CONFIG_JSON}")
        return True
    print("[错误] 无备份文件可恢复")
    return False


def apply_profile_to_config(profile: ProfileItem) -> str:
    """
    将节点配置写入 config.json。
    保留所有 Inbound/DNS/Routing 不变，只替换 outbounds 中的 proxy 部分。
    返回最终 config.json 路径。
    """
    backup_config()

    # 读取当前配置
    config = read_current_config()

    # 构建新的 outbound
    new_proxy_outbound = build_outbound_for_profile(profile)

    # 替换 outbounds 中的 proxy
    outbounds = config.get('outbounds', [])
    replaced = False
    for i, ob in enumerate(outbounds):
        if ob.get('tag') == 'proxy':
            outbounds[i] = new_proxy_outbound
            replaced = True
            break

    if not replaced:
        outbounds.insert(0, new_proxy_outbound)

    config['outbounds'] = outbounds

    # 写回文件
    with open(CONFIG_JSON, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"[配置] 已切换至节点: {profile.remarks} ({profile.address}:{profile.port})")
    print(f"[配置] 写入 {CONFIG_JSON}")
    return CONFIG_JSON