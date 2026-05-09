"""
UI State Machine — Page-first detection strategy.

Phase 1: Match full-page screenshots against the screen
Phase 2: Within matched page, search for sub-elements

This eliminates false positives from cross-page element matches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from config import TEMPLATE, CONF
from logger import Logger
from matcher import locate_page, locate_in_region, locate_all_in_region, locate


class UIState(Enum):
    MAIN = "main"              # main_page.png matched (has "更换线路")
    LINE_PAGE = "line_page"    # line_page.png matched (line selection UI)
    CONNECTED = "connected"    # connected_status found
    POPUP = "popup"            # popup dialog
    UNKNOWN = "unknown"        # cannot determine
    DONE = "done"


@dataclass
class PageContext:
    """
    Result of page detection.
    page: which page was matched (MAIN / LINE_PAGE / None)
    box:  (left, top, width, height) of the page on screen
    """
    state: UIState = UIState.UNKNOWN
    box: Optional[tuple] = None   # page region on screen

    @property
    def has_page(self) -> bool:
        return self.box is not None


class StateManager:
    """
    Page-first state detection.

    detect() returns a PageContext:
      - page matched → context has page state + bounding box
      - sub-elements → checked AFTER page identification
      - popup/connected → checked globally (can appear on any page)
    """

    def __init__(self):
        self.page_context = PageContext()
        self.state = UIState.UNKNOWN
        self.previous_state = UIState.UNKNOWN

    def detect(self) -> PageContext:
        """
        Full detection cycle:
          1. Popup? (any page)
          2. Connected? (any page)
          3. Match full-page: main_page or line_page
          4. If matched → search for sub-elements within page
          5. Nothing → UNKNOWN
        """
        ctx = PageContext()

        # ── 1. Popup (highest priority) ─────────────────────────
        popup = locate(TEMPLATE["popup_close"], "popup_close",
                       confidence=CONF["popup"])
        if popup.found:
            self.previous_state = self.state
            self.state = UIState.POPUP
            ctx.state = UIState.POPUP
            self.page_context = ctx
            return ctx

        # ── 2. Connected status ─────────────────────────────────
        connected = locate(TEMPLATE["connected"], "connected_status",
                           confidence=CONF["connected"])
        if connected.found:
            self.state = UIState.CONNECTED
            ctx.state = UIState.CONNECTED
            ctx.box = connected.box
            self.page_context = ctx
            return ctx

        # ── 3. Page matching (try line_page first, then main) ──
        #    Try line_page first because it's more specific
        page_result = locate_page(TEMPLATE["page_line"], "page_line",
                                  confidence=CONF["page"])
        if page_result.found and page_result.box:
            ctx.state = UIState.LINE_PAGE
            ctx.box = page_result.box
            Logger.info(f"[state] LINE_PAGE matched: box={page_result.box}")
            self.state = UIState.LINE_PAGE
            self.page_context = ctx
            return ctx

        #    Try main_page
        page_result = locate_page(TEMPLATE["page_main"], "page_main",
                                  confidence=CONF["page"])
        if page_result.found and page_result.box:
            ctx.state = UIState.MAIN
            ctx.box = page_result.box
            Logger.info(f"[state] MAIN_PAGE matched: box={page_result.box}")
            self.state = UIState.MAIN
            self.page_context = ctx
            return ctx

        # ── 4. Nothing matched ──────────────────────────────────
        self.state = UIState.UNKNOWN
        ctx.state = UIState.UNKNOWN
        self.page_context = ctx
        Logger.info("[state] No page matched → UNKNOWN")
        return ctx

    def find_in_page(self, template_key: str, name: str = "",
                     confidence: float | None = None) -> MatchResult:
        """
        Search for a sub-element within the current page region.
        Must be called after detect() returns a known page.

        Args:
            template_key: key in TEMPLATE dict (e.g. "change_line", "free_badge")
            name: display name for logging
            confidence: override confidence threshold

        Returns:
            MatchResult for the sub-element (or not-found).
        """
        from matcher import MatchResult

        if not self.page_context.box:
            Logger.warning(f"[state] No page context — searching full screen for '{name}'")
            return locate(TEMPLATE[template_key], name=name, confidence=confidence)

        return locate_in_region(TEMPLATE[template_key], self.page_context.box,
                                name=name, confidence=confidence)

    def find_all_in_page(self, template_key: str, name: str = "",
                         confidence: float | None = None) -> MultiMatchResult:
        """
        Find ALL occurrences of a sub-element within the current page region.
        Used for scanning badges on the line page.

        Returns:
            MultiMatchResult with all matches.
        """
        from matcher import MultiMatchResult, locate_all_in_region

        if not self.page_context.box:
            Logger.warning(f"[state] No page context — searching full screen for '{name}'")
            return locate_all(TEMPLATE[template_key], name=name, confidence=confidence)

        return locate_all_in_region(TEMPLATE[template_key], self.page_context.box,
                                     name=name, confidence=confidence)

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
