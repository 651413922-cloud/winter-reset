"""
Click management module.
Handles all click actions:
  - Click card center (with anti-loop)
  - Click general button
  - Popup auto-close
  - Click logging + debug screenshot
"""

import time
from collections import defaultdict
from pathlib import Path

import pyautogui

from config import TEMPLATE, CONF, ANTI_LOOP_MAX, WAIT
from matcher import locate
from logger import Logger
from debug_visualizer import capture_and_annotate


class Clicker:
    """
    Manages all click operations.
    Tracks per-position click counts for anti-loop.
    """

    def __init__(self):
        # Anti-loop: key = "(center_x, center_y)" string, value = count
        self._click_counts: dict[str, int] = defaultdict(int)
        self._total_clicks = 0

    # ── Public API ───────────────────────────────────────────────

    def click_box(self, box: tuple, center_x: int, center_y: int,
                  name: str = "") -> bool:
        """
        Click at a given coordinate (from a matched box).
        Used when the button position is already known.
        Returns True if clicked successfully.
        """
        try:
            pyautogui.moveTo(center_x, center_y, duration=0.2)
            pyautogui.click()
            btn_name = name or f"({center_x},{center_y})"
            Logger.info(f"[clicker] Clicked '{btn_name}' at ({center_x},{center_y})")
            time.sleep(WAIT["short"])
            return True
        except Exception as e:
            Logger.warning(f"[clicker] Click at ({center_x},{center_y}) failed: {e}")
            return False

    def click_card(self, card_center_x: int, card_center_y: int, card_name: str = "") -> bool:
        """
        Click the center of a line card.
        - Checks anti-loop before clicking.
        - Saves annotated debug screenshot after click.
        - Returns True if clicked, False if anti-loop triggered.
        """
        key = f"({card_center_x},{card_center_y})"
        current = self._click_counts[key]

        if current >= ANTI_LOOP_MAX:
            Logger.warning(f"[clicker] ANTI-LOOP triggered for {key} ({card_name}) — skipping")
            return False

        try:
            pyautogui.moveTo(card_center_x, card_center_y, duration=0.2)
            pyautogui.click()
            self._click_counts[key] += 1
            self._total_clicks += 1
            name_str = f" '{card_name}'" if card_name else ""
            Logger.info(f"[clicker] Clicked{name_str} at ({card_center_x},{card_center_y}) "
                       f"(anti-loop count: {self._click_counts[key]}/{ANTI_LOOP_MAX})")

            # Annotated debug screenshot
            label = f"click_{card_name.replace(' ','')}" if card_name else f"click_{self._total_clicks}"
            capture_and_annotate(
                label=label,
                points=[(card_center_x, card_center_y)],
                point_labels=["click"],
                colors=[(0, 255, 0)],  # green dot
            )

            time.sleep(WAIT["short"])
            return True

        except Exception as e:
            Logger.warning(f"[clicker] Click failed at ({card_center_x},{card_center_y}): {e}")
            return False

    def click_button(self, image_path: str, name: str = "",
                     confidence: float | None = None) -> bool:
        """
        Find a button image and click its center.
        Returns True if found and clicked.
        """
        result = locate(image_path, name, confidence=confidence)
        if not result.found or result.center is None:
            Logger.error(f"[clicker] Button not found: {name or image_path}")
            return False

        cx, cy = result.center
        try:
            pyautogui.moveTo(cx, cy, duration=0.2)
            pyautogui.click()
            btn_name = name or Path(image_path).stem
            Logger.info(f"[clicker] Clicked button '{btn_name}' at ({cx},{cy})")

            capture_and_annotate(
                label=f"btn_{btn_name}",
                points=[(cx, cy)],
                point_labels=[btn_name],
                colors=[(0, 255, 0)],
            )

            time.sleep(WAIT["short"])
            return True
        except Exception as e:
            Logger.warning(f"[clicker] Button click failed: {e}")
            return False

    def close_popup(self) -> bool:
        """
        Detect and close any popup dialog.
        Returns True if popup was found and closed.
        """
        result = locate(TEMPLATE["popup_close"], "popup_close",
                        confidence=CONF["popup"])
        if not result.found or result.center is None:
            return False

        cx, cy = result.center
        try:
            pyautogui.moveTo(cx, cy, duration=0.2)
            pyautogui.click()
            Logger.info(f"[clicker] Closed popup at ({cx},{cy})")

            capture_and_annotate(
                label="popup_closed",
                points=[(cx, cy)],
                point_labels=["popup_close"],
                colors=[(0, 0, 255)],  # blue for popup
            )

            time.sleep(WAIT["medium"])
            return True
        except Exception as e:
            Logger.warning(f"[clicker] Popup close failed: {e}")
            return False

    def reset_anti_loop(self):
        """Reset all click counters (called after successful connection)."""
        self._click_counts.clear()
        Logger.info("[clicker] Anti-loop counters reset")
