"""
Outbound builder — converts ProfileItem → Xray-format outbound dict.

Generates outbounds in the SAME format that v2rayN uses, so the patched
config.json remains compatible with sing-box's Xray-compatibility layer.

Supports:
  - ConfigType=5:  VLESS + Vision + httpupgrade + TLS
  - ConfigType=11: VLESS + gRPC + TLS
  - ConfigType=1:  VMess (various transports: tcp/ws/httpupgrade/grpc)
  - ConfigType=4:  Shadowsocks
  - Future: sing-box native format (for when v2rayN switches)
"""

import logging
from typing import Optional

from models.profile import ProfileItem

logger = logging.getLogger(__name__)


# ============================================================
#  Transport builders (Xray format: streamSettings)
# ============================================================

def _build_stream_settings(profile: ProfileItem) -> dict:
    """Build the streamSettings block for Xray-format config."""
    network = (profile.network or 'tcp').lower()
    ss = {'network': network}

    # --- Transport-specific settings ---
    if network == 'ws':
        ss['wsSettings'] = {
            'path': profile.effective_path or '/',
            'headers': {'Host': profile.effective_host or ''},
        }

    elif network == 'httpupgrade':
        ss['httpupgradeSettings'] = {
            'path': profile.effective_path or '/',
            'host': profile.effective_host or '',
        }

    elif network == 'grpc':
        service = (profile.effective_path or '').lstrip('/')
        ss['grpcSettings'] = {'serviceName': service}

    elif network == 'quic':
        ss['quicSettings'] = {
            'security': profile.effective_host or 'none',
            'key': profile.effective_path or '',
            'header': {'type': profile.header_type or 'none'},
        }

    elif network == 'kcp':
        ss['kcpSettings'] = {
            'mtu': 1350,
            'tti': 50,
            'uplinkCapacity': 12,
            'downlinkCapacity': 100,
            'congestion': False,
            'readBufferSize': 2,
            'writeBufferSize': 2,
            'header': {'type': profile.header_type or 'none'},
        }

    # --- Security (TLS / Reality) ---
    security = (profile.stream_security or '').lower()

    if security == 'tls':
        ss['security'] = 'tls'
        ss['tlsSettings'] = {
            'serverName': profile.sni or profile.address,
            'fingerprint': profile.fingerprint or 'chrome',
            'allowInsecure': profile.allow_insecure == 'true' or profile.allow_insecure == 'True',
        }

    elif security == 'reality':
        ss['security'] = 'reality'
        ss['realitySettings'] = {
            'serverName': profile.sni or profile.address,
            'fingerprint': profile.fingerprint or 'chrome',
            'publicKey': profile.public_key or '',
            'shortId': profile.short_id or '',
            'spiderX': profile.spider_x or '/',
        }

    return ss


# ============================================================
#  Protocol-specific outbound builders
# ============================================================

def _build_vless_outbound(profile: ProfileItem) -> dict:
    """ConfigType=5/11: VLESS in Xray format."""
    flow = profile.effective_flow or ''
    encryption = profile.vless_encryption or 'none'

    ob = {
        'tag': 'proxy',
        'protocol': 'vless',
        'settings': {
            'vnext': [{
                'address': profile.address,
                'port': profile.port,
                'users': [{
                    'id': profile.password,
                    'flow': flow,
                    'encryption': encryption,
                }],
            }],
        },
        'streamSettings': _build_stream_settings(profile),
        'mux': {'enabled': False, 'concurrency': -1},
    }

    # Remove flow if empty (not all VLESS nodes use Vision flow)
    if not flow:
        del ob['settings']['vnext'][0]['users'][0]['flow']

    return ob


def _build_vmess_outbound(profile: ProfileItem) -> dict:
    """ConfigType=1: VMess in Xray format."""
    ob = {
        'tag': 'proxy',
        'protocol': 'vmess',
        'settings': {
            'vnext': [{
                'address': profile.address,
                'port': profile.port,
                'users': [{
                    'id': profile.password,
                    'security': profile.security or 'auto',
                    'alterId': profile.alter_id or 0,
                }],
            }],
        },
        'streamSettings': _build_stream_settings(profile),
        'mux': {'enabled': False, 'concurrency': -1},
    }
    return ob


