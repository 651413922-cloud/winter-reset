# 🏗️ Skill-based Automation Agent 架构设计方案

> 从"传统自动化脚本"升级为"低成本、长期稳定、Skill-based Automation Agent System"

---

## 1. 当前系统核心问题分析

### 1.1 架构层面的根本缺陷

当前系统的核心问题是 **vpn_controller.py 单体架构**，600+ 行代码混合了：
- 决策逻辑 (if-else 状态机)
- 执行逻辑 (pyautogui 点击)
- 图像识别逻辑 (模板匹配 + OCR)
- 异常处理逻辑
- 反循环逻辑

| 问题 | 严重程度 | 根因 |
|------|----------|------|
| 逻辑耦合 | 🔴 致命 | 决策 + 执行 + OCR 全部混杂 |
| 硬编码线路 | 🔴 致命 | 基于 line_aa1/aa2/aa3 位置依赖 |
| 模板匹配滥用 | 🟡 严重 | 7+ 种模板，每个都是脆弱点 |
| 状态机膨胀 | 🟡 严重 | 5 种状态逻辑交织 |
| 配置硬编码 | 🟢 中等 | ROI/OCR 区域硬编码 |

### 1.2 最致命的 3 个问题

**问题 #1: 位置依赖**
- 使用 `line_aa1_label.png` / `line_aa2_label.png` / `line_aa3_label.png`
- UI 线路顺序变化 → 全崩
- 本质: 把"第几条线"写死在代码里

**问题 #2: 状态模板幻觉**
- 使用 `full_line.png` / `available_line.png` 匹配进度条
- 进度条动态变化 → 匹配率持续下降
- 本质: 用静态图片匹配动态 UI 元素

**问题 #3: 决策逻辑内嵌**
- 硬编码 "先点 AA3，再点 AA2，最后 AA1"
- 优先级无法动态调整
- 本质: 业务逻辑和自动化逻辑完全耦合

---

## 2. 为什么传统方案不可持续

### 2.1 模板匹配的衰减曲线

模板匹配的准确率随 UI 更新持续下降：
- 首次截图: 100% 匹配
- 5 次后: ~85%
- 10 次后: ~70%
- UI 更新后: 可能骤降至 30%

### 2.2 传统脚本 vs Skill-based Agent

| 维度 | 传统脚本 | Skill-based Agent |
|------|----------|-------------------|
| 决策灵活性 | 硬编码 if-else | LLM 动态推理 |
| 容错能力 | 特定异常处理 | 上下文感知恢复 |
| 可扩展性 | 改代码 + 加模板 | 加 Skill + 改 Prompt |
| 维护成本 | 指数增长 | 线性增长 |
| UI 变化影响 | 可能全崩 | 局部 skill 调整 |

### 2.3 逻辑正确归属

```
业务决策逻辑 → LLM Agent (选线、重试策略)
流程编排逻辑 → Orchestrator (扫描→决策→执行)
原子操作逻辑 → Python Skills (点击、OCR、截图)
```

---

## 3. 新架构总览

```
┌──────────────────────────────────────────────┐
│        LLM Agent (策略选择器，非流程控制器)    │
│    Gemini 2.0 Flash / DeepSeek-V3            │
│                                              │
│    ⚠️ 严格限制:                              │
│    只做"策略选择"，不做"流程控制"               │
│    不决定 refresh / 循环结构 / 流程跳转        │
│                                              │
│    输出示例:                                  │
│    {"choice":"PERMANENT_FREE","strategy":     │
│     "greedy","retry_mode":"soft"}             │
└─────────────────────┬────────────────────────┘
                      │ HTTP API (仅策略选择)
                      ▼
┌──────────────────────────────────────────────┐
│   ⭐ Python State Machine (确定性状态机层)     │
│                                              │
│   关键职责:                                   │
│   • 状态记忆 (IDLE/SCANNING/CONNECTING…)     │
│   • failure counter + step tracking          │
│   • 反循环检测                                │
│   • 决定刷新/重试/跳转 (不交给LLM)             │
│   • 快速路径优先, 仅复杂场景才调LLM            │
│                                              │
│   这是 GUI automation + retry system          │
│   的刚性骨架, 不可用 LLM 替代                 │
└──────────────┬───────────────────────────────┘
               │ 策略输入 → Skill 调度
               ▼
┌──────────────────────────────────────────────┐
│         Python Agent Orchestrator (编排层)    │
│                                              │
│  职责: 构建上下文、解析LLM策略、调度Skill      │
│        Token统计、decision_log 记录           │
└──────────────┬───────────────────────────────┘
               │ 函数调用
               ▼
┌──────────────────────────────────────────────┐
│           Skill Layer (执行层)                │
│                                              │
│   skill_get_candidate_lines                  │
│   skill_read_percent                         │
│   skill_connect_line                         │
│   skill_check_connected                      │
│   skill_close_popup                          │
│   skill_refresh_page                         │
│   skill_capture_roi                          │
└──────────────┬───────────────────────────────┘
               │ pyautogui/EasyOCR/OpenCV
               ▼
┌──────────────────────────────────────────────┐
│   Resource Layer (⭐新增 — UI资源抽象层)       │
│   ROI 配置 / 窗口管理 / 截图工具 / 模板注册   │
└──────────────┬───────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│        GUI Automation Layer (基础设施)        │
└──────────────────────────────────────────────┘
```

### 3.1 ⚠️ 重大修正 — Strict Role Separation (职责强约束)

**之前的文档最大的问题是: State Machine + Orchestrator 职责重叠, 形成"两个控制中心"**

#### 必须理解的核心问题

