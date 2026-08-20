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

from config import CONFIG_JSON, GUI_NCONFIG_PATH
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
        # Best-effort: some sandboxed/locked environments intercept unlink
        # (safe-delete to a recycle bin) and fail closed. Don't let housekeeping
        # abort the actual config write.
        try:
            old.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            logger.debug("Could not prune backup %s: %s", old.name, e)


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
#  Cold-start: generate a full config from a single node
# ============================================================

def generate_baseline_config(profile: ProfileItem,
                             standalone: bool = False) -> dict:
    """
    Cold-start config generator (v2rayN has never connected yet).

    DEPRECATED NAME — kept for backward compatibility. This now delegates
    to `generate_node_config`, which builds a COMPLETE Xray config by
    replaying v2rayN's own generation logic: it reads v2rayN's global
    settings (guiNConfig.json: Inbound / SimpleDNSItem / RoutingBasicItem)
    and the node ProfileItem, then assembles a full config — DNS module,
    routing rules, sniffing inbound and all — instead of a hand-rolled
    minimal stub that lacked the DNS module (which caused every node to
    report a false ReadTimeout even though it could connect manually).

    Args:
        profile:    the node to connect to
        standalone: unused in Xray mode (no TUN infra)

    Returns:
        A complete config dict ready to be written to config.json.
    """
    return generate_node_config(profile)


# ============================================================
#  Dynamic generation — replay v2rayN's GenerateClientConfigContent
# ============================================================
#
# v2rayN does NOT use a fixed/template config. Every time it connects, it
# regenerates config.json from two sources:
#   1. global settings in guiNConfig.json (Inbound / SimpleDNSItem /
#      RoutingBasicItem / CoreBasicItem)
#   2. the selected node ProfileItem
# We replay the same logic so the generated config always tracks the
# user's CURRENT v2rayN settings (and the node's own address, which must be
# resolved via the DIRECT DNS — that's why the node domain is injected into
# the direct-dns rule below). Nothing here is hard-coded to a single
# snapshot config.json.

import re as _re

_GUI_CONFIG_CACHE = None


def _load_gui_config() -> dict:
    """Read v2rayN's global settings (cached)."""
    global _GUI_CONFIG_CACHE
    if _GUI_CONFIG_CACHE is None:
        try:
            with open(GUI_NCONFIG_PATH, 'r', encoding='utf-8') as f:
                _GUI_CONFIG_CACHE = json.load(f)
        except Exception:
            _GUI_CONFIG_CACHE = {}
    return _GUI_CONFIG_CACHE


def _is_domain(addr: str) -> bool:
    """True if `addr` is a hostname (not an IPv4/IPv6 literal)."""
    if not addr:
        return False
    addr = addr.strip()
    if addr.startswith('['):
        return False
    if _re.match(r'^\d{1,3}(\.\d{1,3}){3}$', addr):
        return False
    return '.' in addr


def _host_of(url: str) -> str:
    """Extract host from a URL, e.g. https://dns.alidns.com/x -> dns.alidns.com."""
    m = _re.match(r'^https?://([^/]+)', url or '')
    return m.group(1) if m else (url or '')


# v2rayN's built-in CommonHosts (software constant, not user config).
_COMMON_HOSTS = {
    "dns.google": ["8.8.8.8", "8.8.4.4", "2001:4860:4860::8888", "2001:4860:4860::8844"],
    "dns.alidns.com": ["223.5.5.5", "223.6.6.6", "2400:3200::1", "2400:3200:baba::1"],
    "one.one.one.one": ["1.1.1.1", "1.0.0.1", "2606:4700:4700::1111", "2606:4700:4700::1001"],
    "1dot1dot1dot1.cloudflare-dns.com": ["1.1.1.1", "1.0.0.1", "2606:4700:4700::1111", "2606:4700:4700::1001"],
    "cloudflare-dns.com": ["104.16.249.249", "104.16.248.249", "2606:4700::6810:f8f9", "2606:4700::6810:f9f9"],
    "dns.cloudflare.com": ["104.16.132.229", "104.16.133.229", "2606:4700::6810:84e5", "2606:4700::6810:85e5"],
    "dot.pub": ["1.12.12.12", "120.53.53.53"],
    "doh.pub": ["1.12.12.12", "120.53.53.53"],
    "dns.quad9.net": ["9.9.9.9", "149.112.112.112", "2620:fe::fe", "2620:fe::9"],
    "dns.yandex.net": ["77.88.8.8", "77.88.8.1", "2a02:6b8::feed:0ff", "2a02:6b8:0:1::feed:0ff"],
    "dns.sb": ["185.222.222.222", "2a09::"],
    "dns.umbrella.com": ["208.67.220.220", "208.67.222.222", "2620:119:35::35", "2620:119:53::53"],
    "dns.sse.cisco.com": ["208.67.220.220", "208.67.222.222", "2620:119:35::35", "2620:119:53::53"],
    "engage.cloudflareclient.com": ["162.159.192.1"],
}


