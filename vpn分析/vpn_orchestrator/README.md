# VPN Orchestrator v1.0

**AI-driven VPN runtime orchestrator — auto node switching, health checking, and self-healing for v2rayN without the GUI.**

```
Google 204: HTTP 204, 658ms   |   Exit IP: 13.212.79.46 (AWS Singapore)
```

> 爱人不亲反其仁，治人不治反其智，礼人不答反其敬。
> 行有不得者，皆反求诸己，其身正而天下归之。
> 《诗》云："永言配命，自求多福。"
>
> — 孟子

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

---

# 中文版

> 爱人不亲反其仁，治人不治反其智，礼人不答反其敬。
> 行有不得者，皆反求诸己，其身正而天下归之。
> 《诗》云："永言配命，自求多福。"
>
> — 孟子

## VPN Orchestrator v1.0 — 这是什么？

一个 **Python 编排器**，接管 v2rayN 的大脑，保留它的肌肉。

v2rayN 是 Windows 上流行的 VPN 客户端。它有一个 GUI、一个存满代理节点的 SQLite 数据库、以及两个后台进程（sing-box 负责 TUN 路由，Xray 负责代理出站）。问题是：你**只能通过 GUI 来操控它**。

这个项目**替换了 GUI 的控制层**，让你可以用命令行、脚本、或者 AI 来自动化管理 VPN：

- 读取 v2rayN 的 SQLite 数据库，发现所有代理节点
- 热补丁运行时配置来切换节点（不破坏 TUN/路由/DNS）
- 管理双进程生命周期（sing-box + Xray）
- 持续监控代理健康状态，断线自动恢复
- 代理就绪后自动打开 ChatGPT、Gemini 浏览器标签页

## 为什么做这个？

因为没人想在 GUI 里一个个手动点节点。因为凌晨两点节点挂了没人想起来切换。因为你每天用的 AI 工具应该一行命令就能配上代理。

还有：v2rayN GUI 和这个编排器**不能同时运行**——它们会抢 `config.json`。所以选一个。选这个。

## 快速开始

```bash
# 1. 安装依赖 (Python 3.12+)
pip install -r requirements.txt

# 2. 以管理员身份运行（TUN 虚拟网卡需要管理员权限）
python main.py auto

# 或者直接双击 bat 文件：
vpn_start.bat  →  右键 "以管理员身份运行"
```

它会自动选出延迟最低的节点，启动 sing-box + Xray，验证代理连通性，然后打开 ChatGPT 和 Gemini。

## 命令一览

| 命令 | 功能 |
|---------|-------------|
| `python main.py auto` | 全自动：选最优节点 → 启动进程 → 验证 → 打开浏览器 |
| `python main.py daemon [秒]` | 守护模式：持续健康检查 + 自动故障转移（默认 30s） |
| `python main.py list` | 列出数据库中所有 41 个节点 |
| `python main.py switch <名称/编号>` | 切换到指定节点 |
| `python main.py best` | 切换到延迟最低的节点 |
| `python main.py working` | 逐个尝试节点直到找到可用的 |
| `python main.py status` | 查看双进程状态和当前节点 |
| `python main.py check` | 完整连通性检测（延迟 + 速度） |
| `python main.py browser` | 打开 ChatGPT + Gemini |
| `python main.py start/stop/restart` | 进程控制 |
| `python main.py` | 交互式菜单 |

## 架构

```
                    VPN Orchestrator
                    ┌───────────────┐
                    │  orchestrator │  状态机 + 恢复引擎
                    └───────┬───────┘
          ┌─────────────────┼─────────────────┐
    ┌─────┴─────┐    ┌──────┴──────┐    ┌─────┴─────┐
    │ 节点切换器  │    │ 运行时管理器  │    │ 健康检查   │
    └─────┬─────┘    └──────┬──────┘    └─────┬─────┘
          │                 │                  │
    ┌─────┴─────┐    ┌──────┴──────┐    ┌─────┴─────┐
    │ guiNDB.db │    │ 双进程       │    │ SOCKS5    │
    │ (SQLite)  │    │ 生命周期      │    │ 代理检测   │
    └───────────┘    └──────┬──────┘    └───────────┘
                            │
          ┌─────────────────┼─────────────────┐
    ┌─────┴─────┐                      ┌─────┴─────┐
    │ sing-box  │  TUN + 路由          │ xray.exe  │  代理
    │ configPre │  + DNS + tun-socks   │ config    │  出站
    └───────────┘                      └───────────┘
```

### 双进程发现：为什么 41 个节点全部超时

v2rayN 秘密地运行了**两个**进程，而不是一个：