```
❌ 错误设计:

State Machine 做流程  ← 控制中心 #1
Orchestrator 也做流程  ← 控制中心 #2  ← 冲突!
LLM 也插流程           ← 控制中心 #3

→ 三个中心同时存在 → 系统漂移 → 不可维护
```

#### ✔ 正确角色定义

```
┌─────────────────────────────────────────────────────────┐
│  🚦 State Machine = "交通规则" (绝对不能做决定)         │
│                                                         │
│  职责:                                                   │
│  • 检查"当前在哪一步"是否合法                             │
│  • 检查"是否允许跳转" (例如: CONNECTING → SCANNING?)     │
│  • 检查"是否触发 fail/retry"                             │
│  • 维护状态转换图 (State Transition Graph)               │
│                                                         │
│  ❌ 绝对不能做:                                          │
│    - 不决定选哪条线路                                     │
│    - 不决定是否 refresh (只能告知"状态非法")              │
│    - 不调 Skill                                           │
│                                                         │
│  输出: 布尔值 (状态是否合法 / 是否允许转换)               │
└─────────────────────────────────────────────────────────┘
         ↑ 咨询合法性
         │
┌─────────────────────────────────────────────────────────┐
│  🚗 Orchestrator = "司机" (真正的核心)                   │
│                                                         │
│  职责:                                                   │
│  • 调 Skill                                              │
│  • 控流程 (主循环 loop)                                  │
│  • 执行 retry 逻辑                                       │
│  • 构建上下文 → 决定走 FAST PATH 还是 LLM PATH           │
│  • 记录 decision_log                                     │
│                                                         │
│  ❌ 绝对不能做:                                          │
│    - 不自己制定策略 (只执行 LLM 或 FAST PATH 的策略)      │
│                                                         │
│  输出: 具体执行动作 (Skill 调用)                          │
└─────────────────────────────────────────────────────────┘
         ↑ 获取策略建议
         │
┌─────────────────────────────────────────────────────────┐
│  💡 LLM = "建议器" (最弱权限)                            │
│                                                         │
│  职责:                                                   │
│  • 仅输出策略选择                                       │
│                                                         │
│  输出 (唯一格式):                                       │
│  {                                                      │
│    "choice": "PERMANENT_FREE",                          │
│    "strategy": "greedy"                                 │
│  }                                                      │
│                                                         │
│  ❌ 绝对不能做:                                          │
│    - ❌ 决定是否 refresh                                 │
│    - ❌ 决定循环结构                                     │
│    - ❌ 决定流程跳转                                     │
│    - ❌ 包含坐标/ROI                                     │
└─────────────────────────────────────────────────────────┘
```

#### 类比: 交通系统

| 组件 | 类比 | 职责 |
|------|------|------|
| State Machine | 🚦 红绿灯 | 只告诉"能不能走", 不决定去哪 |
| Orchestrator | 🚗 司机 | 看红绿灯, 踩油门打方向盘, 决定路线 |
| LLM | 🗺️ 导航建议 | 建议"走哪条路更快", 但司机可以选择不听 |
| Skills | 🦾 手脚 | 执行具体动作: 打方向盘、踩刹车 |

#### 为什么这样设计

1. **State Machine 不能做决定**: 一旦 State Machine 开始做选择, 它就和 Orchestrator 冲突
2. **Orchestrator 是唯一流程控制者**: 确保整个系统只有一个"大脑"在控制流程
3. **LLM 权限最低**: 即使 LLM 返回垃圾, Orchestrator 有最终否决权

#### 新的 Agent 架构层级图 (修正版)

```
┌──────────────────────────────────────────────┐
│  💡 LLM Agent: "建议器" (最弱权限)           │
│  - 仅输出: choice + strategy                 │
│  - 不参与流程                                │
│  - 替代方案: 可被 FAST PATH 完全绕过          │
└──────────────────┬───────────────────────────┘
                   │ HTTP API (仅策略)
                   ▼
┌──────────────────────────────────────────────┐
│  🚦 State Machine: "交通规则" (绝对不能决定)  │
│                                              │
│  只做 3 件事:                                 │
│  1. 状态合法性检查 (是否允许这个跳转)          │
│  2. 计数器管理 (failure counter + step)      │
│  3. 触发条件检测 (是否该 retry/refresh)       │
│                                              │
│  ❌ 不做: 不选线 / 不调 Skill / 不控流程      │
└──────────────────┬───────────────────────────┘
                   │ 合法性咨询
                   ▼
┌──────────────────────────────────────────────┐
│  🚗 Orchestrator: "司机" (唯一流程控制者)     │
│                                              │
│  工作流程:                                    │
│  1. 决定 → 走 FAST PATH 还是 LLM PATH        │
│  2. 调 → State Machine 检查合法性            │
│  3. 执行 → 调用 Skill                        │
│  4. 记录 → decision_log                      │
│  5. 循环 → loop control                      │
└──────────────────┬───────────────────────────┘
                   │ 函数调用
                   ▼
┌──────────────────────────────────────────────┐
│  🦾 Skills: "手脚" (纯执行)                   │
│  - 7 个原子 Skill                             │
│  - 统一返回 SkillResult                       │
│  - 不做任何决策                                │
└──────────────────┬───────────────────────────┘
                   │ 使用 Resource Layer
                   ▼
┌──────────────────────────────────────────────┐
│  📦 Resource Layer: "工具箱" (⭐新增)         │
│  - ROI 配置注册表                             │
│  - 窗口管理                                   │
│  - 模板管理                                   │
│  - 截图工具                                   │
└──────────────────┬───────────────────────────┘
                   │ pyautogui/EasyOCR/OpenCV
                   ▼
┌──────────────────────────────────────────────┐
│  🖥️ GUI Automation Layer (基础设施)          │
└──────────────────────────────────────────────┘
```

