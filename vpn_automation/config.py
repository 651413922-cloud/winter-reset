"""
Configuration module for VPN automation.
All tunable parameters are centralized here.
"""

import os
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
# Place your cropped button images in the screenshots/ folder
# ============================================================

# "更换线路" button on main page
IMAGE_CHANGE_LINE = str(SCREENSHOTS_DIR / "btn_change_line.png")

# Three free lines in RED (unavailable) state
# Script uses reverse matching: if RED image is NOT found → line is available (blue/yellow)
IMAGE_LINE_AA1_RED = str(SCREENSHOTS_DIR / "line_aa1_red.png")   # 美国节点-免费试用AA1 (red/unavailable)
IMAGE_LINE_AA2_RED = str(SCREENSHOTS_DIR / "line_aa2_red.png")   # 美国节点-免费试用AA2 (red/unavailable)
IMAGE_LINE_AA3_RED = str(SCREENSHOTS_DIR / "line_aa3_red.png")   # 美国节点-永久用户AA3 (red/unavailable)

# "已连接" status indicator
IMAGE_STATUS_CONNECTED = str(SCREENSHOTS_DIR / "status_connected.png")

# ============================================================
# Image recognition confidence threshold (0.0 ~ 1.0)
# Lower = more tolerant (may cause false positives)
# Higher = stricter (may miss matches)
# ============================================================
CONFIDENCE = 0.8

# ============================================================
# Timing settings (seconds)
# ============================================================
WAIT_SHORT = 1          # Short wait between operations
WAIT_MEDIUM = 3         # Medium wait for UI transitions
WAIT_REFRESH = 5        # Wait after clicking refresh/change line
WAIT_CONNECT = 5        # Wait after clicking a line to auto-connect
WAIT_BEFORE_RETRY = 2   # Wait before next retry cycle

# ============================================================
# Retry settings
# ============================================================
MAX_RETRIES = 100

# ============================================================
# URL to open after successful connection
# ============================================================
TARGET_URL = "https://chat.openai.com"
