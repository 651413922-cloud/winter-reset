"""
Main orchestrator — Page-first detection flow.

Detection strategy:
  Phase 1: Match full-page screenshots (page_main.png / page_line.png)
  Phase 2: Within matched page, search for sub-elements
  Phase 3: If no page matched, fall back to legacy full-screen matching

This eliminates false positives from cross-page element matches.
"""

import sys
import time
import webbrowser

import pyautogui
import pygetwindow as gw

from config import (
    WINDOW_TITLE,
    TEMPLATE,
    CONF,
    WAIT,
    MAX_RETRIES,
    TARGET_URL,
)
from logger import Logger
from template_validator import validate_all
from state_manager import StateManager, UIState
from matcher import locate
from detector import scan_all
from clicker import Clicker
from debug_visualizer import capture_and_annotate


def find_window() -> bool:
    """Activate the VPN window. Returns True on success."""
    Logger.info(f"Looking for window: '{WINDOW_TITLE}'")
    try:
        windows = gw.getWindowsWithTitle(WINDOW_TITLE)
        if not windows:
            Logger.error(f"Window '{WINDOW_TITLE}' not found")
            return False
        win = windows[0]
        if win.isMinimized:
            win.restore()
        win.activate()
        time.sleep(WAIT["short"])
        Logger.info(f"Window '{WINDOW_TITLE}' activated")
        return True
    except Exception as e:
        Logger.error(f"Window error: {e}")
        return False


def go_back():
    """Press ESC to return to main page."""
    Logger.info("Going back to main page (ESC)...")
    pyautogui.press("esc")
    time.sleep(WAIT["medium"])


