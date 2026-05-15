"""
Xray-format config.json handler.

v2rayN generates config.json in Xray-core format (keys: "protocol", "settings",
"streamSettings", "routing"). sing-box reads this through its compatibility layer.

This module implements a **Patch Strategy**:
  - Read v2rayN's working config.json
  - Replace ONLY the proxy outbound's connection details
  - Preserve inbounds, routing, DNS, and other outbounds intact
  - Write back without altering the JSON structure

This avoids the "full generation" anti-pattern that discards v2rayN's proven
configuration and causes connection timeouts.
"""

import json
import logging
import shutil
from pathlib import Path
from typing import Optional, Tuple

import sys, os
_orch_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _orch_root not in sys.path:
    sys.path.insert(0, _orch_root)

from config import CONFIG_JSON, BACKUP_CONFIG_JSON
from models.profile import ProfileItem
from adapters.outbound_builder import build_xray_outbound

logger = logging.getLogger(__name__)


# ============================================================
#  Config Format Detection
# ============================================================

def get_config_format(config: dict) -> str:
    """
    Detect the config.json format.

    Returns:
        "xray"    — uses "protocol"/"settings"/"streamSettings" keys
        "singbox" — uses "type" key (sing-box native format)
        "unknown" — cannot determine
    """
    outbounds = config.get('outbounds', [])
    if not outbounds:
        return 'unknown'

    first = outbounds[0]
    if 'protocol' in first:
        return 'xray'
    if 'type' in first:
        return 'singbox'
    return 'unknown'


# ============================================================
#  File I/O
# ============================================================

def read_config() -> dict:
    """Read the current config.json."""
    with open(CONFIG_JSON, 'r', encoding='utf-8') as f:
        return json.load(f)


def write_config(config: dict) -> None:
    """Write config.json with consistent formatting."""
    with open(CONFIG_JSON, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def backup_config() -> None:
    """Create a backup of the current config.json."""
    src = Path(CONFIG_JSON)
    if src.exists():
        shutil.copy2(src, BACKUP_CONFIG_JSON)
        logger.info("Backup saved to %s", BACKUP_CONFIG_JSON)


def restore_config() -> bool:
    """Restore config.json from backup."""
    bak = Path(BACKUP_CONFIG_JSON)
    if bak.exists():
        shutil.copy2(bak, CONFIG_JSON)
        logger.info("Restored from backup: %s", CONFIG_JSON)
        return True
    logger.error("No backup file to restore")
    return False


# ============================================================
#  Proxy Outbound Location
# ============================================================

def find_proxy_outbound(config: dict) -> Tuple[Optional[dict], int]:
    """
    Find the primary proxy outbound in config.

    Strategy:
      1. Look for outbound with tag == "proxy"
      2. If not found, look for the first outbound that is NOT
         direct/block/dns/freedom (these are routing targets, not proxies)
      3. If still not found, return the first outbound

    Returns:
        (outbound_dict, index) or (None, -1) if no outbounds exist
    """
    outbounds = config.get('outbounds', [])
    if not outbounds:
        return None, -1

    routing_tags = {'direct', 'block', 'dns', 'dns-out', 'freedom', 'blackhole',
                    'tun-protect-socks', 'api'}

    # Pass 1: look for tag == "proxy"
    for i, ob in enumerate(outbounds):
        if ob.get('tag') == 'proxy':
            return ob, i

    # Pass 2: first non-routing outbound
    for i, ob in enumerate(outbounds):
        if ob.get('tag', '').lower() not in routing_tags:
            return ob, i

    # Pass 3: first outbound
    return outbounds[0], 0


# ============================================================
#  Outbound Patching (Xray format)
# ============================================================

def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge overlay into base. overlay values take precedence."""
    for key, value in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def patch_proxy_outbound(config: dict, new_outbound: dict) -> dict:
    """
    Replace the proxy outbound in config with new_outbound.

    Preserves extra fields from the original:
      - Top-level: mux, sockopt, and any unknown keys
      - streamSettings.sockopt: critical for TUN mode (dialerProxy)

    Returns the modified config (mutated in-place as well).
    """
    _, idx = find_proxy_outbound(config)
    if idx < 0:
        logger.error("No proxy outbound found in config")
        return config

    original = config['outbounds'][idx]

    # ---- Preserve top-level fields we don't manage ----
    managed_keys = {'protocol', 'type', 'tag', 'settings', 'streamSettings'}
    preserved = {k: v for k, v in original.items() if k not in managed_keys}

    merged = dict(new_outbound)
    merged.update(preserved)

    # ---- Preserve streamSettings.sockopt (TUN dialerProxy) ----
    orig_ss = original.get('streamSettings', {})
    orig_sockopt = orig_ss.get('sockopt')
    if orig_sockopt and 'streamSettings' in merged:
        merged['streamSettings']['sockopt'] = orig_sockopt

    config['outbounds'][idx] = merged
    return config


# ============================================================
#  High-level: Apply a node to config
# ============================================================

def apply_node_to_config(profile: ProfileItem) -> str:
    """
    Patch config.json: replace proxy outbound with the given node.

    This is the main entry point — call this instead of the old
    config_builder.apply_profile_to_config().

    1. Backup current config
    2. Read config
    3. Build Xray-format outbound for the profile
    4. Patch it into config
    5. Write config

    Returns:
        Path to the written config.json
    """
    backup_config()

    config = read_config()
    fmt = get_config_format(config)
    logger.info("Detected config format: %s", fmt)

    if fmt == 'xray':
        new_ob = build_xray_outbound(profile)
    else:
        # Future: sing-box native format support
        from adapters.outbound_builder import build_singbox_outbound
        new_ob = build_singbox_outbound(profile)

    patch_proxy_outbound(config, new_ob)
    write_config(config)

    logger.info("Patched proxy outbound → %s (%s:%s)",
                profile.remarks, profile.address, profile.port)
    logger.debug("Written to %s", CONFIG_JSON)
    return CONFIG_JSON
