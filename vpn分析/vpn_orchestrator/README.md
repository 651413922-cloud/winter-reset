# VPN Orchestrator v1.0

**AI-driven VPN runtime orchestrator — auto node switching, health checking, and self-healing for v2rayN without the GUI.**

```
Google 204: HTTP 204, 658ms   |   Exit IP: 13.212.79.46 (AWS Singapore)
```

## What is this?

A Python orchestrator that takes over v2rayN's brain while keeping its muscles.

v2rayN is a popular Windows VPN client. It has a GUI, a database full of proxy nodes, and it manages two processes (sing-box for TUN routing + Xray for the actual proxy connection). The problem: the GUI is the only way to control it.

This project **replaces the GUI's control layer** with a scriptable, AI-friendly orchestrator that:

- Reads v2rayN's SQLite database to discover all proxy nodes
- Patches the runtime config to switch nodes (without destroying TUN/routing/DNS)
- Manages the dual-process lifecycle (sing-box + Xray)
- Continuously monitors proxy health and auto-recovers from failures
- Opens your AI tools (ChatGPT, Gemini) when the VPN is ready

## Why?

Because clicking through a GUI to switch nodes is tedious. Because when a node goes down at 2 AM, you want automatic failover. Because the AI tools you use every day should be one command away.

Also: the v2rayN GUI and this orchestrator **cannot coexist** — they fight over `config.json`. So pick one. Pick this one.

## Quick Start

```bash
# 1. Install dependencies (Python 3.12+)
pip install -r requirements.txt

# 2. Run as Administrator (required — TUN needs admin)
python main.py auto

# Or just double-click:
vpn_start.bat  →  Right-click "Run as administrator"
```

That's it. It'll pick the fastest node, start sing-box + Xray, verify connectivity, and open ChatGPT + Gemini in your browser.

## Commands

| Command | What it does |
|---------|-------------|
| `python main.py auto` | Full auto-connect: pick best node → start processes → verify → open browser |
| `python main.py daemon [interval]` | Daemon mode: continuous health check + auto-failover (default 30s) |
| `python main.py list` | List all 41 proxy nodes from the database |
| `python main.py switch <name/index>` | Switch to a specific node |
| `python main.py best` | Switch to the lowest-latency node |
| `python main.py working` | Try nodes one by one until one works |
| `python main.py status` | Show process status (sing-box + Xray) and current node |
| `python main.py check` | Full connectivity test (latency + speed) |
| `python main.py browser` | Open ChatGPT + Gemini tabs |
| `python main.py start/stop/restart` | Process lifecycle control |
| `python main.py` | Interactive menu (no args) |

## Architecture

```
                    VPN Orchestrator
                    ┌───────────────┐
                    │  orchestrator │  state machine + recovery engine
                    └───────┬───────┘
          ┌─────────────────┼─────────────────┐
    ┌─────┴─────┐    ┌──────┴──────┐    ┌─────┴─────┐
    │ node      │    │ runtime     │    │ health    │
    │ switcher  │    │ manager     │    │ checker   │
    └─────┬─────┘    └──────┬──────┘    └─────┬─────┘
          │                 │                  │
    ┌─────┴─────┐    ┌──────┴──────┐    ┌─────┴─────┐
    │ guiNDB.db │    │ dual-proc   │    │ SOCKS5    │
    │ (SQLite)  │    │ lifecycle   │    │ proxy     │
    └───────────┘    └──────┬──────┘    └───────────┘
                            │
          ┌─────────────────┼─────────────────┐
    ┌─────┴─────┐                      ┌─────┴─────┐
    │ sing-box  │  TUN + routing       │ xray.exe  │  proxy
    │ configPre │  + DNS + tun-socks   │ config    │  outbound
    └───────────┘                      └───────────┘
```

### The dual-process insight (how we stopped 41 nodes from timing out)

v2rayN secretly runs **two** processes, not one:

| Process | Config | Role |
|---------|--------|------|
| `sing-box.exe` | `configPre.json` (10 KB) | TUN virtual NIC, routing, DNS, tun-protect-socks inbound on :58481 |
| `xray.exe` | `config.json` (1.6 KB) | SOCKS5 inbound on :58482, proxy outbound to remote node |

