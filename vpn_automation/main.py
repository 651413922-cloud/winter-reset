"""
VPN 自动选择最优免费线路 - MVP

流程:
1. 截图线路界面
2. 识别 FREE / PERMANENT_FREE 线路 badge
3. OCR 读取百分比，过滤 100% 满额
4. 选择百分比最低的线路 (PERMANENT_FREE 优先)
5. 点击连接
6. 验证连接成功 (connected_status.png)
7. 失败 → 返回 → 重试最多 3 次
"""

import time
import sys
from pathlib import Path
from typing import Optional

import pyautogui

# ── 导入项目基础设施 ──
sys.path.insert(0, str(Path(__file__).parent))
from config import TEMPLATE, CONF, WAIT
from matcher import locate, locate_all
from clicker import Clicker
from logger import Logger
from ocr_reader import read_percentage_from_roi as _read_percentage_from_roi


# ═══════════════════════════════════════════════
#  数据结构
# ═══════════════════════════════════════════════

class LineCard:
    """一条线路卡片"""
    def __init__(self, line_id: int, line_type: str, center_x: int, center_y: int, roi: tuple):
        self.id = line_id
        self.type = line_type              # "FREE" / "PERMANENT_FREE"
        self.center_x = center_x           # 点击 X 坐标
        self.center_y = center_y           # 点击 Y 坐标
        self.roi = roi                     # 线路卡片 ROI (left, top, w, h)
        self.percent: Optional[int] = None # OCR 百分比结果
        self.status: str = "UNKNOWN"       # "AVAILABLE" / "FULL"

    @property
    def is_available(self) -> bool:
        return self.type in ("FREE", "PERMANENT_FREE") and self.status == "AVAILABLE"

    def __repr__(self) -> str:
        return f"[{self.type}#{self.id} {self.percent}% {self.status}]"


# ═══════════════════════════════════════════════
#  Skill: 扫描线路 (badge → ROI → LineCard)
# ═══════════════════════════════════════════════

def _extend_to_line_roi(badge_box: tuple) -> tuple:
    """
    从 badge 的 bounding box 向右向下扩展，得到完整线路卡片区域。
    badge 在卡片左侧，卡片向右延伸约 400px，向下约 40px。
    """
    x, y, w, h = badge_box
    return (int(x), int(y), int(w + 350), int(h + 35))


def _line_card_center(line_roi: tuple) -> tuple[int, int]:
    """
    计算线路卡片的中心坐标（用于点击）。
    注意：是卡片区域中心，不是 badge 中心。
    """
    lx, ly, lw, lh = line_roi
    cx = lx + lw // 2
    cy = ly + lh // 2
    return (cx, cy)


def scan_lines() -> list[LineCard]:
    """
    扫描屏幕，识别 FREE / PERMANENT_FREE badge。
    通过 badge 位置展开得到完整线路 ROI。
    """
    lines = []

    # ── 1. 识别 FREE badge ──
    free_matches = locate_all(TEMPLATE["free_badge"], "free_badge",
                              confidence=CONF["badge"])
    for m in free_matches.matches:
        if m.box is None:
            continue
        line_roi = _extend_to_line_roi(m.box)
        cx, cy = _line_card_center(line_roi)
        lines.append(LineCard(
            line_id=0, line_type="FREE",
            center_x=cx, center_y=cy,
            roi=line_roi
        ))

    # ── 2. 识别 PERMANENT_FREE badge ──
    perm_matches = locate_all(TEMPLATE["permanent_badge"], "permanent_badge",
                              confidence=CONF["badge"])
    for m in perm_matches.matches:
        if m.box is None:
            continue
        line_roi = _extend_to_line_roi(m.box)
        cx, cy = _line_card_center(line_roi)
        lines.append(LineCard(
            line_id=0, line_type="PERMANENT_FREE",
            center_x=cx, center_y=cy,
            roi=line_roi
        ))

    # 按 Y 坐标排序 (从上到下)
    lines.sort(key=lambda l: l.roi[1])
    # 重新编号
    for i, line in enumerate(lines, 1):
        line.id = i

    Logger.info(f"[scan] 找到 {len(lines)} 条免费线路")
    return lines


# ═══════════════════════════════════════════════
#  Skill: OCR 读百分比
# ═══════════════════════════════════════════════

