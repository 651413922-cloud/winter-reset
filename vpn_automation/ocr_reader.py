"""
OCR Percentage Reader module.

Reads the percentage number (e.g. "100%", "45%") from a region of the screen
using Tesseract OCR.

Used by detector.py to determine line status:
  - percent >= 100 → "full"
  - percent < 100  → "available"

Includes preprocessing with OpenCV to improve OCR accuracy on UI elements.
"""

from __future__ import annotations

import re
import time
from typing import Optional, Tuple

import pyautogui
import numpy as np

from config import (
    TESSERACT_CMD,
    OCR_REGION_OFFSET_X,
    OCR_REGION_OFFSET_Y,
    OCR_REGION_WIDTH,
    OCR_REGION_HEIGHT,
    OCR_MAX_RETRIES,
)
from logger import Logger

# ── pytesseract import with custom path ────────────────────────────
try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    _HAVE_TESSERACT = True
except Exception as e:
    _HAVE_TESSERACT = False
    Logger.warning(f"[ocr] pytesseract import failed: {e}")

try:
    import cv2
    _HAVE_CV2 = True
except ImportError:
    _HAVE_CV2 = False


def _safe_roi(roi: tuple) -> tuple:
    """
    Convert any ROI tuple to pure Python ints.
    Handles np.int64, np.int32, float, etc.
    Returns (left, top, width, height) as plain int.
    """
    return tuple(int(v) for v in roi)


def read_percentage_from_roi(line_roi: Tuple[int, int, int, int],
                             line_id: int) -> Optional[int]:
    """
    Extract the percentage number from a line card ROI.

    Args:
        line_roi: (left, top, width, height) of the full line card.
        line_id:  1-based line ID for logging.

    Returns:
        Integer percentage value (e.g. 100, 45), or None if not found.

    The function:
      1. Converts all ROI values to pure Python int (safe_roi)
      2. Calculates the OCR sub-region within the line ROI
      3. Captures a screenshot of that sub-region
      4. Preprocesses with OpenCV (grayscale, threshold, invert)
      5. Runs Tesseract OCR with --psm 7 (single line) and digit whitelist
      6. Parses the first number from the result
      7. Retries up to OCR_MAX_RETRIES times if nothing found
    """
    if not _HAVE_TESSERACT:
        Logger.error("[ocr] Tesseract not available — please install and set TESSERACT_CMD")
        return None

    # ═══ SAFETY: Convert ROI to pure Python ints ═══════════════
    line_roi = _safe_roi(line_roi)

    # ── Calculate OCR sub-region ────────────────────────────────
    ocr_left = line_roi[0] + OCR_REGION_OFFSET_X
    ocr_top = line_roi[1] + OCR_REGION_OFFSET_Y
    ocr_width = OCR_REGION_WIDTH
    ocr_height = OCR_REGION_HEIGHT

    # Clamp to line ROI boundaries
    ocr_left = max(line_roi[0], ocr_left)
    ocr_top = max(line_roi[1], ocr_top)
    ocr_width = min(ocr_width, line_roi[0] + line_roi[2] - ocr_left)
    ocr_height = min(ocr_height, line_roi[1] + line_roi[3] - ocr_top)

    # ═══ SAFETY: Ensure ocr_region is also pure ints ═══════════
    ocr_region = (int(ocr_left), int(ocr_top), int(ocr_width), int(ocr_height))

    # ── Retry loop ──────────────────────────────────────────────
    for attempt in range(1, OCR_MAX_RETRIES + 1):
        try:
            # Capture the OCR region
            screenshot = pyautogui.screenshot(region=ocr_region)

            if _HAVE_CV2:
                # OpenCV preprocessing for better OCR accuracy
                img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

                # Threshold to make text stand out (white text on dark bg)
                # UI typically has white/light text on dark background
                _, thresh = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY)

                # Invert if text is white on black → black on white for Tesseract
                # Tesseract works best with black text on white background
                # Try both and use the one that gives a result
                result_standard = pytesseract.image_to_string(
                    thresh,
                    config='--psm 7 -c tessedit_char_whitelist=0123456789%'
                )

                inv = cv2.bitwise_not(thresh)
                result_inverted = pytesseract.image_to_string(
                    inv,
                    config='--psm 7 -c tessedit_char_whitelist=0123456789%'
                )

                # Pick the result that has a number
                standard_num = _extract_number(result_standard)
                inverted_num = _extract_number(result_inverted)

                percent = standard_num if standard_num is not None else inverted_num
            else:
                # No OpenCV fallback — raw PIL image
                text = pytesseract.image_to_string(
                    screenshot,
                    config='--psm 7 -c tessedit_char_whitelist=0123456789%'
                )
                percent = _extract_number(text)

            if percent is not None:
                Logger.info(f"[ocr] Line #{line_id}: OCR read {percent}%"
                           f" (attempt {attempt}) from region {ocr_region}")
                return percent

            Logger.info(f"[ocr] Line #{line_id}: attempt {attempt} — no number found"
                       f" (raw: '{_get_raw_text(screenshot)}')")

        except Exception as e:
            Logger.warning(f"[ocr] Line #{line_id}: OCR attempt {attempt} failed: {e}")

        # Brief pause before retry
        if attempt < OCR_MAX_RETRIES:
            time.sleep(0.3)

    Logger.warning(f"[ocr] Line #{line_id}: all {OCR_MAX_RETRIES} attempts failed")
    return None


def _extract_number(text: str) -> Optional[int]:
    """
    Extract the first integer from OCR text.
    Handles: "100%", "45 %", "80", "100%\n", etc.
    """
    # Find all digit sequences
    numbers = re.findall(r'(\d+)', text)
    if not numbers:
        return None
    return int(numbers[0])


def _get_raw_text(screenshot) -> str:
    """Get raw OCR text with default settings (no whitelist) for debugging."""
    try:
        return pytesseract.image_to_string(screenshot).strip().replace('\n', ' | ')
    except Exception:
        return "(error)"


def test_ocr_on_region(left: int, top: int, width: int, height: int) -> str:
    """
    Debug tool: capture a region and return what OCR reads.
    Usage:
        from ocr_reader import test_ocr_on_region
        print(test_ocr_on_region(100, 200, 120, 30))
    """
    if not _HAVE_TESSERACT:
        return "Tesseract not available"

    try:
        screenshot = pyautogui.screenshot(region=(left, top, width, height))

        # Try both preprocessings
        img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY)
        inv = cv2.bitwise_not(thresh)

        r1 = pytesseract.image_to_string(thresh).strip()
        r2 = pytesseract.image_to_string(inv).strip()
        r3 = pytesseract.image_to_string(screenshot).strip()

        return f"Standard: '{r1}' | Inverted: '{r2}' | Raw: '{r3}'"
    except Exception as e:
        return f"Error: {e}"
