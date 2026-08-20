"""
sing-box config.json manager (Patch Strategy).

Delegates to adapters/ for format-specific logic.
Public API kept stable for backward compatibility with orchestrator and services.
"""

import logging

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


def apply_profile_to_config(profile: ProfileItem, standalone: bool = False) -> str:
    """
    Generate config.json for `profile` and write it.

    This is the main entry point. It replays v2rayN's own generation logic
    (v2rayN regenerates config.json from scratch on every connect): read
    v2rayN's global settings (guiNConfig.json) + the node ProfileItem and
    assemble a COMPLETE config — DNS module, routing rules, sniffing
    inbound and all. Nothing is hard-coded to a single snapshot config.

    Unlike the old "patch" strategy, this also fixes the false-negative bug
    where a hand-rolled minimal config (no DNS module) made every node look
    dead: the node's own address is injected into the direct-DNS rule so it
    can be resolved without the (not-yet-up) proxy tunnel.

    Args:
        profile: The node to switch to
        standalone: unused in Xray mode (no TUN infra)

    Returns:
        Path to the written config.json
    """
    from config import CONFIG_JSON
    from adapters.xray_config import (
        generate_node_config, write_config, backup_config,
    )

    # Back up any existing config.json before overwriting (v2rayN also
    # regenerates each connect, but we keep a safety copy).
    try:
        backup_config()
    except Exception:
        pass

    cfg = generate_node_config(profile)
    write_config(cfg)
    logger.info('Generated config.json for %s (%s:%s)',
                profile.remarks, profile.address, profile.port)
    return CONFIG_JSON
