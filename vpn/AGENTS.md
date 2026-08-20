# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project overview

A Python VPN orchestrator that bypasses the v2rayN GUI to directly control the **Xray** proxy core (single process, no TUN) through protocol-level control. It replaces the GUI's control layer: reads/writes v2rayN's SQLite node DB (`guiNDB.db`), dynamically generates the Xray config from a node (instead of patching an existing `config.json`), and manages the `xray.exe` subprocess. On connect it also sets the **Windows system proxy** to the local port so every app routes through it — matching v2rayN's global mode.

## Commands (run with system Python 3.12, not managed 3.13 — it lacks psutil/requests)

```bat
set V2RAYN_ROOT=d:\newlife\v2rayN\v2rayn
python "vpn_orchestrator\main.py" connect        # scan → pick fastest reachable node → start xray → enable global system proxy (PRIMARY)
python "vpn_orchestrator\main.py" speedtest [N]  # speed-test N nodes (does not touch main proxy)
python "vpn_orchestrator\main.py" switch <name|index>  # switch to a specific node
python "vpn_orchestrator\main.py" proxy-on       # enable Windows system proxy only (xray already running)
python "vpn_orchestrator\main.py" proxy-off      # disable system proxy
python "vpn_orchestrator\main.py" stop            # kill xray + clear system proxy
python "vpn_orchestrator\main.py" list            # list all nodes
python "vpn_orchestrator\main.py" status          # process + proxy status
```

Legacy/compat commands also exist (`auto`, `best`, `working`, `daemon`, `check`, `browser`, `subs`, `start`, `restart`) but are not verified on this machine — prefer `connect`.

## Architecture

```
vpn_orchestrator/
├── main.py                 CLI entry (subcommand dispatch)
├── config.py               path/port/core-type auto-detection (V2RAYN_ROOT overrides)
├── orchestrator.py         high-level facade: connect_best, state machine, global-proxy hookup
├── core/
│   ├── runtime_manager.py  xray process lifecycle (single process, NOT dual-process)
│   ├── system_proxy.py     Windows system-proxy registry control (global mode)
│   ├── db_manager.py       guiNDB.db read/write
│   ├── state.py            VpnState state machine
│   └── logging_config.py   logging (with rotation)
├── adapters/
│   └── xray_config.py      dynamic Xray config generation from a node (DNS + node-domain direct-resolve)
├── models/
│   └── profile.py          ProfileItem dataclass
└── services/
    ├── proxy_checker.py    connectivity check (same-session warm-up true latency + ChatGPT reachability)
    └── node_switcher.py    scan/speed-test + ranking + sequential fallback
```

Dependency direction: `main.py` → `orchestrator.py` → `core/` + `services/` → `models/profile.py` + `config.py`.

## Key design decisions

- **Dynamic generation, never reuse/patch a stale config** — `adapters/xray_config.py` recreates the Xray config from the node data (mirroring v2rayN's `GenerateClientConfigContent`), rather than editing an existing `config.json`.
- **Global system proxy, not a per-browser window** — `core/system_proxy.py` writes `HKCU\...\Internet Settings` and broadcasts the change, so all apps route through the proxy (same as v2rayN global mode).
- **Single Xray process, no admin needed** — this machine runs Xray core (not sing-box TUN), so no administrator privileges are required.
- **Coexistence guard** — refuses to start while the v2rayN GUI is running (they fight over `config.json` and the xray process).

## External dependency path

v2rayN auto-detected at `d:\newlife\v2rayN\v2rayn` (first entry in config.py's probe list). Override with `V2RAYN_ROOT`. Critical touchpoints:
- `guiConfigs/guiNDB.db` — node DB
- `guiConfigs/guiNConfig.json` — inbound port (10826) etc.
- `bin/xray/xray.exe` — the proxy core

Proxy port: **10826** (mixed SOCKS5 + HTTP), read from `guiNConfig.json`.

## Gotchas already fixed (do not re-introduce)

- Speed-test false-negative: old code only `sleep(1.5)` before probing concurrent xray instances whose SOCKS port wasn't bound yet → "proxy port not listening" and every node marked dead. Fix: wait for port readiness + retry transient failures.
- Inflated latency (~355ms vs real ~80ms): warm-up and measurement used different sessions, so the tunnel was rebuilt each time. Fix: reuse one session for warm-up and timing.
- ChatGPT unreachable: often a node whose egress IP is blocked by OpenAI/Cloudflare. Fix: speed-test probes ChatGPT reachability and ranks it ahead of raw latency.

## Coexistence with v2rayN GUI

Must NOT run simultaneously. Close v2rayN GUI before running `connect`.