---

## 4. Skill API 详细设计

### 4.1 统一接口

```python
from typing import TypedDict, Optional, Any

class SkillResult(TypedDict):
    success: bool                    # 是否成功
    data: Any                        # 结构化结果
    error: Optional[str]             # 错误描述
    duration_ms: int                 # 执行耗时
    screenshot: Optional[str]        # debug 截图路径

    # ⭐ 新增字段 - 增强可观测性
    confidence: float                # 置信度 0.0-1.0 (OCR/模板匹配)
    state: str                       # Skill 执行后的系统状态快照
```

### 4.2 核心数据结构

```python
from dataclasses import dataclass
from typing import Optional, Tuple, Literal

@dataclass
class CandidateLine:
    id: int                           # 1-based 编号
    type: Literal["FREE", "PERMANENT_FREE", "PAID"]
    roi: Tuple[int, int, int, int]    # 线路卡 ROI
    center_x: int                     # 点击 X
    center_y: int                     # 点击 Y
    percent: Optional[int]            # OCR 百分比
    status: Literal["AVAILABLE", "FULL", "UNKNOWN"]

    @property
    def is_eligible(self) -> bool:
        return self.type in ("FREE", "PERMANENT_FREE")

    @property
    def is_available(self) -> bool:
        return self.is_eligible and self.status == "AVAILABLE"
```

### 4.3 Skill 清单 (7 个)

**SKILL-01: skill_get_candidate_lines**
- 输入: page_region (可选)
- 输出: SkillResult[List[CandidateLine]]
- 逻辑: 扫描 badge → 按 Y 去重 → 排除 PAID → 计算 ROI
- 耗时: ~1-2s | 纯 Python, 不调 LLM

**SKILL-02: skill_read_percent**
- 输入: line_roi
- 输出: SkillResult[Optional[int]]
- 逻辑: 缓存检查 → 截图 ROI → EasyOCR 多策略 → 解析数字
- 耗时: ~0.5-1.5s | 纯 Python, 不调 LLM

**SKILL-03: skill_connect_line**
- 输入: 无
- 输出: SkillResult[bool]
- 逻辑: ESC → 等待 → change_line_button → 等待 → badge 确认
- 耗时: ~6-8s | 纯 Python, 不调 LLM

**SKILL-07: skill_capture_roi**
- 输入: roi
- 输出: SkillResult[np.ndarray]
- 逻辑: 截图 → OpenCV 预处理
- 耗时: ~0.2s | 纯 Python, 不调 LLM

---

## 5. Agent 编排流程

### 5.1 主循环设计

```
while True:
    1. detect_ui_state()        # 检测 UI 状态 (State Machine)
    2. if POPUP → close_popup()
    3. if CONNECTED → return
    4. if UNKNOWN → ESC
    5. if MAIN/LINE_PAGE:
       a. build_context()
       b. FAST PATH → try_fast_path()       # ⭐ 纯Python, 不调LLM
       c. if 快速路径失败 → LLM PATH → llm.decide()  # ⭐ 串行, 非混合
       d. execute_decision()
       e. handle_result()
```

### 5.2 快速路径优化 — 串行结构 (非混合触发)

**设计原则: FAST PATH 优先, 失败后再进入 LLM PATH**

```
进入线路页
    │
    ▼
FAST PATH (纯Python规则) ← 覆盖 50-70% 场景
    │
    ├── 成功 → 连接线路
    │
    └── 失败 →
         │
         ▼
    LLM PATH (策略选择) ← 仅覆盖 30-50% 场景
         │
         ├── 成功 → 连接线路
         │
         └── 失败 → State Machine 接管恢复
```

**快速路径条件:**
1. 只有 1 条可用线路 → 直接连接 (无需 LLM)
2. 多条线路且有明确的 PERMANENT_FREE 可用 → 直接选 (规则确定)
3. 没有可用线路 → 直接 retry_scan (无需 LLM)
4. 历史中有同线路近期成功记录 → 复用 (无需 LLM)

### 5.3 LLM 决策上下文

```json
{
    "task": "select_best_line",
    "lines": [
        {"id": 1, "type": "FREE", "percent": 45, "status": "AVAILABLE"},
        {"id": 2, "type": "PERMANENT_FREE", "percent": 80, "status": "AVAILABLE"},
        {"id": 3, "type": "FREE", "percent": 100, "status": "FULL"}
    ],
    "rules": {
        "priority": ["PERMANENT_FREE", "FREE"],
        "full_threshold": 100
    },
    "history": [
        {"line_id": 2, "result": "connection_timeout"}
    ]
}
```

### 5.4 LLM 响应格式 (严格限定为策略选择)

```json
{
    "choice": "PERMANENT_FREE",
    "strategy": "try_best",
    "retry_mode": "soft_once",
    "reason": "PERMANENT_FREE 45% 比 FREE 80% 优先级更高"
}
```

**LLM 输出字段说明:**

| 字段 | 可选值 | 含义 |
|------|--------|------|
| choice | "PERMANENT_FREE" / "FREE" / "any" | 选择哪类线路 |
| strategy | "try_best" / "try_best_three" / "any_available" | 选择策略 |
| retry_mode | "soft_once" / "retry_all" / "refresh_after_fail" | 重试策略 |
| reason | 简短文字 | LLM 推理过程 (用于 debug) |

**⚠️ LLM 绝对不可以输出:**
- ❌ 决定是否 refresh → 这是 State Machine 的责任
- ❌ 决定循环结构 → 这是 Orchestrator 的责任
- ❌ 决定流程跳转 → 这是 State Machine 的责任
- ❌ 包含坐标/ROI → 这是 Skills 的内部实现

