# VPN Orchestrator

> 当前版本：**1.1.0819** — 版本号定义在 `config.py` 的 `__version__` 常量，托盘标题栏与「属性」面板共用。

一个 Python 编排器，绕过 v2rayN GUI，直接读写其 SQLite 节点库（`guiNDB.db`）与配置，再以子进程控制 **Xray** 代理核心，实现「扫描全部节点 → 自动选最快 → 拉起代理 → 全局系统代理」的一键连接。

当前机器实测可用：自动选出最快节点（约 80–100ms 真实延迟），并把 **Windows 系统代理**设为本机，所有浏览器/应用自动走代理（与 v2rayN 全局模式行为一致）。

---

## 核心工作流：`connect`

1. **前置检查** — 共存保护（v2rayN GUI 必须关闭，否则拒绝启动）；探测 v2rayN 安装路径与核心类型（本机为 Xray 单进程）。
2. **扫描测速** — 并发扫描所有节点（过滤掉 `127.0.0.1`/localhost、端口 `0`/`65535` 的坏节点）。每个节点：独立起一份 Xray + 专用临时端口 → **等端口真正监听**（最多 8s）→ 测真实延迟（warm-up 与测量复用同一会话，消除隧道重建冷开销）→ 探测 ChatGPT 可达性；瞬态失败自动重试。
3. **自动选优** — 排序规则：**在线优先 → ChatGPT 可达优先 → 延迟升序 → 速度降序**，取第一个（即「最快且能到 ChatGPT」的节点）。
4. **拉起代理** — 把该节点动态生成 Xray 配置（不依赖旧 `config.json`，每次从节点数据现生成，含完整 DNS 模块与节点域名直连解析）→ 启动 Xray，监听 `127.0.0.1:10826`（mixed：SOCKS5 + HTTP）。
5. **校验 + 全局代理** — 连通性校验通过 → 状态机置 `CONNECTED` → 把 **Windows 系统代理**设为 `127.0.0.1:10826`，所有软件自动走代理。
6. **兜底** — 若并发扫描没筛出可用节点，退化为顺序逐个实测（`switch_until_working`），保证「只要有一个节点能连就一定连上」。

> 排序里「ChatGPT 可达」优先于「绝对延迟最低」：若你要求「严格选延迟最低的节点（不管 ChatGPT）」，改 `node_switcher.py` 的排序去掉 ChatGPT 优先即可。

---

## 用法

**前置：先关掉 v2rayN GUI**（两者抢 `config.json` 和 Xray 进程，不能并存）。

- **图形界面（推荐，单文件 exe）**：双击 `dist/VPNOrchestrator.exe` —— 右下角托盘图标，右键「连接 / 断开 / 退出」。它是常驻进程，退出时**自动杀 Xray + 清系统代理**，一个 exe 搞定开与关。
- **命令行**（必须用系统 Python 3.12，不要用 managed 3.13——缺 `psutil`/`requests`）：

```bat
set V2RAYN_ROOT=d:\newlife\v2rayN\v2rayn
"C:\Users\65141\AppData\Local\Programs\Python\Python312\python.exe" "D:\newlife\GitHub\winter-reset\vpn\vpn_orchestrator\main.py" connect
```

- **代理地址**：`127.0.0.1:10826`（SOCKS5 与 HTTP 均支持，无需再为某个浏览器单独配置）。
- **不需要管理员权限**：本机用 Xray 单进程（无 TUN 虚拟网卡），普通用户即可运行。

### 子命令（`main.py <cmd>`）

| 命令 | 作用 |
|------|------|
| `connect` | 全自动：扫描测速 → 自动选最快节点 → 拉起代理 → 开全局系统代理（**主用**） |
| `speedtest [N]` | 测速前 N 个节点并打印结果（不接管主代理，可配合 GUI 共存时排查） |
| `switch <名称/编号>` | 切换到指定节点 |
| `proxy-on` / `proxy-off` | 仅切换 Windows 全局系统代理（Xray 已在跑时用） |
| `stop` | 停 Xray + 清系统代理 |
| `list` | 列出所有节点 |
| `status` | 查看进程与代理状态 |
| `auto` / `best` / `working` / `daemon` / `check` / `browser` / `subs` / `start` / `restart` | 早期遗留/兼容性命令，当前机器未逐一验证，优先用 `connect` |

---

## 图形界面：托盘 exe（VPNOrchestrator.exe）

把「开 / 关」收敛到一个常驻程序，像正常软件一样使用：

