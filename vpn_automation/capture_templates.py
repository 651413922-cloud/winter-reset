"""
交互式模板重截图工具。

用法：
  python vpn_automation/capture_templates.py

流程：
1. 程序截取全屏并显示
2. 你用鼠标框选目标区域（图标/badge）
3. 保存为新模板，替换旧文件
"""

import cv2
import pyautogui
import numpy as np
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"

# ── 需要重新截图的模板 ──
TARGETS = [
    {
        "name": "change_line_button.png",
        "path": TEMPLATES_DIR / "buttons" / "change_line_button.png",
        "hint": "截取「更换线路」左侧的蓝色折叠地图图标（不要带文字）",
    },
    {
        "name": "free_badge.png",
        "path": TEMPLATES_DIR / "badges" / "free_badge.png",
        "hint": "截取 FREE 标签（纯图标，不要带背景进度条）",
    },
    {
        "name": "permanent_badge.png",
        "path": TEMPLATES_DIR / "badges" / "permanent_badge.png",
        "hint": "截取 PERMANENT_FREE 标签（纯图标）",
    },
]

def select_roi(full_img: np.ndarray, hint: str) -> tuple:
    """
    打开 OpenCV 窗口让用户框选区域。
    返回 (left, top, width, height)
    按 'r' 重置选择, 按 ESC 跳过, 按 SPACE/ENTER 确认。
    """
    disp = full_img.copy()
    roi: tuple | None = None
    selecting = False
    x0 = y0 = 0

    def mouse_cb(event, x, y, flags, param):
        nonlocal roi, selecting, x0, y0, disp
        if event == cv2.EVENT_LBUTTONDOWN:
            selecting = True
            x0, y0 = x, y
        elif event == cv2.EVENT_MOUSEMOVE and selecting:
            disp = full_img.copy()
            cv2.rectangle(disp, (x0, y0), (x, y), (0, 255, 0), 2)
        elif event == cv2.EVENT_LBUTTONUP:
            selecting = False
            x1, y1 = x, y
            left = min(x0, x1)
            top = min(y0, y1)
            w = abs(x1 - x0)
            h = abs(y1 - y0)
            if w > 10 and h > 10:
                roi = (left, top, w, h)
                cv2.rectangle(disp, (left, top), (left + w, top + h), (0, 255, 0), 2)

    cv2.namedWindow("Capture", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Capture", 1920 // 2, 1080 // 2)
    cv2.setMouseCallback("Capture", mouse_cb)

    print(f"\n{'='*60}")
    print(f"  模板: {hint}")
    print(f"{'='*60}")
    print("  操作说明:")
    print("    - 鼠标拖拽框选目标区域")
    print("    - 按 SPACE 或 ENTER → 确认并保存")
    print("    - 按 R → 重新选择")
    print("    - 按 ESC → 跳过此模板")
    print(f"{'='*60}\n")

    while True:
        cv2.imshow("Capture", disp)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:  # ESC
            cv2.destroyWindow("Capture")
            return None
        if key in (13, 32):  # ENTER or SPACE
            if roi is not None:
                cv2.destroyWindow("Capture")
                return roi
            print("  提示: 请先拖拽框选区域!")
        if key == ord('r'):
            roi = None
            disp = full_img.copy()
            print("  已重置选择")

    cv2.destroyWindow("Capture")
    return None


def main():
    print("=" * 60)
    print("  模板重截图工具")
    print("=" * 60)
    for t in TARGETS:
        if not t["path"].parent.exists():
            t["path"].parent.mkdir(parents=True, exist_ok=True)

    for i, target in enumerate(TARGETS, 1):
        print(f"\n[{i}/{len(TARGETS)}] {target['name']}")

        # 1. 截图
        print("  正在截取全屏...")
        screenshot = pyautogui.screenshot()
        full_img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

        # 2. 让用户框选
        roi = select_roi(full_img, target["hint"])
        if roi is None:
            print("  ⏭ 已跳过")
            continue

        left, top, w, h = roi
        crop = full_img[top:top+h, left:left+w]

        # 3. 保存
        cv2.imwrite(str(target["path"]), crop)
        print(f"  ✅ 已保存: {target['path']} ({w}x{h})")

    print("\n" + "=" * 60)
    print("  全部完成!")
    print("=" * 60)
    print("\n提示: 运行 main.py 测试新的模板:")

    print("  python vpn_automation/main.py")

if __name__ == "__main__":
    main()