def _build_shadowsocks_outbound(profile: ProfileItem) -> dict:
    """ConfigType=4: Shadowsocks in Xray format."""
    ob = {
        'tag': 'proxy',
        'protocol': 'shadowsocks',
        'settings': {
            'servers': [{
                'address': profile.address,
                'port': profile.port,
                'method': profile.security or 'aes-256-gcm',
                'password': profile.password,
                'level': 1,
            }],
        },
        'streamSettings': {
            'network': 'tcp',
        },
        'mux': {'enabled': False, 'concurrency': -1},
    }
    return ob


# ============================================================
#  Main dispatcher
# ============================================================

# ConfigType → builder mapping
CONFIG_TYPE_BUILDERS = {
    1:  _build_vmess_outbound,       # VMess
    3:  _build_shadowsocks_outbound, # Shadowsocks
    4:  _build_shadowsocks_outbound, # Shadowsocks (alt)
    5:  _build_vless_outbound,       # VLESS + Vision + httpupgrade
    11: _build_vless_outbound,       # VLESS + gRPC
}


def build_xray_outbound(profile: ProfileItem) -> dict:
    """
    Build an Xray-format proxy outbound from ProfileItem.

    Dispatches to the correct builder based on profile.config_type.
    Falls back to VLESS builder for unknown types.
    """
    builder = CONFIG_TYPE_BUILDERS.get(profile.config_type)

    if builder:
        logger.debug("Building Xray outbound (config_type=%d, protocol=%s)",
                     profile.config_type, profile.network)
        return builder(profile)

    # Unknown config type — try VLESS as the most common fallback
    logger.warning("Unknown config_type=%d for %s, falling back to VLESS",
                   profile.config_type, profile.remarks)
    return _build_vless_outbound(profile)


# ============================================================
#  Sing-box native format (for future use)
# ============================================================

def build_singbox_outbound(profile: ProfileItem) -> dict:
    """
    Build a sing-box native format outbound.

    Used when config.json is already in sing-box native format.
    Only handles the subset of fields that sing-box ≥1.13 accepts.
    """
    network = (profile.network or 'tcp').lower()
    security = (profile.stream_security or '').lower()

    ob = {
        'type': 'vless',
        'tag': 'proxy',
        'server': profile.address,
        'server_port': profile.port,
        'uuid': profile.password,
    }

    flow = profile.effective_flow or ''
    if flow:
        ob['flow'] = flow

    # TLS
    if security == 'tls':
        ob['tls'] = {
            'enabled': True,
            'server_name': profile.sni or profile.address,
            'utls': {
                'enabled': True,
                'fingerprint': profile.fingerprint or 'chrome',
            },
        }
    elif security == 'reality':
        ob['tls'] = {
            'enabled': True,
            'server_name': profile.sni or profile.address,
            'reality': {
                'enabled': True,
                'public_key': profile.public_key or '',
                'short_id': profile.short_id or '',
            },
            'utls': {
                'enabled': True,
                'fingerprint': profile.fingerprint or 'chrome',
            },
        }

    # Transport
    if network == 'httpupgrade':
        ob['transport'] = {
            'type': 'httpupgrade',
            'path': profile.effective_path or '/',
            'host': profile.effective_host or '',
        }
    elif network == 'grpc':
        ob['transport'] = {
            'type': 'grpc',
            'service_name': (profile.effective_path or '').lstrip('/'),
        }
    elif network == 'ws':
        ob['transport'] = {
            'type': 'ws',
            'path': profile.effective_path or '/',
            'headers': {'Host': profile.effective_host or ''},
        }
    elif network != 'tcp':
        ob['transport'] = {'type': network}

    return ob


# ============================================================
#  Utility
# ============================================================

def detect_protocol_from_outbound(outbound: dict) -> Optional[str]:
    """Return the protocol of an existing outbound (Xray or sing-box format)."""
    return outbound.get('protocol') or outbound.get('type')
