"""
Configuration module for VPN automation.
All tunable parameters are centralized here.
"""

from pathlib import Path

# ============================================================
# Project paths
# ============================================================
BASE_DIR = Path(__file__).parent
SCREENSHOTS_DIR = BASE_DIR / "screenshots"

# Ensure screenshots directory exists
SCREENSHOTS_DIR.mkdir(exist_ok=True)

# ============================================================
# Window settings
# ============================================================
WINDOW_TITLE = "小熊加速器"

# ============================================================
# Screenshot file names for image recognition
# ============================================================

# Main page: "更换线路" button
IMAGE_CHANGE_LINE = str(SCREENSHOTS_DIR / "btn_change_line.png")

# Line row tags: click on these to trigger connection
# "普通用户" tag (for AA1, AA2)
IMAGE_TAG_NORMAL = str(SCREENSHOTS_DIR / "tag_normal.png")
# "永久用户" tag (for AA3)
IMAGE_TAG_FOREVER = str(SCREENSHOTS_DIR / "tag_forever.png")

# Line status: red "100%" text indicating line is full
IMAGE_STATUS_FULL = str(SCREENSHOTS_DIR / "status_full.png")

# Connected page: "连接成功" text
IMAGE_STATUS_CONNECTED = str(SCREENSHOTS_DIR / "status_connected.png")

# Page anchor: "充值" button at top-right corner
IMAGE_RECHARGE = str(SCREENSHOTS_DIR / "btn_recharge.png")

# ============================================================
# Image recognition confidence thresholds (0.0 ~ 1.0)
# ============================================================
# General default confidence (for buttons, labels)
CONFIDENCE = 0.5

# Tag image detection (普通用户, 永久用户) — was 0.6, need lower for full-screen match
CONFIDENCE_TAG = 0.5

# High confidence to avoid false-positive "100%" detection
CONFIDENCE_FULL = 0.8

# Low confidence for "充值" anchor (actual score ~0.44)
CONFIDENCE_ANCHOR = 0.35

# Confidence for "连接成功" status detection
CONFIDENCE_CONNECTED = 0.7

# ============================================================
# Line row search: after finding line name text, extend rightwards
# to search for the tag image. This region is relative to the
# name text position. (pixels)
# ============================================================
ROW_SEARCH_OFFSET_X = 200      # start of search region (right of name text)
ROW_SEARCH_WIDTH = 400         # width of search region to the right

# ============================================================
# Timing settings (seconds)
# ============================================================
WAIT_SHORT = 1
WAIT_MEDIUM = 2
WAIT_REFRESH = 5
WAIT_CONNECT = 8
WAIT_BEFORE_RETRY = 2

# ============================================================
# Retry settings
# ============================================================
MAX_RETRIES = 100

# ============================================================
# URL to open after successful connection
# ============================================================
TARGET_URL = "https://chat.openai.com"

# ============================================================
# DPI scaling / multi-resolution hints
# ============================================================
#
# DPI Compatibility:
# - PyAutoGUI locateOnScreen() works with pixel-perfect matching.
# - If DPI scaling is NOT 100% (e.g., 125%, 150% on Windows),
#   you MUST set Windows DPI scaling to 100% for the VPN app,
#   OR take screenshots at the SAME DPI scaling level as runtime.
#
# Multi-resolution Tips:
# - LocateOnScreen() does NOT auto-scale templates.
# - If you run the script on a different resolution/DPI:
#   1. Re-take all template PNG screenshots at that resolution.
#   2. Or set `pyautogui.USE_IMAGE_RESIZE = True` (experimental).
# - Recommended: Keep a separate screenshots/ folder per resolution.
#
