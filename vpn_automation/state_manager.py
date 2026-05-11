"""
UI State Machine — Element-based priority detection.

Detection priority (most specific first):
  1. POPUP      → popup_close.png found
  2. CONNECTED  → connected_status.png found
  3. LINE_PAGE  → free_badge.png OR permanent_badge.png found  (checked BEFORE MAIN!)
  4. MAIN       → change_line_button.png found
  5. UNKNOWN    → nothing matches

Why LINE_PAGE before MAIN:
  - Badges ONLY exist on the line page (they are "免费试用" / "永久用户" labels)
  - change_line_button may still match on the line page (similar UI elements)
  - So checking badges FIRST ensures reliable LINE_PAGE detection

No full-page screenshots needed — just small, static element templates.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from config import TEMPLATE, CONF
from logger import Logger
from matcher import locate, MultiMatchResult


class UIState(Enum):
    MAIN = "main"              # change_line button visible
    LINE_PAGE = "line_page"    # badges visible (line selection UI)
    CONNECTED = "connected"    # connected_status found
    POPUP = "popup"            # popup dialog
    UNKNOWN = "unknown"        # cannot determine
    DONE = "done"              # finished


@dataclass
class DetectionResult:
    """
    Result of a detection cycle.
    state: which UI state was detected
    """
    state: UIState = UIState.UNKNOWN


class StateManager:
    """Element-based UI state detection."""

    def __init__(self):
        self.state = UIState.UNKNOWN
        self.previous_state = UIState.UNKNOWN

    def detect(self) -> DetectionResult:
        """
        Full detection cycle.
        Priority: POPUP > CONNECTED > LINE_PAGE > MAIN > UNKNOWN
        """
        # ── 1. Popup (highest priority — blocks everything) ─────
        popup = locate(TEMPLATE["popup_close"], "popup_close",
                       confidence=CONF["popup"])
        if popup.found:
            self.previous_state = self.state
            self.state = UIState.POPUP
            return DetectionResult(UIState.POPUP)

        # ── 2. Connected status ─────────────────────────────────
        connected = locate(TEMPLATE["connected"], "connected_status",
                           confidence=CONF["connected"])
        if connected.found:
            self.state = UIState.CONNECTED
            return DetectionResult(UIState.CONNECTED)

        # ── 3. LINE_PAGE: check for badges FIRST ────────────────
        #    Badges ONLY exist on the line selection page
        for badge_key, badge_name in [("free_badge", "free"), ("permanent_badge", "permanent")]:
            badge = locate(TEMPLATE[badge_key], badge_name,
                           confidence=CONF["badge"])
            if badge.found:
                Logger.info(f"[state] LINE_PAGE detected via '{badge_name}' badge")
                self.state = UIState.LINE_PAGE
                return DetectionResult(UIState.LINE_PAGE)

        # ── 4. MAIN: check for change_line button ───────────────
        change = locate(TEMPLATE["change_line"], "change_line",
                        confidence=CONF["button"])
        if change.found:
            self.state = UIState.MAIN
            return DetectionResult(UIState.MAIN)

        # ── 5. Nothing matched ──────────────────────────────────
        self.state = UIState.UNKNOWN
        Logger.info("[state] No elements matched → UNKNOWN")
        return DetectionResult(UIState.UNKNOWN)

    def next_action(self) -> str:
        """Return recommended action for current state."""
        mapping = {
            UIState.MAIN: "click_change_line",
            UIState.LINE_PAGE: "scan_and_click",
            UIState.CONNECTED: "open_browser",
            UIState.POPUP: "close_popup",
            UIState.UNKNOWN: "retry",
            UIState.DONE: "done",
        }
        return mapping.get(self.state, "retry")
