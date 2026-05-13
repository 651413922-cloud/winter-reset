# Python VPN Orchestrator MVP 设计文档

## 1. 核心思路

放弃 GUI 操控，直接对 Sing-Box 进行**配置级**和**进程级**控制：

```
Python Orchestrator
├── 直接读写 SQLite (guiNDB.db)        → 节点管理
├── 直接生成/替换 config.json           → 切换节点
├── 直接控制 sing-box.exe 进程           → 启停
├── 直接测试代理端口 (127.0.0.1:10808) → 状态检测
└── 直接打开浏览器 (webbrowser)        → ChatGPT/Gemini
```

---

## 2. 目录结构

```
vpn_orchestrator/
├── main.py                   # 入口：CLI/交互模式
├── requirements.txt          # 依赖：requests, psutil
├── config.py                 # 所有路径/端口/URL 常量
│
├── core/
│   ├── __init__.py
│   ├── db_manager.py         # SQLite 读写（节点/订阅）
│   ├── process_manager.py    # sing-box 进程控制
│   └── config_builder.py     # 构建/替换 config.json
│
├── services/
│   ├── __init__.py
│   ├── proxy_checker.py      # 代理连通性检测（请求 Google）
│   ├── node_switcher.py      # 自动切换节点
│   └── browser_launcher.py   # 打开 ChatGPT/Gemini
│
├── models/
│   ├── __init__.py
│   └── profile.py            # ProfileItem 数据模型
│
└── orchestrator.py           # 高层编排逻辑
```

---

## 3. 模块拆分

### 3.1 `config.py` — 配置常量
```python
# 路径
GUI_DB = "guiConfigs/guiNDB.db"
CONFIG_JSON = "binConfigs/config.json"
SING_BOX_EXE = "bin/sing_box/sing-box.exe"

# 代理
SOCKS5_PROXY = "socks5://127.0.0.1:10808"
HTTP_PROXY = "http://127.0.0.1:10808"

# 检测
CHECK_URL = "https://www.google.com/generate_204"
TIMEOUT = 10

# 浏览器
TARGETS = [
    "https://chatgpt.com",
    "https://gemini.google.com"
]
```

### 3.2 `db_manager.py` — SQLite 控制器
- 列出所有节点
- 获取节点详情（地址/端口/协议/uuid/flow/sni/网络/path）
- 获取订阅列表
- 获取节点延迟/速度数据
- 更新活动节点
- 更新订阅（触发刷新）

### 3.3 `config_builder.py` — 配置生成器
- 从 ProfileItem 数据构建完整 sing-box config.json
- 替换当前活动节点（修改 outbounds.proxy）
- 生成 configTest 配置（测试用）
- 保留原路由/DNS/Inbound 不变

### 3.4 `process_manager.py` — 进程控制
- 查找 sing-box.exe 进程（psutil）
- 停止 sing-box（kill）
- 启动 sing-box（subprocess.Popen）
- 重启 sing-box（stop → write config → start）
- 检查进程是否运行

### 3.5 `proxy_checker.py` — 连通性检测
- 通过 SOCKS5 代理访问 Google 204
- 测量延迟
- 测量速度（下载测试文件）
- 返回可用/不可用/延迟值

### 3.6 `node_switcher.py` — 节点切换
- 按名称查找节点
- 按索引切换
- 自动选择最优节点（速度/延迟)
- 切换 → 重启 → 检测连通性

### 3.7 `browser_launcher.py` — 浏览器
- 用 webbrowser.open() 打开目标 URL
- 支持多标签页

### 3.8 `orchestrator.py` — 编排
- `auto_connect()`: 选最优节点 → 切换 → 检测 → 打开浏览器
- `switch_to_best()`: 自动选延迟最低的节点
- `switch_node(name)`: 指定节点名切换
- `refresh_subscription()`: 更新订阅

---

## 4. 风险点

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| sing-box 进程被 v2rayN 同时管理 | ⚠️ 中 | 检查 sing-box 是否正在运行，先停止 v2rayN |
| 配置文件损坏导致 VPN 中断 | ⚠️ 中 | 修改前备份 config.json |
| 订阅 URL 失效 | ⚠️ 低 | 手动预留节点，用 DB 冗余 |
| SOCKS5 端口占用 | ⚠️ 低 | 端口检测，释放后启动 |
| 没有 API 回调确认 | ⚠️ 中 | 用代理检测代替 API 确认状态 |

---

## 5. 与 GUI 共存策略

| 场景 | 策略 |
|------|------|
| v2rayN 正在运行 | 先关闭 v2rayN，然后接管 sing-box |
| v2rayN 未运行 | 直接控制 sing-box |
| 需要返回 GUI | 停止 orchestrator，手动重启 v2rayN |
| 混合使用 | 不推荐 — 会互相覆盖 config.json |

---

## 6. 后续扩展（非 MVP）

- LLM Agent 接入（自动决策节点切换时机）
- 定时健康检查 + 自动重连
- 多订阅管理
- 测速结果记录 + 趋势分析
- Telegram Bot 远程控制
- 策略路由定制