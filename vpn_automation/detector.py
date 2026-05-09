"""
Line state detector — Badge-first + OCR architecture.

Flow:
  1. Accept an optional page_region (from PageContext.box)
  2. Search for badges ONLY within that region (if provided)
  3. For each matched badge → expand into line ROI
  4. Within each line ROI → use OCR to read percentage
  5. percent >= 100 → "full"
     percent < 100  → "available"
     no number      → "unknown"

Key rule: Lines WITHOUT a recognized badge are NEVER touched.
Status is determined ONLY by OCR percentage, NOT by image templates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pyautogui

from config import TEMPLATE, CONF, ROI_EXPAND_RIGHT, ROI_EXPAND_BOTTOM, FULL_THRESHOLD
from matcher import locate_all
from ocr_reader import read_percentage_from_roi
from logger import Logger


@dataclass
class EligibleLineInfo:
    """
    One detected eligible line with its OCR-determined status.
    id:      1-based index (top-to-bottom order)
    badge:   "free" | "permanent"  ← which badge triggered this
    status:  "available" | "full" | "unknown"
    percent: the actual OCR percentage value (None if not readable)
    box:     (left, top, width, height) of the full line card
    center_x, center_y:  center of the card (for clicking)
    """
    id: int
    badge: str
    status: str
    percent: Optional[int]
    box: tuple
    center_x: int
    center_y: int


@dataclass
class ScanResult:
    """Result of scanning all eligible lines."""
    eligible_lines: List[EligibleLineInfo] = field(default_factory=list)

    @property
    def has_eligible(self) -> bool:
        return len(self.eligible_lines) > 0

    @property
    def available(self) -> List[EligibleLineInfo]:
        return [l for l in self.eligible_lines if l.status == "available"]

    @property
    def has_available(self) -> bool:
        return len(self.available) > 0

    @property
    def full(self) -> List[EligibleLineInfo]:
        return [l for l in self.eligible_lines if l.status == "full"]


# ── Badge definitions ──────────────────────────────────────────────
_BADGES = [
    ("free_badge", "free"),
    ("permanent_badge", "permanent"),
]


def _expand_badge_to_line_roi(badge_box: tuple) -> tuple:
    """
    Given a badge box (left, top, width, height),
    expand it rightward + downward to create a ROI covering the full line row.
    Returns a tuple of plain Python ints (for pyautogui compatibility).
    """
    b_left, b_top, b_width, b_height = (int(v) for v in badge_box)
    roi_left = b_left
    roi_top = b_top
    roi_width = b_width + ROI_EXPAND_RIGHT
    roi_height = b_height + ROI_EXPAND_BOTTOM

    screen_w, screen_h = (int(v) for v in pyautogui.size())
    roi_left = max(0, int(roi_left))
    roi_top = max(0, int(roi_top))
    roi_width = min(int(roi_width), screen_w - roi_left)
    roi_height = min(int(roi_height), screen_h - roi_top)

    return (roi_left, roi_top, roi_width, roi_height)


def _determine_status(percent: Optional[int], line_id: int) -> str:
    """
    Determine line status from OCR percentage.

    Rules:
      - percent >= FULL_THRESHOLD (100) → "full"
      - percent <  FULL_THRESHOLD (100) → "available"
      - None → "unknown"
    """
    if percent is None:
        return "unknown"

    if percent >= FULL_THRESHOLD:
        Logger.info(f"    → Line #{line_id}: {percent}% >= {FULL_THRESHOLD}% = FULL")
        return "full"
    else:
        Logger.info(f"    → Line #{line_id}: {percent}% < {FULL_THRESHOLD}% = AVAILABLE")
        return "available"


def scan_all(page_region: tuple | None = None) -> ScanResult:
    """
    Full scan — badge-first + OCR.

    Args:
        page_region: (left, top, width, height) to restrict badge search.
                     If None, searches full screen.

    1. Scan for all badges (free + permanent), optionally within page_region
    2. Deduplicate by y-position
    3. For each unique badge:
       a. Expand badge to full line ROI
       b. Read percentage with OCR from the ROI
       c. Determine status: percent >= 100 → full, else available
    4. Return structured result
    """
    result = ScanResult()
    line_counter = 0

    # ── Step 1: Collect all badge matches ──────────────────────
    all_raw_matches = []
    for template_key, badge_name in _BADGES:
        image_path = TEMPLATE[template_key]
        Logger.info(f"[detector] Scanning for '{badge_name}' badge..."
                    f" region={page_region}")
        badge_matches = locate_all(image_path, badge_name,
                                   confidence=CONF["badge"],
                                   region=page_region)
        for m in badge_matches.matches:
            if m.found and m.box:
                all_raw_matches.append((badge_name, m.box, m.center_x, m.center_y))

    if not all_raw_matches:
        Logger.warning("[detector] No eligible badges found on screen")
        return result

    Logger.info(f"[detector] Found {len(all_raw_matches)} badge match(es) total")

    # ── Step 2: Sort top→bottom, deduplicate by y ─────────────
    all_raw_matches.sort(key=lambda x: x[1][1])

    deduplicated = []
    last_y = -100
    for badge_name, box, cx, cy in all_raw_matches:
        if abs(box[1] - last_y) < 20:
            Logger.info(f"  Skipping duplicate badge at y={box[1]} (same line)")
            continue
        deduplicated.append((badge_name, box, cx, cy))
        last_y = box[1]

    # ── Step 3: For each unique badge → expand → OCR → status ─
    for badge_name, badge_box, b_cx, b_cy in deduplicated:
        line_counter += 1
        line_id = line_counter

        # Expand badge to full line ROI
        roi = _expand_badge_to_line_roi(badge_box)
        Logger.info(f"  Eligible line #{line_id}: badge='{badge_name}' at ({b_cx},{b_cy})")

        # OCR: read percentage from ROI
        Logger.info(f"    [OCR] Reading percentage from ROI: {roi}")
        percent = read_percentage_from_roi(roi, line_id)

        # Determine status from percentage
        status = _determine_status(percent, line_id)

        # Click target = ROI center
        roi_center_x = roi[0] + roi[2] // 2
        roi_center_y = roi[1] + roi[3] // 2

        line_info = EligibleLineInfo(
            id=line_id,
            badge=badge_name,
            status=status,
            percent=percent,
            box=roi,
            center_x=roi_center_x,
            center_y=roi_center_y,
        )
        result.eligible_lines.append(line_info)

        percent_str = f"{percent}%" if percent is not None else "N/A"
        Logger.info(f"    → #{line_id}: badge='{badge_name}' percent={percent_str}"
                   f" status={status} click=({roi_center_x},{roi_center_y})")

    # ── Summary ────────────────────────────────────────────────
    avail = len(result.available)
    full = len(result.full)
    unk = len(result.eligible_lines) - avail - full
    Logger.info(f"[detector] Scan complete: {len(result.eligible_lines)} eligible lines"
               f" ({avail} available, {full} full, {unk} unknown)")

    return result