State Machine 根据 LLM 策略 + 当前 failure counter 自行决定后续动作:
- soft_once → 失败后重试同线路 1 次
- retry_all → 尝试所有可用线路
- refresh_after_fail → 连续失败 2 次后自动刷新页面

---

## 6. ROI + OCR Pipeline

### 6.1 Badge → Line ROI 展开

```
Badge 匹配区域:
┌──────────────────┐
│ [永久用户]       │  ← badge (x, y, w, h)
└──────────────────┘
        │ EXPAND_RIGHT=400, EXPAND_BOTTOM=40
        ▼
┌──────────────────────────────────────┐
│ [永久用户] ████████████████ 45%     │  ← line ROI
└──────────────────────────────────────┘
                          │ OCR 子区域
                          ▼
                ┌──────────────────┐
                │     45%          │ (x+250, y+5, 120, 30)
                └──────────────────┘
```

### 6.2 EasyOCR Pipeline

```python
class OCRPipeline:
    def read_percent(self, roi) -> Optional[int]:
        # 1. 缓存检查 (3s TTL)
        # 2. lazy init EasyOCR
        # 3. 截图 ROI
        # 4. 多策略: raw / thresh / invert
        # 5. 解析数字 0-100
        # 6. 更新缓存
        pass
```

优点:
- 只识别数字 (allowlist='0123456789%')，精度高
- 多策略容错
- OCR 缓存减少重复调用

---

## 7. 状态管理策略

### 7.1 三层状态体系

**Level 1: UI 物理状态 (Python)**
- POPUP → popup_close.png 匹配
- MAIN → change_line_button.png 匹配
- LINE_PAGE → badge 匹配
- CONNECTED → connected_status.png 匹配
- UNKNOWN

**Level 2: Agent 逻辑状态 (Orchestrator)**
- IDLE / SCANNING / DECIDING / CONNECTING / VERIFYING / RECOVERING

**Level 3: Session 持久状态 (JSON 文件)**
- 今日连接次数、各线路失败历史、Token 消耗统计

### 7.2 反循环策略

- 同一位置最多点击 3 次
- 连续 3 次连接失败 → 刷新页面
- 成功连接后重置计数器
- session 持久化避免跨轮次重复

---

## 8. 降低 GUI 自动化脆弱性的 7 条原则

**原则 1: 优先识别"结构不变"的元素**
- 图标 (badge) > 文字 > 位置
- 永远不要依赖 XY 坐标

**原则 2: 使用 ROI 展开而非精确匹配**
- Badge ROI + 固定偏移 → 线路卡区域
- 即使 UI 微调, ROI 展开仍有效

**原则 3: OCR 读数字, 不读文字**
- 数字识别率远高于中文
- allowlist=['0123456789%'] 大幅提高精度

**原则 4: 每个 Skill 独立可测试**
- 一个 Skill 崩了不影响其他
- 可单独调试 + 验证

**原则 5: 快速失败 + 优雅降级**
- OCR 失败 → 重试 2 次 → 标记 UNKNOWN
- 连接失败 → 尝试下一条 → 刷新 → 放弃

**原则 6: Debug 可视化**
- 每次关键操作自动截图
- 标注 ROI/点击/识别结果
- 便于事后分析失败原因

**原则 7: 配置集中管理**
- ROI 偏移量、等待时间、阈值全部集中
- 修改配置即可适配 UI 变化
- 无需修改代码

---

## 9. Token 成本控制策略

### 9.1 三层成本控制

```
Layer 1: 减少调用次数
  ├── 快速路径: 30-50% 场景不调 LLM
  ├── OCR 缓存: 同一 ROI 3 秒内复用
  └── 状态聚合: 多条线路合并请求

Layer 2: 减少每次的 token
  ├── 只传 essential 字段 (省略坐标/ROI)
  ├── 历史只传最近 3 条
  ├── 使用简短 field name (id/type/percent)
  └── 严格 system prompt 控制输出格式

Layer 3: 选择低成本模型
  ├── 首选: Gemini 2.0 Flash (免费层)
  ├── 次选: DeepSeek-V3 (极低成本)
  └── 备选: OpenRouter 路由到最低价
```

### 9.2 预估成本

| 模型 | 每百万 token | 每次决策 token | 每天 100 次 | 月成本 |
|------|-------------|----------------|-------------|--------|
| Gemini 2.0 Flash | 免费 | ~300 | 0 | $0 |
| DeepSeek-V3 | ~$0.5 | ~300 | ~$0.015 | ~$0.45 |
| GPT-4o-mini | ~$0.15 | ~300 | ~$0.0045 | ~$0.14 |

结论: **月成本 < $1**, 完全可以接受。

---

## 10. 系统稳定性保障

### 10.1 健康检查机制

- 每次循环开始检查 VPN 窗口是否存在
- 超过 60 秒无进展 → 触发恢复流程
- 连续 5 次 LLM 调用失败 → 降级到纯 Python 模式

### 10.2 日志与监控

```
logs/
├── agent.log              # Agent 主日志
├── skill_calls.log        # Skill 调用记录
├── llm_decisions.log      # LLM 决策历史
├── errors.log             # 错误日志
└── token_usage.log        # Token 使用统计
```

### 10.3 降级策略

```
正常模式: LLM + Skills
  ↓ LLM API 不可用
降级模式: 纯 Python 规则引擎 (if-else 兜底)
  ↓ 连续失败
安全模式: 停止执行 + 通知用户
```

---

## 11. 与 VSCode 协作方式