| 进程 | 配置文件 | 职责 |
|---------|--------|------|
| `sing-box.exe` | `configPre.json` (10 KB) | TUN 虚拟网卡、路由、DNS、tun-protect-socks 入站 (:58481) |
| `xray.exe` | `config.json` (1.6 KB) | SOCKS5 入站 (:58482)、代理出站到远程节点 |

Xray 的代理出站带有 `dialerProxy: tun-protect-socks`——它把自己的连接通过 sing-box 的 TUN 接口发送，避免路由死循环。**两个进程缺一不可。**

我们连续测试了 29 个节点全部超时后才发现这个问题。修复方案：完全重写 `RuntimeManager`，先启动 sing-box（TUN 就绪），再启动 Xray（代理就绪）。切换节点时**只重启 Xray**——TUN 基础设施保持不变。

### Patch 策略：绝不重新生成配置

编排器**永远不**从零生成 config.json。它读取 v2rayN 当前在用的 `config.json`，找到 `"proxy"` 出站，只替换连接参数（地址、端口、协议、TLS）。其他所有内容——inbounds、DNS、路由规则、TUN 设置——原封不动。

这是让一切正常运转的核心原则：**v2rayN 的 config 是唯一的真相源**。

### 状态机

```
DISCONNECTED → CONNECTING → CONNECTED → DEGRADED → RECOVERING → CONNECTED
                    │                         │            │
                    ↓                         ↓            ↓
                  FAILED ←───────────────────┴────────────┘
                    │
                    └──→ CONNECTING (重试循环)
```

恢复策略升级：0-2 次失败 → 重启进程，3-5 次 → 切换节点，6-8 次 → 恢复配置，9-14 次 → 退避等待，15+ 次 → 放弃 → FAILED

## 系统要求

- **Windows**（Windows 11 测试通过）
- **Python 3.12+**
- **v2rayN** 安装在 `d:\useful\加速器\v2rayn`（可修改 config.py 中的 `BASE_DIR`）
- **管理员权限**（sing-box 创建 TUN 虚拟网卡需要）
- 已导入代理节点的 v2rayN 数据库（订阅或手动导入均可）

## 常见问题

**Q: 为什么需要管理员权限？**
A: sing-box 需要创建 TUN 虚拟网络接口（和 VPN 虚拟网卡一样原理），这在 Windows 上需要 Administrator 权限。v2rayN 也一样——只是它自动提权你没注意到。

**Q: 能和 v2rayN GUI 一起用吗？**
A: 不能。它们会争抢 `config.json` 和代理进程。先关掉 v2rayN 再用编排器。

**Q: 所有节点都挂了怎么办？**
A: 守护进程会进入退避循环，每隔几分钟重试。最终到达 FAILED 状态等待人工介入。实际上订阅里 41 个节点基本不会全部同时挂掉。

**Q: 支持 VLESS/VMess/Trojan 吗？**
A: 全部支持。outbound builder 能生成 Shadowsocks、VMess、VLESS（gRPC 和 Vision+httpupgrade）的出站配置。adapter 层自动检测 config 格式。

**Q: 能改 v2rayN 的安装路径吗？**
A: 编辑 `config.py` 里的 `BASE_DIR` 即可。

## 项目结构

```
vpn_orchestrator/
├── main.py                  入口（交互菜单 + CLI 子命令）
├── orchestrator.py          编排层（状态机 + 恢复引擎）
├── daemon.py                守护进程（持续监控 + 自动故障转移）
├── config.py                路径/端口/核心自动检测
├── test_admin.py            管理员权限验证脚本
├── vpn_start.bat            一键启动
├── models/
│   └── profile.py           ProfileItem 数据类
├── core/
│   ├── runtime_manager.py   双进程管理 + 健康检查 + 恢复
│   ├── process_manager.py   向后兼容包装
│   ├── config_builder.py    Config patch 委托
│   ├── db_manager.py        guiNDB.db 读写
│   ├── state.py             状态机 + 恢复策略
│   └── logging_config.py    共享日志配置
├── adapters/
│   ├── xray_config.py       Config 格式检测 + 字段级 patch
│   └── outbound_builder.py  Profile → Xray/singbox 出站生成
└── services/
    ├── node_switcher.py     手动/自动节点切换
    ├── proxy_checker.py     SOCKS5 代理连通性 + 延迟 + 速度
    └── browser_launcher.py  打开 ChatGPT + Gemini
```

## 致谢

通过逆向工程 v2rayN 内部架构构建：SQLite 数据库结构、双进程配置生成、TUN 路由机制。无 GUI 自动化——直接协议级控制。

---

*"GUI 是可选的。协议不是。"*
