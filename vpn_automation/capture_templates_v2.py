"""
模板截图工具 v2（无 OpenCV 窗口，纯后台截图保存）

工作原理：
1. 先截取当前屏幕 → 保存到 debug/
2. 你在图片查看器中打开，标示出图标/badge 的位置
3. 我根据你给的坐标裁剪出模板

用法（分两步）：

Step 1 - 截取「更换线路」按钮所在的首页
  python vpn_automation/capture_templates_v2.py screenshot change_line

Step 2 - 截取「线路页面」（FREE/PERMANENT_FREE badge）
  python vpn_automation/capture_templates_v2.py screenshot line_page

截图会保存在：
  vpn_automation/debug/capture_change_line.png
  vpn_automation/debug/capture_line_page.png

Step 3 - 裁剪模板（你告诉我坐标后，我执行）
  python vpn_automation/capture_templates_v2.py crop <模板名> <left> <top> <width> <height>

支持的模板名：
  change_line, free_badge, permanent_badge
"""

import sys
import time
from pathlib import Path

import pyautogui

DEBUG_DIR = Path(__file__).parent / "debug"
TEMPLATES_DIR = Path(__file__).parent / "templates"

# 确保目录存在
DEBUG_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
(TEMPLATES_DIR / "buttons").mkdir(exist_ok=True)
(TEMPLATES_DIR / "badges").mkdir(exist_ok=True)


def cmd_screenshot(target: str):
    """截取全屏并保存"""
    if target == "change_line":
        path = DEBUG_DIR / "capture_change_line.png"
        print(f"请在 VPN 主界面（能看到「更换线路」按钮）时按回车...")
        input()
        time.sleep(1)
        pyautogui.screenshot(str(path))
        print(f"✅ 已保存: {path} ({path.stat().st_size} bytes)")

    elif target == "line_page":
        path = DEBUG_DIR / "capture_line_page.png"
        print(f"请在 VPN 线路选择页面（能看到 FREE / PERMANENT_FREE badge）时按回车...")
        input()
        time.sleep(1)
        pyautogui.screenshot(str(path))
        print(f"✅ 已保存: {path} ({path.stat().st_size} bytes)")
    else:
        print(f"❌ 未知目标: {target}，可选: change_line, line_page")


def cmd_crop(template_name: str, left: int, top: int, width: int, height: int):
    """从已有截图中裁剪出模板"""
    # 确定源截图
    if template_name == "change_line":
        src = DEBUG_DIR / "capture_change_line.png"
        dst = TEMPLATES_DIR / "buttons" / "change_line_button.png"
    elif template_name == "free_badge":
        src = DEBUG_DIR / "capture_line_page.png"
        dst = TEMPLATES_DIR / "badges" / "free_badge.png"
    elif template_name == "permanent_badge":
        src = DEBUG_DIR / "capture_line_page.png"
        dst = TEMPLATES_DIR / "badges" / "permanent_badge.png"
    elif template_name == "line_page_title":
        src = DEBUG_DIR / "capture_line_page.png"
        dst = TEMPLATES_DIR / "pages" / "line_page_title.png"
    else:
        print(f"❌ 未知模板名: {template_name}")
        print(f"   可选: change_line, free_badge, permanent_badge, line_page_title")
        return

    if not src.exists():
        print(f"❌ 源截图不存在: {src}")
        print(f"   请先运行: python capture_templates_v2.py screenshot <target>")
        return

    from PIL import Image
    img = Image.open(src)
    crop = img.crop((left, top, left + width, top + height))

    dst.parent.mkdir(parents=True, exist_ok=True)
    crop.save(str(dst))
    print(f"✅ 模板已保存: {dst} ({width}x{height})")


def cmd_help():
    print(__doc__)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        cmd_help()
        sys.exit(1)

    command = sys.argv[1]

    if command == "screenshot":
        if len(sys.argv) < 3:
            print("请指定目标: change_line 或 line_page")
            sys.exit(1)
        cmd_screenshot(sys.argv[2])

    elif command == "crop":
        if len(sys.argv) < 7:
            print("用法: python capture_templates_v2.py crop <模板名> <left> <top> <width> <height>")
            sys.exit(1)
        name = sys.argv[2]
        left = int(sys.argv[3])
        top = int(sys.argv[4])
        w = int(sys.argv[5])
        h = int(sys.argv[6])
        cmd_crop(name, left, top, w, h)

    elif command in ("help", "--help", "-h"):
        cmd_help()

    else:
        print(f"未知命令: {command}")
        cmd_help()