def read_percent(line: LineCard) -> Optional[int]:
    """
    对线路卡片的百分比区域截图 → OCR → 提取数字。
    使用 ocr_reader.read_percentage_from_roi (pytesseract 方案)。
    """
    return _read_percentage_from_roi(line.roi, line.id)


# ═══════════════════════════════════════════════
#  Skill: 进入线路页面
# ═══════════════════════════════════════════════

def click_change_line() -> bool:
    """
    点击「更换线路」按钮，进入线路选择页面。
    
    策略（防 ClearType 误匹配）：
    1. 对图标模板使用高置信度 (0.8)
    2. 点击后验证页面是否真的跳转
    3. 未跳转 → 判定为误点击，返回 False
    """
    # ── 1. 用高置信度查找按钮 ──
    #     ⚠️ 0.5 太低 → 容易匹配到其他文字
    #     ✅ 0.8 确保只匹配到真正的图标/按钮区域
    result = locate(TEMPLATE["change_line"], "change_line",
                    confidence=0.8)
    if not result.found or not result.center:
        Logger.warning("[nav] 未找到「更换线路」按钮 (conf=0.8)")
        # 降级尝试：用 0.6 再试一次（防止图标位置轻微变化）
        result = locate(TEMPLATE["change_line"], "change_line",
                        confidence=0.6)
        if not result.found or not result.center:
            Logger.error("[nav] 两次尝试均未找到按钮")
            return False
        Logger.info("[nav] 降级匹配成功 (conf=0.6)")

    cx, cy = result.center
    pyautogui.click(cx, cy)
    Logger.info(f"[nav] 点击「更换线路」 ({cx},{cy})")
    time.sleep(WAIT["medium"])

    # ── 2. 验证是否真的进入了线路选择页面 ──
    #     检测线路页面标题（例如「共享线路」区域）
    #     如果检测不到 → 说明误点击，立即返回 False
    if not _verify_on_line_page():
        Logger.error("[nav] 页面跳转验证失败 — 仍停留在原界面，取消本次重试")
        return False

    Logger.success("[nav] ✅ 已确认进入线路选择页面")
    return True


def _verify_on_line_page() -> bool:
    """
    验证当前是否在线路选择页面。
    
    策略：
    - 检测线路页面特有的 UI 元素（标题区域、列表容器等）
    - 使用多模版投票：只要任一模板匹配即认为成功
    - 每个模板单独用 0.7 置信度，避免误判
    """
    # 检测线路页面标题
    markers = [
        ("line_page_title", TEMPLATE.get("line_page_title"), 0.7),
    ]

    for name, tmpl_path, conf in markers:
        if not tmpl_path:
            continue
        if not Path(tmpl_path).exists():
            Logger.warning(f"[verify] 模板不存在: {tmpl_path}，跳过")
            continue
        result = locate(tmpl_path, name, confidence=conf)
        if result.found:
            Logger.info(f"[verify] ✅ 检测到线路页面标记: {name}")
            return True

    # ── fallback：用 free_badge 或 permanent_badge 也能判断 ──
    #     如果 badge 置信度 > 0.4，说明至少看到了线路卡片
    for badge_key in ["free_badge", "permanent_badge"]:
        tmpl_path = TEMPLATE.get(badge_key)
        if not tmpl_path:
            continue
        if not Path(tmpl_path).exists():
            continue
        result = locate(tmpl_path, badge_key, confidence=0.4)
        if result.found:
            Logger.info(f"[verify] ✅ 通过 {badge_key} 确认在线路页面")
            return True

    Logger.warning("[verify] ❌ 线路页面标记均未检测到")
    return False


# ═══════════════════════════════════════════════
#  Skill: 弹窗管理
# ═══════════════════════════════════════════════

def close_popup_if_present() -> bool:
    """检测弹窗关闭按钮 → 点击关闭"""
    result = locate(TEMPLATE["popup_close"], "popup_close",
                    confidence=CONF["popup"])
    if result.found and result.center:
        cx, cy = result.center
        pyautogui.click(cx, cy)
        Logger.info(f"[popup] 弹窗已关闭 ({cx},{cy})")
        time.sleep(WAIT["medium"])
        return True
    return False


# ═══════════════════════════════════════════════
#  Skill: 连接线路
# ═══════════════════════════════════════════════

