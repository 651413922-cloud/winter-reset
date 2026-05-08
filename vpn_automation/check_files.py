"""
Quick script to check if all required screenshot files exist.
Run: python check_files.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    IMAGE_CHANGE_LINE,
    IMAGE_LINE_AA1,
    IMAGE_LINE_AA2,
    IMAGE_LINE_AA3,
    IMAGE_STATUS_FULL,
    IMAGE_STATUS_CONNECTED,
    IMAGE_RECHARGE,
    SCREENSHOTS_DIR,
)

FILES = [
    ("btn_change_line.png", IMAGE_CHANGE_LINE, "更换线路按钮"),
    ("line_aa1_label.png", IMAGE_LINE_AA1, "美国直连节点AA1 名称"),
    ("line_aa2_label.png", IMAGE_LINE_AA2, "美国直连节点AA2 名称"),
    ("line_aa3_label.png", IMAGE_LINE_AA3, "美国直连节点AA3 名称"),
    ("status_full.png", IMAGE_STATUS_FULL, "红色100%状态"),
    ("status_connected.png", IMAGE_STATUS_CONNECTED, "连接成功状态"),
    ("btn_recharge.png", IMAGE_RECHARGE, "充值按钮锚点"),
]

print("=" * 60)
print(f"Scanning folder: {SCREENSHOTS_DIR}")
print("=" * 60)

all_ok = True
for filename, fullpath, description in FILES:
    exists = Path(fullpath).exists()
    status = "OK" if exists else "MISSING"
    if not exists:
        all_ok = False
    print(f"  [{status}] {filename:30s} <- {description}")

print("=" * 60)
if all_ok:
    print(f"  All {len(FILES)} files found! Ready to run: python main.py")
else:
    print("  Some files are missing! Please add them to the screenshots/ folder.")
print("=" * 60)
