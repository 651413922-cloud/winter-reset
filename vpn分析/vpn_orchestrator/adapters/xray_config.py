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
import time
from pathlib import Path
from typing import Optional, Tuple

from config import CONFIG_JSON
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
    """Create a timestamped backup of the current config.json. Keeps last 5."""
    src = Path(CONFIG_JSON)
    if src.exists():
        ts = time.strftime('%Y%m%d-%H%M%S')
        bak = src.parent / (src.name + f'.{ts}.bak')
        shutil.copy2(src, bak)
        _prune_backups(keep=5)
        logger.info("Backup saved to %s", bak.name)


def _prune_backups(keep: int = 5) -> None:
    """Remove old timestamped backups, keeping the most recent `keep`."""
    cfg_dir = Path(CONFIG_JSON).parent
    cfg_name = Path(CONFIG_JSON).name
    backups = sorted(
        cfg_dir.glob(cfg_name + '.*.bak'),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    for old in backups[keep:]:
        old.unlink(missing_ok=True)


def _latest_backup() -> Optional[Path]:
    """Return the most recent timestamped backup, or None."""
    cfg_dir = Path(CONFIG_JSON).parent
    cfg_name = Path(CONFIG_JSON).name
    backups = sorted(
        cfg_dir.glob(cfg_name + '.*.bak'),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    return backups[0] if backups else None


def restore_config() -> bool:
    """Restore config.json from the most recent backup."""
    bak = _latest_backup()
    if bak:
        shutil.copy2(bak, CONFIG_JSON)
        logger.info("Restored from backup: %s → %s", bak.name, CONFIG_JSON)
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


def patch_proxy_outbound(config: dict, new_outbound: dict,
                         standalone: bool = False) -> dict:
    """
    Replace the proxy outbound in config with new_outbound.

    Preserves extra fields from the original:
      - Top-level: mux and any unknown keys
      - streamSettings.sockopt: TUN dialerProxy (only if standalone=False)

    When standalone=True (no v2rayN GUI), dialerProxy is removed because
    the TUN infrastructure is not available.

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

    # ---- Handle streamSettings.sockopt (TUN dialerProxy) ----
    orig_ss = original.get('streamSettings', {})
    orig_sockopt = orig_ss.get('sockopt')
    has_tun_protect = any(
        ob.get('tag') == 'tun-protect-socks' for ob in config.get('outbounds', [])
    )

    if 'streamSettings' in merged:
        if standalone:
            merged['streamSettings'].pop('sockopt', None)
            logger.debug("Removed dialerProxy (standalone mode)")
        elif orig_sockopt:
            merged['streamSettings']['sockopt'] = orig_sockopt
            logger.debug("Preserved dialerProxy for TUN mode")
        elif has_tun_protect:
            # Config has tun-protect-socks outbound but proxy lost its
            # sockopt from an earlier standalone patch — restore it.
            merged['streamSettings']['sockopt'] = {
                'dialerProxy': 'tun-protect-socks'
            }
            logger.debug("Restored dialerProxy → tun-protect-socks")

    config['outbounds'][idx] = merged
    return config


# ============================================================
#  High-level: Apply a node to config
# ============================================================

def apply_node_to_config(profile: ProfileItem, standalone: bool = False) -> str:
    """
    Patch config.json: replace proxy outbound with the given node.

    This is the main entry point — call this instead of the old
    config_builder.apply_profile_to_config().

    Args:
        profile: The node to switch to
        standalone: If True, remove TUN-specific settings (dialerProxy)
                    that require v2rayN GUI's TUN infrastructure

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
        from adapters.outbound_builder import build_singbox_outbound
        new_ob = build_singbox_outbound(profile)

    patch_proxy_outbound(config, new_ob, standalone=standalone)
    write_config(config)

    logger.info("Patched proxy outbound → %s (%s:%s)",
                profile.remarks, profile.address, profile.port)
    logger.debug("Written to %s", CONFIG_JSON)
    return CONFIG_JSON


# ============================================================
#  Utility: extract node identifier from an outbound
# ============================================================

def extract_node_identifier(outbound: dict) -> str:
    """Extract a human-readable identifier (addr:port) from an outbound dict."""
    proto = outbound.get('protocol', outbound.get('type', ''))

    if proto in ('vless', 'vmess', 'trojan'):
        vnext = outbound.get('settings', {}).get('vnext', [])
        if vnext:
            return f"{vnext[0].get('address', '?')}:{vnext[0].get('port', '?')}"

    elif proto == 'shadowsocks':
        servers = outbound.get('settings', {}).get('servers', [])
        if servers:
            return f"{servers[0].get('address', '?')}:{servers[0].get('port', '?')}"

    # Sing-box native format or fallback
    server = outbound.get('server', '')
    port = outbound.get('server_port', '')
    if server:
        return f'{server}:{port}' if port else server

    return f'{proto}://?'