def connect_line(line: LineCard, clicker: Clicker) -> bool:
    """点击线路中心，等待连接"""
    close_popup_if_present()

    if not clicker.click_card(line.center_x, line.center_y,
                              f"{line.type}_{line.id}"):
        Logger.error(f"[connect] 线路 #{line.id} 点击失败 (反循环保护)")
        return False

    Logger.info(f"[connect] 已点击 {line.type}#{line.id}，等待 {WAIT['connect']}s...")
    time.sleep(WAIT["connect"])

    close_popup_if_present()
    return True


# ═══════════════════════════════════════════════
#  Skill: 验证连接
# ═══════════════════════════════════════════════

def check_connected() -> bool:
    """检测 connected_status.png 是否出现"""
    close_popup_if_present()
    result = locate(TEMPLATE["connected"], "connected",
                    confidence=CONF["connected"])
    if result.found:
        Logger.success(f"[check] ✅ 连接成功")
        return True
    Logger.warning(f"[check] 未检测到连接状态")
    return False


# ═══════════════════════════════════════════════
#  Skill: 返回线路页
# ═══════════════════════════════════════════════

def go_back_to_lines() -> None:
    """按 ESC 返回线路页面"""
    pyautogui.press('esc')
    time.sleep(WAIT["medium"])
    Logger.info(f"[back] 已返回线路页")


# ═══════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════

def main():
    Logger.info("=" * 55)
    Logger.info("  VPN 自动最优免费线路选择系统 (MVP)")
    Logger.info("=" * 55)

    clicker = Clicker()
    MAX_RETRIES = 3

    for attempt in range(1, MAX_RETRIES + 1):
        Logger.info(f"\n{'─'*40}")
        Logger.info(f"  第 {attempt}/{MAX_RETRIES} 次尝试")
        Logger.info(f"{'─'*40}")

        # 0. 先消除弹窗干扰
        close_popup_if_present()

        # ── 1. 进入线路选择页面 ──
        Logger.info("[nav] 进入线路选择页面...")
        if not click_change_line():
            Logger.warning("[main] 无法进入线路页面，重试")
            time.sleep(WAIT["retry_gap"])
            continue
        time.sleep(WAIT["medium"])

        # ── 2. 扫描线路 ──
        lines = scan_lines()
        if not lines:
            Logger.warning("[main] 未检测到免费线路，重试")
            go_back_to_lines()
            time.sleep(WAIT["retry_gap"])
            continue

        # ── 2. 对每条线路做 OCR ──
        for line in lines:
            percent = read_percent(line)
            if percent is not None:
                line.percent = percent
                line.status = "AVAILABLE" if percent < 100 else "FULL"
            Logger.info(f"  → {line}")

        # ── 3. 过滤可用线路 ──
        available = [l for l in lines if l.is_available]
        if not available:
            Logger.warning("[main] 没有可用线路 (全部满额/识别失败)")
            go_back_to_lines()
            time.sleep(WAIT["retry_gap"])
            continue

        # ── 4. 选择最佳线路 ──
        #    优先级: PERMANENT_FREE > FREE
        #    同类型: 百分比最低的优先
        available.sort(key=lambda l: (
            0 if l.type == "PERMANENT_FREE" else 1,
            l.percent if l.percent is not None else 999
        ))

        best = available[0]
        Logger.info(f"\n[select] 最佳线路: {best.type}#{best.id} ({best.percent}%)")

        # ── 5. 连接 ──
        if not connect_line(best, clicker):
            Logger.error(f"[main] 连接失败")
            go_back_to_lines()
            time.sleep(WAIT["retry_gap"])
            continue

        # ── 6. 验证 ──
        if check_connected():
            Logger.success(f"\n{'='*55}")
            Logger.success(f"  ✅ 成功连接 {best.type}#{best.id} ({best.percent}%)")
            Logger.success(f"{'='*55}")
            return True

        # ── 7. 失败 → 继续重试 ──
        Logger.warning(f"[main] 连接验证未通过，准备第 {attempt+1} 次重试")
        go_back_to_lines()
        time.sleep(WAIT["retry_gap"])

    Logger.error(f"\n❌ 超过 {MAX_RETRIES} 次重试，脚本结束")
    return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