### 11.1 角色分离

**VSCode 只负责:**
- 编写和调试 Skill 代码
- 调整 ROI 配置参数
- 查看日志和 debug 截图
- 修改模板图片

**Python Agent 负责:**
- 运行自动化流程
- 调用 LLM API
- 执行 Skill 操作 GUI
- 记录日志和统计

### 11.2 开发流程

```
VSCode 中开发:
  1. 修改 Skill 代码
  2. 运行 test_skill.py 验证
  3. 调整 ROI 配置
  4. 查看 agent.log

终端运行:
  1. python agent_main.py
  2. Agent 接管自动化流程
  3. 实时输出日志
  4. 生成 debug 截图到 debug_output/
```

---

## 12. 低成本运行方案

| 资源 | 方案 | 成本 |
|------|------|------|
| LLM 模型 | Gemini 2.0 Flash (免费) | $0 |
| OCR | EasyOCR (本地, CPU 模式) | 免费 |
| GUI 自动化 | pyautogui + OpenCV | 免费 |
| 运行环境 | Windows 本地 | 已有 |
| 模板匹配 | OpenCV template matching | 免费 |

**总成本: 仅 LLM API 费用, 每月 < $1**

---

## 13. 项目文件结构

```
vpn_automation/
├── agent/                    # Agent 层
│   ├── __init__.py
│   ├── orchestrator.py       # 主循环编排
│   ├── context_builder.py    # LLM 上下文构建
│   └── decision_parser.py    # LLM 响应解析
├── skills/                   # Skill 层 (7 个 skill)
│   ├── __init__.py
│   ├── base.py              # SkillResult 基类
│   ├── get_candidate_lines.py
│   ├── read_percent.py      # EasyOCR 封装
│   ├── connect_line.py
│   ├── check_connected.py
│   ├── close_popup.py
│   ├── refresh_page.py
│   └── capture_roi.py
├── llm/                      # LLM 客户端
│   ├── __init__.py
│   └── client.py            # Gemini/DeepSeek API 封装
├── config/                   # 配置
│   ├── __init__.py
│   ├── settings.py          # 系统配置
│   └── roi_config.py        # ROI 参数集中管理
├── templates/                # 保留的模板
│   ├── badges/
│   ├── buttons/
│   ├── popup/
│   └── status/
├── utils/                    # 工具
│   ├── __init__.py
│   ├── logger.py
│   ├── window.py            # 窗口管理
│   └── debug.py             # debug 截图
├── tests/                    # 测试
│   ├── test_skill_badge.py
│   ├── test_skill_ocr.py
│   └── test_agent_flow.py
├── logs/                     # 日志
├── debug_output/             # debug 截图
├── requirements.txt
├── agent_main.py             # 入口文件
└── ARCHITECTURE_REDESIGN.md  # 本文档
```

---

## 14. 迁移路线图

### Phase 1: 基础设施 (1-2 天)
1. 创建新项目结构 (agent/ skills/ llm/ config/ utils/)
2. 实现 SkillResult 基类和异常体系
3. 实现 config 和 ROI 配置
4. 安装 EasyOCR + 验证

### Phase 2: Skill 实现 (2-3 天)
1. skill_capture_roi + skill_check_connected (复用现有模板)
2. skill_get_candidate_lines (badge 扫描 + ROI 展开)
3. skill_read_percent (EasyOCR pipeline)
4. skill_connect_line + skill_close_popup (迁移现有代码)
5. skill_refresh_page

### Phase 3: Agent 编排 (2 天)
1. LLM 客户端封装 (Gemini/DeepSeek API)
2. Context builder + Decision parser
3. 主循环 orchestration
4. 快速路径优化

### Phase 4: 集成与测试 (1-2 天)
1. 端到端流程测试
2. Token 成本监控
3. 异常恢复测试
4. 旧代码清理

### Phase 5: 优化 (持续)
1. 根据实际表现调整 ROI 参数
2. 优化 Prompt 减少 token
3. 添加更多快速路径条件

---

## 15. Decision Log — 所有决策必须可回放 (⭐新增)

这是防止系统进入"不可演化阶段"的关键设计。

### 15.1 为什么需要 Decision Log

```
没有 decision_log 的系统:
  运行 100 次 → 行为不可追溯 → 出现问题无法复现 → 最终不敢更新代码

有 decision_log 的系统:
  运行 100 次 → 每条决策可回放 → 问题精准定位 → 持续安全演进
```

### 15.2 decision_log.json 格式

```json
{
    "timestamp": "2026-05-10T10:30:00",
    "session_id": "session_001",
    "step_id": 42,
    
    "ui_state": "LINE_PAGE",
    "lines_input": [
        {"id": 1, "type": "FREE", "percent": 45, "status": "AVAILABLE"},
        {"id": 2, "type": "PERMANENT_FREE", "percent": 100, "status": "FULL"},
        {"id": 3, "type": "PAID", "percent": null, "status": "UNKNOWN"}
    ],

    "path_taken": "fast_path",        // "fast_path" | "llm_path" | "recovery"
    
    "llm_request": null,               // 如果走了 LLM 路径
    "llm_response": null,              // LLM 输出

    "final_action": {
        "skill": "skill_connect_line",
        "line_id": 1,
        "result": "success"
    },
    
    "duration_ms": 8432,
    "errors": []
}
```

### 15.3 设计原则

- **每步必记**: 每个循环迭代都记录一条
- **输入完整**: 记录 LLM 看到的完整上下文 (不省略)
- **输出准确**: 记录最终执行的动作和结果
- **可回放**: 用 decision_log.json 可以完全重现当时场景

### 15.4 解决的问题