def main():
    Logger.info("=" * 50)
    Logger.info("VPN Automation — Page-First Detection System")
    Logger.info("=" * 50)
    Logger.info(f"Max retries: {MAX_RETRIES}")
    Logger.info("Press Ctrl+C to abort; mouse to top-left for emergency stop")
    Logger.info("=" * 50)

    # ── Step 0: Validate templates ──────────────────────────────
    if not validate_all():
        Logger.error("Template validation FAILED. Please add missing screenshots.")
        sys.exit(1)

    # ── Initialize ──────────────────────────────────────────────
    state_mgr = StateManager()
    clicker = Clicker()
    consecutive_fail = 0
    retry_count = 0

    # ── Main loop ───────────────────────────────────────────────
    try:
        if not find_window():
            sys.exit(1)

        while retry_count < MAX_RETRIES:
            retry_count += 1
            Logger.info("")
            Logger.info(f"=== Round {retry_count}/{MAX_RETRIES} ===")

            # ── Phase 1: Page-first detection ───────────────────
            ctx = state_mgr.detect()
            current_state = ctx.state
            page_box = ctx.box   # (left, top, width, height) or None

            Logger.info(f"[state] Current: {current_state.value} → action: {state_mgr.next_action()}")
            if page_box:
                Logger.info(f"[state] Page region: {page_box}")

            # ── Handle POPUP ────────────────────────────────────
            if current_state == UIState.POPUP:
                if clicker.close_popup():
                    Logger.success("[state] Popup closed, continuing")
                    time.sleep(WAIT["medium"])
                    continue
                else:
                    Logger.warning("[state] Popup detected but close button not found")
                    go_back()
                    continue

            # ── Handle CONNECTED ────────────────────────────────
            if current_state == UIState.CONNECTED:
                Logger.success("=" * 50)
                Logger.success("[SUCCESS] VPN connected!")
                Logger.success("=" * 50)
                clicker.reset_anti_loop()

                Logger.info(f"Opening browser: {TARGET_URL}")
                try:
                    webbrowser.open(TARGET_URL)
                    Logger.success(f"Browser opened: {TARGET_URL}")
                except Exception as e:
                    Logger.error(f"Failed to open browser: {e}")
                return

            # ── Handle MAIN ─────────────────────────────────────
            if current_state == UIState.MAIN:
                # Search for change_line button WITHIN page region
                Logger.info("[action] Looking for '更换线路' in page region...")

                change = locate_in_region(TEMPLATE["change_line"], page_box,
                                          name="change_line", confidence=CONF["button"])

                if change.found:
                    clicked = clicker.click_box(change.box, change.center_x, change.center_y,
                                                "change_line")
                    if clicked:
                        time.sleep(WAIT["long"])
                        # Check if page switched → scan for badges in new page
                        re_ctx = state_mgr.detect()
                        if re_ctx.state == UIState.LINE_PAGE:
                            Logger.success("Page switched to LINE_PAGE!")
                            continue
                        elif re_ctx.state == UIState.POPUP:
                            clicker.close_popup()
                            continue
                        elif re_ctx.state == UIState.CONNECTED:
                            continue
                        else:
                            # Change line still visible → try again
                            Logger.info("Page didn't switch yet, retrying...")
                            continue
                    else:
                        Logger.warning("Failed to click change_line")
                        time.sleep(WAIT["retry_gap"])
                        continue
                else:
                    Logger.warning("change_line not found in page region")
                    # Fallback: try full screen
                    change_fs = locate(TEMPLATE["change_line"], "change_line",
                                       confidence=CONF["button"])
                    if change_fs.found:
                        Logger.info("Found change_line on full screen (fallback)")
                        clicked = clicker.click_box(change_fs.box, change_fs.center_x,
                                                    change_fs.center_y, "change_line")
                        if clicked:
                            time.sleep(WAIT["long"])
                            continue
                    Logger.warning("change_line not found at all — unknown state")
                    go_back()
                    time.sleep(WAIT["short"])
                    continue

            # ── Handle LINE_PAGE ────────────────────────────────
            if current_state == UIState.LINE_PAGE:
                Logger.info("[action] Scanning for eligible lines "
                           f"within page region: {page_box}")

                # Phase 2: Scan badges WITHIN page region
                result = scan_all(page_region=page_box)

                # Debug annotation
                if result.eligible_lines:
                    all_boxes = [c.box for c in result.eligible_lines]
                    all_labels = []
                    for c in result.eligible_lines:
                        pct = f"{c.percent}%" if c.percent is not None else "N/A"
                        all_labels.append(f"#{c.id}-{c.badge}-{c.status}-{pct}")
                    all_colors = []
                    for c in result.eligible_lines:
                        if c.status == "full":
                            all_colors.append((0, 0, 255))
                        elif c.status == "available":
                            all_colors.append((0, 255, 0))
                        else:
                            all_colors.append((255, 255, 0))
                    capture_and_annotate(
                        label="eligible_lines_scan",
                        boxes=all_boxes,
                        box_labels=all_labels,
                        box_colors=all_colors,
                    )

                if result.has_available:
                    consecutive_fail = 0
                    for card in result.available:
                        Logger.info(f"  → Trying line #{card.id} ({card.badge}) "
                                   f"at ({card.center_x}, {card.center_y})")

                        if not clicker.click_card(card.center_x, card.center_y,
                                                  f"line#{card.id}-{card.badge}"):
                            Logger.warning(f"  Anti-loop skipped line #{card.id}")
                            continue

                        Logger.info(f"  Waiting {WAIT['connect']}s for connection...")
                        time.sleep(WAIT["connect"])

                        # Re-detect
                        new_ctx = state_mgr.detect()
                        if new_ctx.state == UIState.POPUP:
                            clicker.close_popup()
                            continue
                        if new_ctx.state == UIState.CONNECTED:
                            Logger.success(f"Connected via line #{card.id} ({card.badge})!")
                            break
                        else:
                            Logger.warning(f"  Line #{card.id} did not connect")
                            continue
                    else:
                        Logger.info("All eligible lines tried, no connection yet")
                        continue
                else:
                    consecutive_fail += 1
                    Logger.warning(f"No available lines (consecutive_fail={consecutive_fail})")

                    if consecutive_fail >= 3:
                        Logger.info("3 consecutive failures — going back to refresh")
                        go_back()
                        time.sleep(WAIT["long"])
                        consecutive_fail = 0
                    else:
                        Logger.info("Staying on line page, will re-scan...")
                        time.sleep(WAIT["long"])
                continue

            # ── Handle UNKNOWN ──────────────────────────────────
            Logger.warning("[state] Unknown UI state — going back via ESC")
            go_back()
            time.sleep(WAIT["medium"])

        # ── Out of retries ──────────────────────────────────────
        Logger.error(f"Failed after {MAX_RETRIES} rounds")
        sys.exit(1)

    except KeyboardInterrupt:
        Logger.warning("\nScript interrupted by user")
        sys.exit(0)
    except Exception as e:
        Logger.error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def locate_in_region(image_path: str, region: tuple | None, name: str = "",
                     confidence: float | None = None):
    """Search for an image within a region. Falls back to full screen if no region."""
    from matcher import locate, locate_in_region as _locate_in_region
    if region:
        return _locate_in_region(image_path, region, name=name, confidence=confidence)
    else:
        return locate(image_path, name=name, confidence=confidence)


if __name__ == "__main__":
    main()
