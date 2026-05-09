"""
Core image matching module.
Encapsulates pyautogui.locateOnScreen / locateAllOnScreen.
Defaults to grayscale matching.
Returns structured MatchResult objects (never raw boxes).
Handles needle-dimension-exceed gracefully.

Enhanced with:
  - locate_page()     → match full-page screenshots to determine state
  - locate_in_region() → search for sub-elements WITHIN a given page region
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pyautogui

from config import CONF
from logger import Logger


@dataclass
class MatchResult:
    """Structured result of a single image match."""
    name: str
    box: tuple | None            # (left, top, width, height) or None
    center_x: int | None
    center_y: int | None
    confidence: float
    found: bool

    @property
    def center(self) -> tuple[int, int] | None:
        if self.center_x is not None and self.center_y is not None:
            return (self.center_x, self.center_y)
        return None


@dataclass
class MultiMatchResult:
    """Structured result of locateAllOnScreen."""
    name: str
    matches: list[MatchResult]   # sorted top→bottom
    confidence: float

    @property
    def count(self) -> int:
        return len(self.matches)


def _safe_region(region: tuple) -> tuple:
    """Convert to pure Python ints for pyautogui compatibility."""
    return tuple(int(v) for v in region)


def locate(
    image_path: str,
    name: str = "",
    confidence: float | None = None,
    region: tuple | None = None,
    grayscale: bool = True,
    timeout: float = 0,
) -> MatchResult:
    """
    Find a single image on screen.
    - Returns MatchResult (never raises).
    - region: restrict search to this (left, top, width, height) area.
    - Handles ImageNotFoundException, needle-dimension-exceed
      and file-not-found gracefully.
    - If timeout > 0, retries until found or timeout reached.
    """
    use_conf = confidence if confidence is not None else CONF.get("button", 0.5)
    img_path = Path(image_path)
    display = name or img_path.stem

    if not img_path.exists():
        Logger.warning(f"[matcher] File not found: {image_path}")
        return MatchResult(display, None, None, None, use_conf, False)

    kwargs = {"confidence": use_conf, "grayscale": grayscale}
    if region is not None:
        kwargs["region"] = _safe_region(region)

    deadline = time.time() + timeout if timeout > 0 else None

    while True:
        try:
            box = pyautogui.locateOnScreen(str(img_path), **kwargs)
            if box:
                cx, cy = pyautogui.center(box)
                Logger.info(f"[match] '{display}' → Box={box} Center=({cx},{cy}) "
                           f"conf={use_conf} region={region}")
                return MatchResult(display, box, cx, cy, use_conf, True)
            # not found
            if deadline is not None and time.time() < deadline:
                time.sleep(0.5)
                continue
            Logger.info(f"[match] '{display}' — not found")
            return MatchResult(display, None, None, None, use_conf, False)

        except pyautogui.ImageNotFoundException:
            if deadline is not None and time.time() < deadline:
                time.sleep(0.5)
                continue
            Logger.info(f"[match] '{display}' — not found")
            return MatchResult(display, None, None, None, use_conf, False)

        except Exception as e:
            err = str(e)
            if "needle dimension" in err.lower() or "exceed" in err.lower():
                Logger.warning(f"[matcher] '{display}' region too small — {err}")
                return MatchResult(display, None, None, None, use_conf, False)
            Logger.warning(f"[matcher] '{display}' error — {err}")
            return MatchResult(display, None, None, None, use_conf, False)


def locate_all(
    image_path: str,
    name: str = "",
    confidence: float | None = None,
    region: tuple | None = None,
    grayscale: bool = True,
) -> MultiMatchResult:
    """
    Find ALL occurrences of an image on screen.
    If region is provided, search is restricted to that area.
    Returns MultiMatchResult (never raises).
    Results sorted top-to-bottom by y coordinate.
    """
    use_conf = confidence if confidence is not None else CONF.get("badge", 0.5)
    img_path = Path(image_path)
    display = name or img_path.stem

    if not img_path.exists():
        Logger.warning(f"[matcher] File not found: {image_path}")
        return MultiMatchResult(display, [], use_conf)

    kwargs = {"confidence": use_conf, "grayscale": grayscale}
    if region is not None:
        kwargs["region"] = _safe_region(region)

    try:
        raw = list(pyautogui.locateAllOnScreen(str(img_path), **kwargs))
        raw.sort(key=lambda b: b[1])
        matches = []
        for box in raw:
            cx, cy = pyautogui.center(box)
            matches.append(MatchResult(display, box, cx, cy, use_conf, True))
        Logger.info(f"[match] '{display}' — {len(matches)} match(es) in region={region}")
        for m in matches:
            Logger.info(f"         Box={m.box} Center=({m.center_x},{m.center_y})")
        return MultiMatchResult(display, matches, use_conf)

    except pyautogui.ImageNotFoundException:
        Logger.info(f"[match] '{display}' — 0 matches")
        return MultiMatchResult(display, [], use_conf)

    except Exception as e:
        err = str(e)
        if "needle dimension" in err.lower():
            Logger.warning(f"[matcher] '{display}' region issue — {err}")
        else:
            Logger.warning(f"[matcher] '{display}' error — {err}")
        return MultiMatchResult(display, [], use_conf)


# ── Page-level helpers ─────────────────────────────────────────────

def locate_page(page_image_path: str, name: str = "",
                confidence: float | None = None) -> MatchResult:
    """
    Match a full-page screenshot against the current screen.
    This is the FIRST phase of state detection.

    Returns:
      MatchResult with the page's bounding box on screen.
      If found, the box defines the ROI for sub-element search.
    """
    use_conf = confidence if confidence is not None else CONF.get("page", 0.5)
    result = locate(page_image_path, name=name, confidence=use_conf)
    return result


def locate_in_region(sub_image_path: str, page_box: tuple,
                     name: str = "",
                     confidence: float | None = None) -> MatchResult:
    """
    Search for a sub-element (button, badge) WITHIN a page region.
    This is the SECOND phase after a page has been identified.

    Args:
        sub_image_path: path to the sub-element template (e.g. change_line_button.png)
        page_box: (left, top, width, height) of the parent page
        name: display name for logging
        confidence: match confidence threshold

    Returns:
        MatchResult for the sub-element (coordinates relative to screen).
    """
    return locate(sub_image_path, name=name, confidence=confidence, region=page_box)


def locate_all_in_region(sub_image_path: str, page_box: tuple,
                         name: str = "",
                         confidence: float | None = None) -> MultiMatchResult:
    """
    Find ALL occurrences of a sub-element within a page region.
    Used for finding all badge matches on the line selection page.

    Args:
        sub_image_path: path to the badge template (e.g. free_badge.png)
        page_box: (left, top, width, height) of the parent page
        name: display name for logging
        confidence: match confidence threshold

    Returns:
        MultiMatchResult with all sub-element matches.
    """
    return locate_all(sub_image_path, name=name, confidence=confidence, region=page_box)