- LLM 输出不稳定 → 可复现分析
- 系统行为异常 → 可追溯根因
- UI 变化影响评估 → 可对比历史 logs
- 新增 Skill 是否可靠 → 可在历史数据上验证

---

## 附录: 关键设计决策汇总

| 决策 | 选择 | 理由 |
|------|------|------|
| Agent 部署方式 | Python Agent (非 VSCode 扩展) | 稳定、可控、长流程 |
| OCR 引擎 | EasyOCR (替代 Tesseract) | 精度更高、安装简单 |
| PAID 识别 | 排除法 (badge 识别) | 最稳定、无需额外模板 |
| 连接验证 | 保留 template matching | 此场景 template 更可靠 |
| 刷新定义 | ESC → 重进线路页 | 简单、可靠 |
| 模板保留 | badge/button/popup/status | 稳定的结构元素 |
| 模板废弃 | line_aa1/aa2/aa3 + full/available | 位置依赖 + 动态变化 |
| LLM 模型 | Gemini 2.0 Flash (首选) | 免费、速度快、够用 |**SKILL-06: skill_refresh_page**
- 输入: 无
- 输出: SkillResult[bool]
- 逻辑: ESC → 等待 → change_line_button → 等待 → badge 确认
- 耗时: ~6-8s | 纯 Python, 不调 LLM

**SKILL-07: skill_capture_roi**
- 输入: roi
- 输出: SkillResult[np.ndarray]
- 逻辑: 截图 → OpenCV 预处理
- 耗时: ~0.2s | 纯 Python, 不调 LLM

---

## 5. Agent 编排流程

### 5.1 主循环设计

```
while True:
    1. detect_ui_state()        # 检测 UI 状态 (State Machine)
    2. if POPUP → close_popup()
    3. if CONNECTED → return
    4. if UNKNOWN → ESC
    5. if MAIN/LINE_PAGE:
       a. build_context()
       b. FAST PATH → try_fast_path()       # ⭐ 纯Python, 不调LLM
       c. if 快速路径失败 → LLM PATH → llm.decide()  # ⭐ 串行, 非混合
       d. execute_decision()
       e. handle_result()
```

### 5.2 快速路径优化 — 串行结构 (非混合触发)

**设计原则: FAST PATH 优先, 失败后再进入 LLM PATH**

```
进入线路页
    │
    ▼
FAST PATH (纯Python规则) ← 覆盖 50-70% 场景
    │
    ├── 成功 → 连接线路
    │
    └── 失败 →
         │
         ▼
    LLM PATH (策略选择) ← 仅覆盖 30-50% 场景
         │
         ├── 成功 → 连接线路
         │
         └── 失败 → State Machine 接管恢复
```

**快速路径条件:**
1. 只有 1 条可用线路 → 直接连接 (无需 LLM)
2. 多条线路且有明确的 PERMANENT_FREE 可用 → 直接选 (规则确定)
3. 没有可用线路 → 直接 retry_scan (无需 LLM)
4. 历史中有同线路近期成功记录 → 复用 (无需 LLM)

### 5.3 LLM 决策上下文

```json
{
    "task": "select_best_line",
    "lines": [
        {"id": 1, "type": "FREE", "percent": 45, "status": "AVAILABLE"},
        {"id": 2, "type": "PERMANENT_FREE", "percent": 80, "status": "AVAILABLE"},
        {"id": 3, "type": "FREE", "percent": 100, "status": "FULL"}
    ],
    "rules": {
        "priority": ["PERMANENT_FREE", "FREE"],
        "full_threshold": 100
    },
    "history": [
        {"line_id": 2, "result": "connection_timeout"}
    ]
}
```

### 5.4 LLM 响应格式 (严格限定为策略选择)

```json
{
    "choice": "PERMANENT_FREE",
    "strategy": "try_best",
    "retry_mode": "soft_once",
    "reason": "PERMANENT_FREE 45% 比 FREE 80% 优先级更高"
}
```

**LLM 输出字段说明:**

| 字段 | 可选值 | 含义 |
|------|--------|------|
| choice | "PERMANENT_FREE" / "FREE" / "any" | 选择哪类线路 |
| strategy | "try_best" / "try_best_three" / "any_available" | 选择策略 |
| retry_mode | "soft_once" / "retry_all" / "refresh_after_fail" | 重试策略 |
| reason | 简短文字 | LLM 推理过程 (用于 debug) |

**⚠️ LLM 绝对不可以输出:**
- ❌ 决定是否 refresh → 这是 State Machine 的责任
- ❌ 决定循环结构 → 这是 Orchestrator 的责任
- ❌ 决定流程跳转 → 这是 State Machine 的责任
- ❌ 包含坐标/ROI → 这是 Skills 的内部实现

State Machine 根据 LLM 策略 + 当前 failure counter 自行决定后续动作:
- soft_once → 失败后重试同线路 1 次
- retry_all → 尝试所有可用线路
- refresh_after_fail → 连续失败 2 次后自动刷新页面

---

## 6. ROI + OCR Pipeline

### 6.1 Badge → Line ROI 展开

```
Badge 匹配区域:
┌──────────────────┐
│ [永久用户]       │  ← badge (x, y, w, h)
└──────────────────┘
        │ EXPAND_RIGHT=400, EXPAND_BOTTOM=40
        ▼
┌──────────────────────────────────────┐
│ [永久用户] ████████████████ 45%     │  ← line ROI
└──────────────────────────────────────┘
                          │ OCR 子区域
                          ▼
                ┌──────────────────┐
                │     45%          │ (x+250, y+5, 120, 30)
                └──────────────────┘
```

### 6.2 EasyOCR Pipeline

