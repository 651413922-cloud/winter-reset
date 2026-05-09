"""
Core VPN controller module — "Visual State Card Recognition System".

Architecture upgrade:
  - No more OCR, no offset, no nearby region search, no tag distance
  - Each line is identified as a complete card screenshot
  - Card state is determined by state templates (full_line vs available_line)

Flow:
  1. Find each specific line card on screen (AA1, AA2, AA3)
  2. For each card:
     a. Check if full_line.png matches in card region → skip (full)
     b. Check if available_line.png matches in card region → click card center
  3. Anti-loop: skip card after ANTI_LOOP_MAX failed clicks
"""

import time
import webbrowser
from datetime import datetime
from pathlib import Path
from collections import defaultdict

import pyautogui
import pygetwindow as gw

from config import (
    SCREENSHOTS_DIR,
    WINDOW_TITLE,
    IMAGE_CHANGE_LINE,
    IMAGE_RECHARGE,
    IMAGE_LINE_AA1,
    IMAGE_LINE_AA2,
    IMAGE_LINE_AA3,
    IMAGE_FULL_LINE,
    IMAGE_AVAILABLE_LINE,
    IMAGE_STATUS_CONNECTED,
    CONFIDENCE,
    CONFIDENCE_LINE_CARD,
    CONFIDENCE_LINE_STATE,
    CONFIDENCE_CONNECTED,
    CONFIDENCE_ANCHOR,
    ANTI_LOOP_MAX,
    WAIT_SHORT,
    WAIT_MEDIUM,
    WAIT_AFTER_REFRESH,
    WAIT_CONNECT,
    WAIT_BEFORE_RETRY,
    MAX_RETRIES,
    TARGET_URL,
)
from logger import Logger


