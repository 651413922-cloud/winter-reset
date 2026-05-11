"""
Central configuration for VPN automation.
All tunable parameters in one place.
"""

from pathlib import Path

# ── Project paths ─────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
DEBUG_DIR = BASE_DIR / "debug"

for sub in ["buttons", "badges", "status", "popup", "anchors", "pages"]:
    (TEMPLATES_DIR / sub).mkdir(exist_ok=True, parents=True)
DEBUG_DIR.mkdir(exist_ok=True)

# ── Tesseract OCR path (Windows default) ─────────────────────────
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ── Window ────────────────────────────────────────────────────────
WINDOW_TITLE = "小熊加速器"

# ── Template paths ────────────────────────────────────────────────
TEMPLATE = {
    # ── State detection elements ──────────────────────────────
    "change_line": str(TEMPLATES_DIR / "buttons" / "change_line_button.png"),
    "line_page_title": str(TEMPLATES_DIR / "pages" / "line_page_title.png"),
    "free_badge": str(TEMPLATES_DIR / "badges" / "free_badge.png"),
    "permanent_badge": str(TEMPLATES_DIR / "badges" / "permanent_badge.png"),
    "connected": str(TEMPLATES_DIR / "status" / "connected_status.png"),
    "popup_close": str(TEMPLATES_DIR / "popup" / "popup_close.png"),
}

# ── Confidence thresholds ─────────────────────────────────────────
CONF = {
    "page": 0.5,       # full-page match
    "button": 0.5,
    "badge": 0.55,     # 线路页面真实 badge 匹配度更高
    "connected": 0.7,
    "popup": 0.5,
}

# ── Template validation ───────────────────────────────────────────
TEMPLATE_MIN_WIDTH = 30
TEMPLATE_MIN_HEIGHT = 10

# ── Timing (seconds) ──────────────────────────────────────────────
WAIT = {
    "short": 1,
    "medium": 2,
    "long": 5,
    "connect": 8,
    "retry_gap": 2,
}

# ── Retry / anti-loop ─────────────────────────────────────────────
MAX_RETRIES = 100
ANTI_LOOP_MAX = 3

# ── URL ───────────────────────────────────────────────────────────
TARGET_URL = "https://chat.openai.com"

# ── Badge → ROI expansion ─────────────────────────────────────────
ROI_EXPAND_RIGHT = 400
ROI_EXPAND_BOTTOM = 40

# ── OCR percentage region (relative to ROI) ───────────────────────
OCR_REGION_OFFSET_X = 250
OCR_REGION_OFFSET_Y = 5
OCR_REGION_WIDTH = 120
OCR_REGION_HEIGHT = 30

# ── OCR status thresholds ─────────────────────────────────────────
FULL_THRESHOLD = 100

# ── OCR retries ───────────────────────────────────────────────────
OCR_MAX_RETRIES = 3