```python
class OCRPipeline:
    def read_percent(self, roi) -> Optional[int]:
        # 1. 缓存检查 (3s TTL)
        # 2. lazy init EasyOCR
        # 3. 截图 ROI
        # 4. 多策略: raw / thresh / invert
        # 5. 解析数字 0-100
        # 6. 更新缓存
        pass
```

优点:
- 只识别数字 (allowlist='0123456789%')，精度高
- 多策略容错
- OCR 缓存减少重复调用

---

## 7. 状态管理策略

### 7.1 三层状态体系

**Level 1: UI 物理状态 (Python)**
- POPUP → popup_close.png 匹配
- MAIN → change_line_button.png 匹配
- LINE_PAGE → badge 匹配
- CONNECTED → connected_status.png 匹配
- UNKNOWN

**Level 2: Agent 逻辑状态 (Orchestrator)**
- IDLE / SCANNING / DECIDING / CONNECTING / VERIFYING / RECOVERING

**Level 3: Session 持久状态 (JSON 文件)**
- 今日连接次数、各线路失败历史、Token 消耗统计

### 7.2 反循环策略

- 同一位置最多点击 3 次
- 连续 3 次连接失败 → 刷新页面
- 成功连接后重置计数器
- session 持久化避免跨轮次重复

---

## 8. 降低 GUI 自动化脆弱性的 7 条原则

**原则 1: 优先识别"结构不变"的元素**
- 图标 (badge) > 文字 > 位置
- 永远不要依赖 XY 坐标

**原则 2: 使用 ROI 展开而非精确匹配**
- Badge ROI + 固定偏移 → 线路卡区域
- 即使 UI 微调, ROI 展开仍有效

**原则 3: OCR 读数字, 不读文字**
- 数字识别率远高于中文
- allowlist=['0123456789%'] 大幅提高精度

**原则 4: 每个 Skill 独立可测试**
- 一个 Skill 崩了不影响其他
- 可单独调试 + 验证

**原则 5: 快速失败 + 优雅降级**
- OCR 失败 → 重试 2 次 → 标记 UNKNOWN
- 连接失败 → 尝试下一条 → 刷新 → 放弃

**原则 6: Debug 可视化**
- 每次关键操作自动截图
- 标注 ROI/点击/识别结果
- 便于事后分析失败原因

**原则 7: 配置集中管理**
- ROI 偏移量、等待时间、阈值全部集中
- 修改配置即可适配 UI 变化
- 无需修改代码

---

## 9. Token 成本控制策略

### 9.1 三层成本控制

```
Layer 1: 减少调用次数
  ├── 快速路径: 30-50% 场景不调 LLM
  ├── OCR 缓存: 同一 ROI 3 秒内复用
  └── 状态聚合: 多条线路合并请求

Layer 2: 减少每次的 token
  ├── 只传 essential 字段 (省略坐标/ROI)
  ├── 历史只传最近 3 条
  ├── 使用简短 field name (id/type/percent)
  └── 严格 system prompt 控制输出格式

Layer 3: 选择低成本模型
  ├── 首选: Gemini 2.0 Flash (免费层)
  ├── 次选: DeepSeek-V3 (极低成本)
  └── 备选: OpenRouter 路由到最低价
```

### 9.2 预估成本

| 模型 | 每百万 token | 每次决策 token | 每天 100 次 | 月成本 |
|------|-------------|----------------|-------------|--------|
| Gemini 2.0 Flash | 免费 | ~300 | 0 | $0 |
| DeepSeek-V3 | ~$0.5 | ~300 | ~$0.015 | ~$0.45 |
| GPT-4o-mini | ~$0.15 | ~300 | ~$0.0045 | ~$0.14 |

结论: **月成本 < $1**, 完全可以接受。

---

## 10. 系统稳定性保障

### 10.1 健康检查机制

- 每次循环开始检查 VPN 窗口是否存在
- 超过 60 秒无进展 → 触发恢复流程
- 连续 5 次 LLM 调用失败 → 降级到纯 Python 模式

### 10.2 日志与监控

```
logs/
├── agent.log              # Agent 主日志
├── skill_calls.log        # Skill 调用记录
├── llm_decisions.log      # LLM 决策历史
├── errors.log             # 错误日志
└── token_usage.log        # Token 使用统计
```

### 10.3 降级策略

```
正常模式: LLM + Skills
  ↓ LLM API 不可用
降级模式: 纯 Python 规则引擎 (if-else 兜底)
  ↓ 连续失败
安全模式: 停止执行 + 通知用户
```

---

## 11. 与 VSCode 协作方式

### 11.1 角色分离

**VSCode 只负责:**
- 编写和调试 Skill 代码
- 调整 ROI 配置参数
- 查看日志和 debug 截图
- 修改模板图片

**Python Agent 负责:**
- 运行自动化流程
- 调用 LLM API
- 执行 Skill 操作 GUI
- 记录日志和统计

### 11.2 开发流程

```
VSCode 中开发:
  1. 修改 Skill 代码
  2. 运行 test_skill.py 验证
  3. 调整 ROI 配置
  4. 查看 agent.log

终端运行:
  1. python agent_main.py
  2. Agent 接管自动化流程
  3. 实时输出日志
  4. 生成 debug 截图到 debug_output/
```

---

## 12. 低成本运行方案

| 资源 | 方案 | 成本 |
|------|------|------|
| LLM 模型 | Gemini 2.0 Flash (免费) | $0 |
| OCR | EasyOCR (本地, CPU 模式) | 免费 |
| GUI 自动化 | pyautogui + OpenCV | 免费 |
| 运行环境 | Windows 本地 | 已有 |
| 模板匹配 | OpenCV template matching | 免费 |

