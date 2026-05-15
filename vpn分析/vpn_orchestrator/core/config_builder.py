"""
sing-box config.json manager (Patch Strategy).

Delegates to adapters/ for format-specific logic.
Public API kept stable for backward compatibility with orchestrator and services.
"""

import logging

import sys, os
_orch_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _orch_root not in sys.path:
    sys.path.insert(0, _orch_root)

from models.profile import ProfileItem

logger = logging.getLogger(__name__)


# ============================================================
#  Public API (stable)
# ============================================================

def read_current_config() -> dict:
    """Read the current config.json."""
    from adapters.xray_config import read_config
    return read_config()


def backup_config() -> None:
    """Create a backup of config.json."""
    from adapters.xray_config import backup_config
    backup_config()


def restore_config() -> bool:
    """Restore config.json from backup."""
    from adapters.xray_config import restore_config
    return restore_config()


def build_outbound_for_profile(profile: ProfileItem) -> dict:
    """Build an outbound dict for a profile (auto-detects format from config)."""
    from adapters.xray_config import get_config_format, read_config

    try:
        config = read_config()
        fmt = get_config_format(config)
    except Exception:
        fmt = 'xray'  # default

    if fmt == 'singbox':
        from adapters.outbound_builder import build_singbox_outbound
        return build_singbox_outbound(profile)
    else:
        from adapters.outbound_builder import build_xray_outbound
        return build_xray_outbound(profile)


def apply_profile_to_config(profile: ProfileItem) -> str:
    """
    Patch config.json: replace proxy outbound with the given profile's data.

    This is the main entry point. Uses Patch Strategy:
      - Reads v2rayN's working config.json
      - Replaces ONLY the proxy outbound
      - Preserves inbounds, routing, DNS, and all other outbounds
      - Writes back

    Returns:
        Path to the written config.json
    """
    from adapters.xray_config import apply_node_to_config
    return apply_node_to_config(profile)