Xray's proxy outbound has `dialerProxy: tun-protect-socks` — it routes its own connection through sing-box's TUN interface to avoid routing loops. Without both processes running, every single node times out.

We discovered this after testing 29 of 41 nodes, all failing. The fix was a complete rewrite of `RuntimeManager` to manage both processes: sing-box starts first (TUN up), then Xray (proxy up). Node switching only restarts Xray — no need to tear down the TUN.

### Patch strategy (never regenerate config)

The orchestrator **never** generates a full config from scratch. It reads v2rayN's working `config.json`, finds the `"proxy"` outbound, and replaces only the connection parameters (address, port, protocol, TLS settings). Everything else — inbounds, DNS, routing rules, TUN settings — stays untouched.

This is the architectural rule that made everything work: **v2rayN's config is the single source of truth**.

### State machine

```
DISCONNECTED → CONNECTING → CONNECTED → DEGRADED → RECOVERING → CONNECTED
                    │                         │            │
                    ↓                         ↓            ↓
                  FAILED ←───────────────────┴────────────┘
                    │
                    └──→ CONNECTING (retry loop)
```

Recovery escalation: 0-2 failures → RESTART, 3-5 → SWITCH_NODE, 6-8 → RESET_CONFIG, 9-14 → BACKOFF, 15+ → FAILED

## Requirements

- **Windows** (tested on Windows 11)
- **Python 3.12+**
- **v2rayN** installed at `d:\useful\加速器\v2rayn` (the default path)
- **Administrator privileges** (sing-box needs admin to create the TUN virtual network interface)
- A v2rayN database with proxy nodes (subscription or manual import)

## Project structure

```
vpn_orchestrator/
├── main.py                  CLI entry point
├── orchestrator.py          High-level facade (state machine + recovery)
├── daemon.py                Long-running health-check daemon
├── config.py                Paths, ports, core auto-detection
├── test_admin.py            Admin privilege verification script
├── vpn_start.bat            One-click launcher
├── models/
│   └── profile.py           ProfileItem dataclass
├── core/
│   ├── runtime_manager.py   Dual-process lifecycle + health + recovery
│   ├── process_manager.py   Backward-compat wrapper
│   ├── config_builder.py    Config patch delegation
│   ├── db_manager.py        SQLite read/write on guiNDB.db
│   ├── state.py             State machine + recovery strategies
│   └── logging_config.py    Shared logging setup
├── adapters/
│   ├── xray_config.py       Config format detection + field-level patching
│   └── outbound_builder.py  Profile → Xray/singbox outbound generator
└── services/
    ├── node_switcher.py     Manual + auto node switching
    ├── proxy_checker.py     SOCKS5 connectivity + latency + speed
    └── browser_launcher.py  Opens ChatGPT + Gemini
```

## FAQ

**Q: Why does it need admin rights?**
A: sing-box creates a TUN virtual network interface (like a VPN virtual NIC). This requires Administrator privileges on Windows. v2rayN has the same requirement — you just don't notice because it auto-elevates.

**Q: Can I run this alongside v2rayN GUI?**
A: No. They will fight over `config.json` and the proxy processes. Close v2rayN first.

**Q: What happens if all nodes are down?**
A: The daemon enters a backoff loop, retrying every few minutes. Eventually it reaches FAILED state and waits for manual intervention. In practice, with 41 nodes from a subscription, this almost never happens.

**Q: Does it support VLESS/VMess/Trojan?**
A: Yes. The outbound builder handles Shadowsocks, VMess, and VLESS (both gRPC and Vision+httpupgrade transports). The adapter layer detects config format automatically.

**Q: Can I change the v2rayN installation path?**
A: Edit `BASE_DIR` in `config.py`.

## Credits

Built by reverse-engineering v2rayN's internal architecture: SQLite database schema, dual-process config generation, and TUN routing mechanics. No GUI automation — direct protocol-level control.

---

*"The GUI is optional. The protocol is not."*