**总成本: 仅 LLM API 费用, 每月 < $1**

---

## 13. 项目文件结构

```
vpn_automation/
├── agent/                    # Agent 层
│   ├── __init__.py
│   ├── orchestrator.py       # 主循环编排
│   ├── context_builder.py    # LLM 上下文构建
│   └── decision_parser.py    # LLM 响应解析
├── skills/                   # Skill 层 (7 个 skill)
│   ├── __init__.py
│   ├── base.py              # SkillResult 基类
│   ├── get_candidate_lines.py
│   ├── read_percent.py      # EasyOCR 封装
│   ├── connect_line.py
│   ├── check_connected.py
│   ├── close_popup.py
│   ├── refresh_page.py
│   └── capture_roi.py
├── llm/                      # LLM 客户端
│   ├── __init__.py
│   └── client.py            # Gemini/DeepSeek API 封装
├── config/                   # 配置
│   ├── __init__.py
│   ├── settings.py          # 系统配置
│   └── roi_config.py        # ROI 参数集中管理
├── templates/                # 保留的模板
│   ├── badges/
│   ├── buttons/
│   ├── popup/
│   └── status/
├── utils/                    # 工具
│   ├── __init__.py
│   ├── logger.py
│   ├── window.py            # 窗口管理
│   └── debug.py             # debug 截图
├── tests/                    # 测试
│   ├── test_skill_badge.py
│   ├── test_skill_ocr.py
│   └── test_agent_flow.py
├── logs/                     # 日志
├── debug_output/             # debug 截图
├── requirements.txt
├── agent_main.py             # 入口文件
└── ARCHITECTURE_REDESIGN.md  # 本文档
```

---

## 14. 迁移路线图

### Phase 1: 基础设施 (1-2 天)
1. 创建新项目结构 (agent/ skills/ llm/ config/ utils/)
2. 实现 SkillResult 基类和异常体系
3. 实现 config 和 ROI 配置
4. 安装 EasyOCR + 验证

### Phase 2: Skill 实现 (2-3 天)
1. skill_capture_roi + skill_check_connected (复用现有模板)
2. skill_get_candidate_lines (badge 扫描 + ROI 展开)
3. skill_read_percent (EasyOCR pipeline)
4. skill_connect_line + skill_close_popup (迁移现有代码)
5. skill_refresh_page

### Phase 3: Agent 编排 (2 天)
1. LLM 客户端封装 (Gemini/DeepSeek API)
2. Context builder + Decision parser
3. 主循环 orchestration
4. 快速路径优化

### Phase 4: 集成与测试 (1-2 天)
1. 端到端流程测试
2. Token 成本监控
3. 异常恢复测试
4. 旧代码清理

### Phase 5: 优化 (持续)
1. 根据实际表现调整 ROI 参数
2. 优化 Prompt 减少 token
3. 添加更多快速路径条件

---

## 15. Decision Log — 所有决策必须可回放 (⭐新增)

这是防止系统进入"不可演化阶段"的关键设计。

### 15.1 为什么需要 Decision Log

```
没有 decision_log 的系统:
  运行 100 次 → 行为不可追溯 → 出现问题无法复现 → 最终不敢更新代码

有 decision_log 的系统:
  运行 100 次 → 每条决策可回放 → 问题精准定位 → 持续安全演进
```

### 15.2 decision_log.json 格式

```json
{
    "timestamp": "2026-05-10T10:30:00",
    "session_id": "session_001",
    "step_id": 42,
    
    "ui_state": "LINE_PAGE",
    "lines_input": [
        {"id": 1, "type": "FREE", "percent": 45, "status": "AVAILABLE"},
        {"id": 2, "type": "PERMANENT_FREE", "percent": 100, "status": "FULL"},
        {"id": 3, "type": "PAID", "percent": null, "status": "UNKNOWN"}
    ],

    "path_taken": "fast_path",        // "fast_path" | "llm_path" | "recovery"
    
    "llm_request": null,               // 如果走了 LLM 路径
    "llm_response": null,              // LLM 输出

    "final_action": {
        "skill": "skill_connect_line",
        "line_id": 1,
        "result": "success"
    },
    
    "duration_ms": 8432,
    "errors": []
}
```

### 15.3 设计原则

- **每步必记**: 每个循环迭代都记录一条
- **输入完整**: 记录 LLM 看到的完整上下文 (不省略)
- **输出准确**: 记录最终执行的动作和结果
- **可回放**: 用 decision_log.json 可以完全重现当时场景

### 15.4 解决的问题

- LLM 输出不稳定 → 可复现分析
- 系统行为异常 → 可追溯根因
- UI 变化影响评估 → 可对比历史 logs
- 新增 Skill 是否可靠 → 可在历史数据上验证

---

## 附录: 关键设计决策汇总

| 决策 | 选择 | 理由 |
|------|------|------|
| Agent 部署方式 | Python Agent (非 VSCode 扩展) | 稳定、可控、长流程 |
| OCR 引擎 | EasyOCR (替代 Tesseract) | 精度更高、安装简单 |
| PAID 识别 | 排除法 (badge 识别) | 最稳定、无需额外模板 |
| 连接验证 | 保留 template matching | 此场景 template 更可靠 |
| 刷新定义 | ESC → 重进线路页 | 简单、可靠 |
| 模板保留 | badge/button/popup/status | 稳定的结构元素 |
| 模板废弃 | line_aa1/aa2/aa3 + full/available | 位置依赖 + 动态变化 |
| LLM 模型 | Gemini 2.0 Flash (首选) | 免费、速度快、够用 |