"""Adapters layer - isolates v2rayN format knowledge from orchestration logic."""

from adapters.xray_config import (
    read_config,
    write_config,
    backup_config,
    restore_config,
    find_proxy_outbound,
    patch_proxy_outbound,
    get_config_format,
    apply_node_to_config,
)

from adapters.outbound_builder import (
    build_xray_outbound,
    detect_protocol_from_outbound,
)