- 双击 `dist/VPNOrchestrator.exe` → 右下角出现托盘图标（灰=未连接 / 黄=连接中 / 绿=已连接 / 红=失败）。
- 右键菜单：**连接（扫描+选最优）** / **断开并清除代理** / **退出（自动断开）**。
- 启动即同步现有状态：若已有 Xray 在跑（上一会话残留），会被接管显示为「已连接」。
- **退出 / 关闭 / 被任务管理器杀**，都会统一杀 Xray + 清系统代理（`atexit` + 信号钩子兜底），不会留下孤儿进程或残留代理。
- **设置子菜单**（右键「设置」）：
  - **属性**：只读多字段窗口，展示 版本 / 核心引擎 / 当前状态 / 本地代理 / 系统代理 / 节点总数 / 套餐到期 / 剩余流量 / 距离下次重置，带「复制」按钮便于排障时贴出。
  - **日志**：滚动文本框，tail 最近 100 条历史日志（含之前运行留下的失败），顶部显示「最近测速摘要」（最优节点 + 扫描节点数），可按「全部 / 仅失败&警告 / 仅关键事件」筛选。
- 日志：`%LOCALAPPDATA%\VPNOrchestrator\vpn_orchestrator.log`。

### 重新打包

源码 `vpn_orchestrator/tray_app.py`，用 PyInstaller 打成单文件（需先 `pip install pystray pillow pyinstaller`）：

```bat
"C:\Users\65141\AppData\Local\Programs\Python\Python312\python.exe" build_tray_exe.py
```

产物 `dist/VPNOrchestrator.exe`（约 33 MB，构建脚本已自动扫描 `vpn_orchestrator` 下所有模块作 `--hidden-import`，无需手动补包）。

---

## 架构

```
vpn_orchestrator/
├── main.py                 命令行入口（子命令分发）
├── tray_app.py             系统托盘 GUI（单文件 exe 入口）
├── config.py               路径/端口/核心类型自动探测（V2RAYN_ROOT 可覆盖）
├── orchestrator.py         高层编排：connect_best / 状态机 / 全局代理挂接
├── core/
│   ├── runtime_manager.py  Xray 进程生命周期（单进程，非双进程）
│   ├── system_proxy.py     Windows 系统代理注册表控制（全局代理的关键）
│   ├── db_manager.py       guiNDB.db 读写（节点/订阅/统计）
│   ├── state.py            VpnState 状态机
│   └── logging_config.py   日志（含轮转）
├── adapters/
│   └── xray_config.py      从节点动态生成 Xray 配置（含 DNS + 节点域名直连解析）
├── models/
│   └── profile.py          ProfileItem 数据模型
└── services/
    ├── proxy_checker.py    连通性检测（同会话 warm-up 真实延迟 + ChatGPT 可达探测）
    └── node_switcher.py    扫描测速 + 排序选优 + 顺序兜底
├── ui/
│   ├── __init__.py
│   └── panels.py           托盘弹窗：属性（多字段只读）/ 日志（滚动文本 + 筛选 + 测速摘要）
```

依赖方向：`main.py` → `orchestrator.py` → `core/` + `services/` → `models/profile.py` + `config.py`；`tray_app.py` → `ui/panels.py`（属性/日志弹窗）。

### 关键设计

- **不写死/不克隆配置** — 每次从节点数据动态生成 Xray 配置（复刻 v2rayN 的 `GenerateClientConfigContent` 逻辑），而不是修补旧 `config.json`。
- **全局系统代理** — 像 v2rayN 一样写注册表 `HKCU\...\Internet Settings` 并广播，让所有软件自动走代理，而非只给某个浏览器窗口配代理。
- **共存保护** — 检测到 v2rayN GUI 运行即拒绝启动。

---

## v2rayN 依赖路径

- 默认自动探测：`d:\newlife\v2rayN\v2rayn`（config.py 探测列表首位）。
- 可用环境变量覆盖：`set V2RAYN_ROOT=<你的 v2rayN 目录>`。
- 关键触点：`guiConfigs/guiNDB.db`（节点库）、`guiConfigs/guiNConfig.json`（入站端口等）、`bin/xray/xray.exe`（核心）。

---

## 已解决的历史坑（避免重复踩）

- **测速全节点假阴性**：早期只 `sleep(1.5)` 就让并发 Xray 被连通性检查连，端口未就绪 → 报「连接被拒绝，代理端口未监听」并全节点误杀。修复：等端口真正监听 + 瞬态失败重试。
- **延迟虚高（355ms vs 实际 80ms）**：warm-up 与测量用不同会话，每个新会话连 SOCKS 都要重建上游隧道（~200ms），冷开销被算进延迟。修复：warm-up 与测量复用同一会话。
- **ChatGPT 打不开**：多因选中了封锁 OpenAI 的节点 egress IP。修复：测速加 ChatGPT 可达性探测并优先排序。

---

## 注意事项

- 与 v2rayN GUI **互斥**，先关 GUI 再连。
- 当前代理由启动它的进程拉起；若进程退出（如关闭托盘 exe、关机），代理会断——届时双击 `dist/VPNOrchestrator.exe` 重连（它会自动接管残留的 Xray）。长期持久保活建议用 **Windows 计划任务**（沙箱自动化无外网不可用）。
