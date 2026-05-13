# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A Python VPN orchestrator that bypasses the v2rayN GUI to directly control the **sing-box** proxy core through protocol-level manipulation. It replaces the GUI's three core functions: SQLite database management, config.json generation, and process lifecycle control.

## Commands

```bash
# Install dependencies (Python 3.12+)
pip install -r "vpn分析/vpn_orchestrator/requirements.txt"

# Run interactive menu
python "vpn分析/vpn_orchestrator/main.py"

# CLI commands
python "vpn分析/vpn_orchestrator/main.py" auto      # Full auto-connect: start VPN → check proxy → open browser
python "vpn分析/vpn_orchestrator/main.py" list      # List all nodes
python "vpn分析/vpn_orchestrator/main.py" switch <name/index>  # Switch to a specific node
python "vpn分析/vpn_orchestrator/main.py" best      # Switch to best node by latency/speed
python "vpn分析/vpn_orchestrator/main.py" daemon [interval]  # Daemon mode: continuous health-check + auto-failover (default 30s)
python "vpn分析/vpn_orchestrator/main.py" status    # Show sing-box process and proxy status
python "vpn分析/vpn_orchestrator/main.py" check     # Full connectivity check (latency + speed test)
python "vpn分析/vpn_orchestrator/main.py" start/stop/restart  # Process control
python "vpn分析/vpn_orchestrator/main.py" browser   # Open ChatGPT + Gemini

# Debug / analysis scripts
python "vpn分析/vpn_orchestrator/debug_start.py"    # Diagnose sing-box startup issues
python "vpn分析/vpn_orchestrator/analyze_db.py"     # Full DB + config.json dump
```

## Architecture

```
vpn分析/
├── 01_架构分析报告.md          # Reverse-engineering report of v2rayN internals
├── 02_MVP设计文档.md           # MVP design document
├── _db_explorer.py             # Early DB exploration script
├── analyze_all.py              # Full analysis: DB + config.json + cache.db
└── vpn_orchestrator/
    ├── main.py                 # CLI entry point (interactive menu + subcommands)
    ├── config.py               # Paths/ports/URLs pointing at v2rayN installation
    ├── orchestrator.py         # VpnOrchestrator: high-level facade combining all modules
    ├── daemon.py               # VpnDaemon: long-running health-check loop + auto-failover
    ├── models/
    │   └── profile.py          # ProfileItem dataclass + profile_from_db_row() factory
    ├── core/
    │   ├── state.py            # VpnState enum + StateMachine (DISCONNECTED→CONNECTING→CONNECTED→DEGRADED→RECOVERING)
    │   ├── logging_config.py   # Shared logging setup (console + file, timestamps, levels)
    │   ├── db_manager.py       # SQLite read/write on guiNDB.db (nodes, subscriptions, stats)
    │   ├── config_builder.py   # Build sing-box outbound from ProfileItem → write config.json
    │   └── process_manager.py  # Find/kill/start/restart sing-box.exe via psutil + subprocess
    └── services/
        ├── proxy_checker.py    # SOCKS5 proxy connectivity check (Google 204, latency, speed)
        ├── node_switcher.py    # Manual + auto node switching (best by latency, or iterate until working)
        └── browser_launcher.py # Opens ChatGPT + Gemini tabs via webbrowser.open_new_tab()
```

### Dependency graph (layer direction)

`main.py` → `orchestrator.py` → `core/` + `services/` → `models/profile.py` + `config.py`

### Key design decisions

- **No GUI automation** — directly reads/writes v2rayN's SQLite DB (`guiNDB.db`) and `config.json`, then controls `sing-box.exe` as a subprocess. This is the core architectural insight from the reverse-engineering report.
- **config.json patching, not full generation** — `config_builder.py` reads the existing config, replaces only the `proxy` outbound entry, then writes back. Inbounds, DNS, and routing rules are preserved as-is.
- **SOCKS5 proxy is the health check** — since sing-box has no HTTP API, connectivity is verified by making HTTP requests through `socks5://127.0.0.1:10808` to Google's `/generate_204` endpoint.
- **sing-box 1.12+ compatibility** — process_manager.py sets `ENABLE_DEPRECATED_LEGACY_DNS_SERVERS=true` to handle older DNS config formats in newer sing-box versions.

### External dependency path

The orchestrator depends on a v2rayN installation at `d:\useful\加速器\v2rayN-Core\v2rayN-windows-64`. The critical touchpoints are:
- `guiConfigs/guiNDB.db` — SQLite DB with nodes, subscriptions, routing rules
- `binConfigs/config.json` — sing-box runtime config (generated from active node)
- `bin/sing_box/sing-box.exe` — the actual proxy core

### Coexistence with v2rayN GUI

v2rayN and this orchestrator must NOT run simultaneously — they will fight over `config.json` and the sing-box process. Stop v2rayN before using the orchestrator.