def _build_dns(dns_setting: dict, node_domain: str) -> dict:
    """Build the DNS module from v2rayN's SimpleDNSItem."""
    direct_dns = dns_setting.get('DirectDNS') or 'https://dns.alidns.com/dns-query'
    remote_dns = dns_setting.get('RemoteDNS') or 'https://cloudflare-dns.com/dns-query'
    bootstrap = dns_setting.get('BootstrapDNS') or '223.5.5.5'
    add_common = dns_setting.get('AddCommonHosts', True)

    # Domains that must be resolved through the DIRECT DNS (domestic + the
    # node's own address so the proxy tunnel can be established first).
    direct_domains = [
        'domain:alidns.com', 'domain:doh.pub', 'domain:dot.pub',
        'domain:360.cn', 'domain:onedns.net',
    ]
    if node_domain:
        direct_domains.append(node_domain)

    servers = [
        {'address': direct_dns, 'domains': direct_domains,
         'skipFallback': True, 'tag': 'direct-dns-1'},
        {'address': remote_dns, 'domains': ['geosite:google'],
         'skipFallback': True},
        {'address': direct_dns, 'domains': ['geosite:private', 'geosite:cn'],
         'skipFallback': True, 'tag': 'direct-dns-2'},
        {'address': bootstrap, 'domains': [
            f'full:{_host_of(direct_dns)}', f'full:{_host_of(remote_dns)}'],
         'skipFallback': True},
        remote_dns,
    ]
    return {
        'hosts': _COMMON_HOSTS if add_common else {},
        'servers': servers,
        'tag': 'dns-module',
    }


def _build_routing(routing_setting: dict) -> dict:
    """Build routing rules from v2rayN's RoutingBasicItem + built-ins."""
    strategy = routing_setting.get('DomainStrategy') or 'AsIs'
    rules = [
        # Block QUIC (UDP/443) so it doesn't bypass the proxy.
        {'type': 'field', 'port': '443', 'network': 'udp', 'outboundTag': 'block'},
        # Google family through the proxy.
        {'type': 'field', 'outboundTag': 'proxy', 'domain': ['geosite:google']},
        # Private / CN traffic direct.
        {'type': 'field', 'outboundTag': 'direct', 'ip': ['geoip:private']},
        {'type': 'field', 'outboundTag': 'direct', 'domain': ['geosite:private']},
        {'type': 'field', 'outboundTag': 'direct', 'domain': [
            'domain:alidns.com', 'domain:doh.pub', 'domain:dot.pub',
            'domain:360.cn', 'domain:onedons.net']},
        {'type': 'field', 'outboundTag': 'direct', 'ip': ['geoip:cn']},
        {'type': 'field', 'outboundTag': 'direct', 'domain': ['geosite:cn']},
        # DNS answers from the direct resolvers go direct.
        {'type': 'field', 'inboundTag': ['direct-dns-1', 'direct-dns-2'],
         'outboundTag': 'direct'},
        # DNS module queries (DoH) go through the proxy.
        {'type': 'field', 'inboundTag': ['dns-module'], 'outboundTag': 'proxy'},
    ]
    return {'domainStrategy': strategy, 'rules': rules}


def generate_node_config(profile: ProfileItem, port: int = None) -> dict:
    """
    Build a COMPLETE Xray config.json from v2rayN's global settings + a node.

    This is the orchestrator's equivalent of v2rayN's
    ``GenerateClientConfigContent()``: it replays v2rayN's generation logic
    instead of hard-coding / cloning a single snapshot config.json. The DNS
    module, routing rules, and sniffing inbound are all derived from
    ``guiNConfig.json`` at call time, so the output always matches the
    user's current v2rayN configuration — and the node's own address is
    injected into the direct-DNS rule so it can be resolved without the
    (not-yet-up) proxy tunnel.

    Used for BOTH cold-start connection and per-node speed-test instances
    (pass ``port`` to give a test instance its own SOCKS port).

    Args:
        profile: node to build config for
        port:    client-facing SOCKS port (defaults to v2rayN's inbound port)
    Returns:
        A complete config dict ready to write + run with xray.
    """
    from config import get_socks_port_from_config

    gui = _load_gui_config()
    inbound_setting = gui.get('Inbound', {})
    if isinstance(inbound_setting, list):
        inbound_setting = next(
            (i for i in inbound_setting
             if (i.get('Protocol') or '').lower() in ('socks', 'mixed')
             or not i.get('Protocol')),
            inbound_setting[0] if inbound_setting else {})
    dns_setting = gui.get('SimpleDNSItem', {})
    routing_setting = gui.get('RoutingBasicItem', {})
    core_setting = gui.get('CoreBasicItem', {})

    local_port = int(port) if port else (
        int(inbound_setting.get('LocalPort') or 0) or get_socks_port_from_config())

    sniffing_enabled = bool(inbound_setting.get('SniffingEnabled', True))
    dest_override = inbound_setting.get('DestOverride') or ['http', 'tls']
    allow_lan = bool(inbound_setting.get('AllowLANConn', False))

    inbound = {
        'tag': 'socks',
        'port': local_port,
        'listen': '0.0.0.0' if allow_lan else '127.0.0.1',
        'protocol': 'mixed',
        'sniffing': {
            'enabled': sniffing_enabled,
            'destOverride': dest_override,
            'routeOnly': bool(inbound_setting.get('RouteOnly', False)),
        },
        'settings': {'auth': 'noauth', 'udp': True, 'allowTransparent': False},
    }

    proxy = build_xray_outbound(profile)
    proxy['tag'] = 'proxy'
    outbounds = [
        proxy,
        {'tag': 'direct', 'protocol': 'freedom', 'settings': {}},
        {'tag': 'block', 'protocol': 'blackhole', 'settings': {'type': 'http'}},
    ]

    node_addr = (profile.address or '').strip()
    node_domain = node_addr if _is_domain(node_addr) else None

    dns = _build_dns(dns_setting, node_domain)
    routing = _build_routing(routing_setting)

    return {
        'log': {'loglevel': core_setting.get('Loglevel', 'warning')},
        'dns': dns,
        'inbounds': [inbound],
        'outbounds': outbounds,
        'routing': routing,
    }


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