class VPNController:
    """Controls the VPN client via UI automation — Card State Recognition."""

    # -----------------------------------------------------------------
    #  Three specific free line cards to search for
    #  Each template is a complete row (name + tag + bg + status area)
    # -----------------------------------------------------------------
    LINE_CARDS = [
        (IMAGE_LINE_AA1, "AA1-免费试用"),
        (IMAGE_LINE_AA2, "AA2-免费试用"),
        (IMAGE_LINE_AA3, "AA3-永久用户"),
    ]

    REQUIRED_IMAGES = [
        (IMAGE_CHANGE_LINE, "更换线路按钮 (btn_change_line.png)"),
        (IMAGE_LINE_AA1, "线路卡片 AA1 (line_aa1_label.png)"),
        (IMAGE_LINE_AA2, "线路卡片 AA2 (line_aa2_label.png)"),
        (IMAGE_LINE_AA3, "线路卡片 AA3 (line_aa3_label.png)"),
        (IMAGE_FULL_LINE, "满额状态模板 (full_line.png)"),
        (IMAGE_AVAILABLE_LINE, "可连接状态模板 (available_line.png)"),
        (IMAGE_STATUS_CONNECTED, "连接成功状态 (status_connected.png)"),
        (IMAGE_RECHARGE, "充值按钮锚点 (btn_recharge.png)"),
    ]

    def __init__(self):
        self.window = None
        pyautogui.FAILSAFE = True
        self.screen_width, self.screen_height = pyautogui.size()
        # Anti-loop: count consecutive clicks per card (keyed by card name)
        self.click_count = defaultdict(int)

    @staticmethod
    def check_required_files() -> bool:
        """Check if all required screenshot files exist."""
        all_ok = True
        Logger.info("Checking required screenshot files...")
        for file_path, description in VPNController.REQUIRED_IMAGES:
            if Path(file_path).exists():
                Logger.info(f"  [OK] {description}")
            else:
                Logger.error(f"  [MISSING] {description}")
                Logger.error(f"          Expected at: {file_path}")
                all_ok = False
        if not all_ok:
            Logger.error("=" * 50)
            Logger.error("请添加缺失的截图文件到 screenshots/ 目录")
            Logger.error("=" * 50)
        return all_ok

    # ----------------------------------------------------------
    # Debug tools
    # ----------------------------------------------------------
    def _debug_screenshot(self, label: str):
        """Save a full-screen debug screenshot."""
        try:
            ts = datetime.now().strftime("%H%M%S")
            filename = f"debug_{label}_{ts}.png"
            filepath = SCREENSHOTS_DIR / filename
            pyautogui.screenshot(str(filepath))
            Logger.info(f"[DEBUG] Screenshot saved: {filepath}")
        except Exception as e:
            Logger.warning(f"[DEBUG] Screenshot error: {e}")

    # ----------------------------------------------------------
    # Window management
    # ----------------------------------------------------------
    def find_window(self) -> bool:
        """Find and activate the VPN client window."""
        Logger.info(f"Looking for window: '{WINDOW_TITLE}'")
        try:
            windows = gw.getWindowsWithTitle(WINDOW_TITLE)
            if not windows:
                Logger.error(f"Window '{WINDOW_TITLE}' not found")
                return False
            self.window = windows[0]
            if self.window.isMinimized:
                self.window.restore()
            self.window.activate()
            time.sleep(WAIT_SHORT)
            Logger.info(f"Window '{WINDOW_TITLE}' activated")
            return True
        except Exception as e:
            Logger.error(f"Window error: {e}")
            return False

    def go_back(self):
        """Press ESC to return to main page."""
        Logger.info("Going back to main page (ESC)...")
        pyautogui.press("esc")
        time.sleep(WAIT_MEDIUM)

    # ----------------------------------------------------------
    # Core: locateOnScreen with detailed debug output
    # ----------------------------------------------------------
    def _locate_on_screen(self, image_path: str, description: str = "",
                          confidence: float = None, region: tuple = None):
        """
        Find a single image match on screen.
        Returns (Box, confidence) or (None, None).
        Logs matched template + confidence + center point.
        """
        if not image_path:
            return None, None
        img_path = Path(image_path)
        if not img_path.exists():
            Logger.warning(f"Image file not found: '{image_path}'")
            return None, None
        use_conf = confidence if confidence is not None else CONFIDENCE
        try:
            kwargs = {"confidence": use_conf}
            if region:
                kwargs["region"] = region
            location = pyautogui.locateOnScreen(str(img_path), **kwargs)
            if location:
                center = pyautogui.center(location)
                Logger.info(f"  Matched: '{description}'"
                           f" | Box: {location}"
                           f" | Center: ({center.x}, {center.y})"
                           f" | Confidence: {use_conf}")
            else:
                Logger.info(f"  '{description}' — not found")
            return location, use_conf
        except pyautogui.ImageNotFoundException:
            Logger.info(f"  '{description}' — not found")
            return None, use_conf
        except Exception as e:
            Logger.warning(f"  '{description}' — error: {e}")
            return None, use_conf

    def _locate_all_on_screen(self, image_path: str, description: str = "",
                              confidence: float = None) -> list:
        """
        Find ALL matches of an image on screen.
        Returns list of (Box, confidence) sorted top-to-bottom.
        """
        if not image_path:
            return []
        img_path = Path(image_path)
        if not img_path.exists():
            Logger.warning(f"Image file not found: '{image_path}'")
            return []
        use_conf = confidence if confidence is not None else CONFIDENCE
        try:
            locations = list(pyautogui.locateAllOnScreen(str(img_path), confidence=use_conf))
            locations.sort(key=lambda loc: loc[1])  # sort by y
            Logger.info(f"  Found {len(locations)}x '{description}'")
            for idx, loc in enumerate(locations):
                center = pyautogui.center(loc)
                Logger.info(f"    #{idx}: Box={loc} Center=({center.x},{center.y})"
                           f" Confidence={use_conf}")
            return [(loc, use_conf) for loc in locations]
        except pyautogui.ImageNotFoundException:
            Logger.info(f"  '{description}' — 0 matches")
            return []
        except Exception as e:
            Logger.warning(f"  '{description}' — error: {e}")
            return []

    # ----------------------------------------------------------
    # Page status helpers
    # ----------------------------------------------------------
    def is_page_loaded(self) -> bool:
        """Check if line selection page loaded (充值 anchor)."""
        loc, _ = self._locate_on_screen(IMAGE_RECHARGE, "充值 anchor",
                                        confidence=CONFIDENCE_ANCHOR)
        return loc is not None

    def is_connected(self) -> bool:
        """Check if VPN is connected."""
        Logger.info("Checking connection status...")
        loc, _ = self._locate_on_screen(IMAGE_STATUS_CONNECTED, "连接成功",
                                        confidence=CONFIDENCE_CONNECTED)
        if loc:
            Logger.success("  status_connected.png MATCHED → VPN is connected")
        else:
            Logger.info("  status_connected.png NOT found → not connected yet")
        return loc is not None

    def click_change_line(self) -> bool:
        """Click the '更换线路' button."""
        Logger.info("Clicking '更换线路' button...")
        loc, conf = self._locate_on_screen(IMAGE_CHANGE_LINE, "更换线路",
                                           confidence=CONFIDENCE)
        if not loc:
            Logger.error("[ERROR] button image not found: 更换线路")
            return False
        center = pyautogui.center(loc)
        try:
            pyautogui.moveTo(center, duration=0.2)
            pyautogui.click()
            Logger.info(f"Clicked '更换线路' at center ({center.x}, {center.y})")
            self._debug_screenshot("after_click_change_line")
            time.sleep(WAIT_SHORT)
            return True
        except Exception as e:
            Logger.warning(f"Click failed: {e}")
            return False

    def _get_card_region(self, card_box: tuple, margin: int = 20) -> tuple:
        """
        Expand the card's box slightly to create a search region
        for state templates. Returns (left, top, width, height).
        """
        left, top, width, height = card_box
        r_left = max(0, left - margin)
        r_top = max(0, top - margin)
        r_width = min(width + 2 * margin, self.screen_width - r_left)
        r_height = min(height + 2 * margin, self.screen_height - r_top)
        return (r_left, r_top, r_width, r_height)

    def _is_card_full(self, card_box: tuple) -> bool:
        """
        Check if a card is in 'full' state by looking for full_line.png
        in the card's region.
        """
        region = self._get_card_region(card_box)
        loc, _ = self._locate_on_screen(IMAGE_FULL_LINE, "满额状态(full_line)",
                                        confidence=CONFIDENCE_LINE_STATE,
                                        region=region)
        if loc:
            Logger.info("  → Card is FULL (full_line matched)")
            return True
        Logger.info("  → Card does NOT match full_line")
        return False

    def _is_card_available(self, card_box: tuple) -> bool:
        """
        Check if a card is in 'available' state by looking for
        available_line.png in the card's region.
        """
        region = self._get_card_region(card_box)
        loc, _ = self._locate_on_screen(IMAGE_AVAILABLE_LINE, "可连接状态(available_line)",
                                        confidence=CONFIDENCE_LINE_STATE,
                                        region=region)
        if loc:
            Logger.info("  → Card is AVAILABLE (available_line matched)")
            return True
        Logger.info("  → Card does NOT match available_line")
        return False

    def _click_card_center(self, card_box, card_name: str) -> bool:
        """
        Click the center of a card. Updates anti-loop counter.
        """
        center = pyautogui.center(card_box)
        try:
            pyautogui.moveTo(center, duration=0.2)
            pyautogui.click()
            Logger.info(f"Clicked card '{card_name}' at center ({center.x}, {center.y})")
            self.click_count[card_name] += 1
            Logger.info(f"  [Anti-loop] '{card_name}' clicked {self.click_count[card_name]}/"
                       f"{ANTI_LOOP_MAX} times this session")
            self._debug_screenshot(f"clicked_{card_name.replace('-','')}")
            time.sleep(WAIT_SHORT)
            return True
        except Exception as e:
            Logger.warning(f"Click failed for '{card_name}': {e}")
            return False

    def _is_card_looped(self, card_name: str) -> bool:
        """Check if a card has been clicked too many times (anti-loop)."""
        if self.click_count[card_name] >= ANTI_LOOP_MAX:
            Logger.warning(f"  [Anti-loop] '{card_name}' reached max clicks "
                          f"({ANTI_LOOP_MAX}), skipping")
            return True
        return False

    # ----------------------------------------------------------
    # Main connection logic — Card State Recognition
    # ----------------------------------------------------------
    def auto_connect(self) -> bool:
        """
        Visual State Card Recognition System:

        1. Find window → click "更换线路"
        2. For each of the 3 line cards (AA1, AA2, AA3):
           a. Find card on screen via its full-card template
           b. Check if full_line.png matches in card region → skip
           c. Check if available_line.png matches in card region → click
           d. Wait → check connected
        3. Anti-loop: skip card after ANTI_LOOP_MAX failed clicks
        4. Retry: go back → re-enter line page
        """
        if not self.find_window():
            return False

        for attempt in range(1, MAX_RETRIES + 1):
            Logger.info(f"=== Attempt {attempt}/{MAX_RETRIES} ===")
            self.find_window()

            # ---- Step 1: Click "更换线路" ----
            Logger.info("[Step 1] Clicking '更换线路'...")
            if not self.click_change_line():
                Logger.warning("Cannot find '更换线路', retrying...")
                time.sleep(WAIT_BEFORE_RETRY)
                continue

            # ---- Step 2: Wait for page ----
            Logger.info("[Step 2] Waiting for line selection page...")
            time.sleep(WAIT_MEDIUM)
            if not self.is_page_loaded():
                Logger.warning("Page not fully loaded, waiting more...")
                time.sleep(WAIT_MEDIUM)

            # ---- Step 3: Scan each line card ----
            Logger.info("[Step 3] Scanning line card states...")
            connected = False

            for card_image, card_name in self.LINE_CARDS:
                Logger.info(f"--- Checking card: {card_name} ---")

                # 3a. Find this specific card on screen
                card_results = self._locate_all_on_screen(
                    card_image, card_name, confidence=CONFIDENCE_LINE_CARD
                )
                if not card_results:
                    Logger.warning(f"Card '{card_name}' not found on screen, skipping")
                    continue

                # 3b. Check each occurrence (usually 1, but handle multiple)
                for card_box, card_conf in card_results:
                    ctr = pyautogui.center(card_box)
                    Logger.info(f"  Card '{card_name}' found at center=({ctr.x},{ctr.y})")

                    # Anti-loop check
                    if self._is_card_looped(card_name):
                        continue

                    # 3c. Priority: check full_line first
                    Logger.info(f"  [State check] Is '{card_name}' FULL?")
                    if self._is_card_full(card_box):
                        Logger.warning(f"  → '{card_name}' is FULL, skipping")
                        continue

                    # 3d. Check if available
                    Logger.info(f"  [State check] Is '{card_name}' AVAILABLE?")
                    if not self._is_card_available(card_box):
                        Logger.warning(f"  → '{card_name}' not available (no template match)")
                        continue

                    # 3e. Click card center
                    Logger.success(f"  → '{card_name}' is AVAILABLE, clicking card center...")
                    clicked = self._click_card_center(card_box, card_name)
                    if not clicked:
                        continue

                    # 3f. Wait for connection
                    time.sleep(WAIT_CONNECT)

                    if self.is_connected():
                        Logger.success(f"'{card_name}' connected!")
                        connected = True
                        break
                    else:
                        Logger.warning(f"'{card_name}' clicked but connection not confirmed")

                if connected:
                    break

            # ---- Step 4: Handle result ----
            if connected:
                Logger.info("[Step 4] Final verification...")
                time.sleep(WAIT_MEDIUM)
                if self.is_connected():
                    Logger.success("=== VPN CONNECTED ===")
                    return True

            # ---- Step 5: Refresh by going back and retrying ----
            Logger.info("[Step 5] No line connected, going back and retrying...")
            self.go_back()
            Logger.info(f"Waiting {WAIT_AFTER_REFRESH}s...")
            time.sleep(WAIT_AFTER_REFRESH)

        Logger.error(f"Failed after {MAX_RETRIES} attempts")
        return False

    @staticmethod
    def open_target_url():
        """Open target URL in default browser."""
        Logger.info(f"Opening browser: {TARGET_URL}")
        try:
            webbrowser.open(TARGET_URL)
            Logger.success(f"Browser opened: {TARGET_URL}")
        except Exception as e:
            Logger.error(f"Failed to open browser: {e}")
