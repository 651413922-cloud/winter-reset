"""
Core VPN controller module.
Handles window management, line status detection, and auto-connection
via direct image recognition (NO offset-based clicking).

Click strategy: Search for "普通用户"/"永久用户" tag image directly
on the full screen, then click its center to trigger connection.
"""

import time
import webbrowser
from datetime import datetime
from pathlib import Path

import pyautogui
import pygetwindow as gw

from config import (
    SCREENSHOTS_DIR,
    WINDOW_TITLE,
    IMAGE_CHANGE_LINE,
    IMAGE_TAG_NORMAL,
    IMAGE_TAG_FOREVER,
    IMAGE_STATUS_FULL,
    IMAGE_STATUS_CONNECTED,
    IMAGE_RECHARGE,
    CONFIDENCE,
    CONFIDENCE_TAG,
    CONFIDENCE_FULL,
    CONFIDENCE_ANCHOR,
    CONFIDENCE_CONNECTED,
    WAIT_SHORT,
    WAIT_MEDIUM,
    WAIT_REFRESH,
    WAIT_CONNECT,
    WAIT_BEFORE_RETRY,
    MAX_RETRIES,
    TARGET_URL,
)
from logger import Logger


class VPNController:
    """Controls the VPN client application via UI automation."""

    # Tags to search for, in priority order (AA1/AA2 first, then AA3)
    TAG_SEARCH_ORDER = [
        (IMAGE_TAG_NORMAL, "普通用户"),
        (IMAGE_TAG_FOREVER, "永久用户"),
    ]

    REQUIRED_IMAGES = [
        (IMAGE_CHANGE_LINE, "更换线路按钮 (btn_change_line.png)"),
        (IMAGE_TAG_NORMAL, "普通用户标签 (tag_normal.png)"),
        (IMAGE_TAG_FOREVER, "永久用户标签 (tag_forever.png)"),
        (IMAGE_STATUS_FULL, "红色100%状态 (status_full.png)"),
        (IMAGE_STATUS_CONNECTED, "连接成功状态 (status_connected.png)"),
        (IMAGE_RECHARGE, "充值按钮锚点 (btn_recharge.png)"),
    ]

    def __init__(self):
        self.window = None
        pyautogui.FAILSAFE = True
        self.screen_width, self.screen_height = pyautogui.size()

    @staticmethod
    def check_required_files() -> bool:
        """Check if all required screenshot files exist before starting."""
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
            Logger.error("缺少必须的截图文件！请在 screenshots/ 目录下添加。")
            Logger.error("=" * 50)
        return all_ok

    def _debug_screenshot(self, label: str):
        """Save a full-screen screenshot for debugging."""
        try:
            ts = datetime.now().strftime("%H%M%S")
            filename = f"debug_{label}_{ts}.png"
            filepath = SCREENSHOTS_DIR / filename
            pyautogui.screenshot(str(filepath))
            Logger.info(f"[DEBUG] Screenshot saved: {filepath}")
        except Exception as e:
            Logger.warning(f"[DEBUG] Failed to save screenshot: {e}")

    def find_window(self) -> bool:
        """Find and activate the VPN client window."""
        Logger.info(f"Looking for window: '{WINDOW_TITLE}'")
        try:
            windows = gw.getWindowsWithTitle(WINDOW_TITLE)
            if not windows:
                Logger.error(f"Window '{WINDOW_TITLE}' not found. Is the app running?")
                return False
            self.window = windows[0]
            if self.window.isMinimized:
                self.window.restore()
            self.window.activate()
            time.sleep(WAIT_SHORT)
            Logger.info(f"Window '{WINDOW_TITLE}' activated")
            return True
        except Exception as e:
            Logger.error(f"Failed to find/activate window: {e}")
            return False

    def go_back(self):
        """Press ESC to go back to main page."""
        Logger.info("Going back to main page (ESC)...")
        pyautogui.press("esc")
        time.sleep(WAIT_MEDIUM)

    # ----------------------------------------------------------
    # Full-screen image detection
    # ----------------------------------------------------------
    def _find_image(self, image_path: str, description: str = "",
                    confidence: float = None, region: tuple = None):
        """Find a single image match on screen. Returns Box or None."""
        if not image_path:
            return None
        img_path = Path(image_path)
        if not img_path.exists():
            Logger.warning(f"Image file not found: '{image_path}'")
            return None
        use_confidence = confidence if confidence is not None else CONFIDENCE
        try:
            kwargs = {"confidence": use_confidence}
            if region:
                kwargs["region"] = region
            location = pyautogui.locateOnScreen(str(img_path), **kwargs)
            if location:
                Logger.info(f"Found '{description}' at {location}")
            else:
                Logger.info(f"'{description}' not found")
            return location
        except pyautogui.ImageNotFoundException:
            Logger.info(f"'{description}' not found")
            return None
        except Exception as e:
            Logger.warning(f"Error locating '{description}': {e}")
            return None

    def _find_all_images(self, image_path: str, description: str = "",
                         confidence: float = None) -> list:
        """Find ALL matching occurrences of an image on screen.
        Returns list of Box locations, sorted top-to-bottom by y coordinate."""
        if not image_path:
            return []
        img_path = Path(image_path)
        if not img_path.exists():
            Logger.warning(f"Image file not found: '{image_path}'")
            return []
        use_confidence = confidence if confidence is not None else CONFIDENCE
        try:
            locations = list(pyautogui.locateAllOnScreen(str(img_path), confidence=use_confidence))
            # Sort by y coordinate (top-to-bottom)
            locations.sort(key=lambda loc: loc[1])
            Logger.info(f"Found {len(locations)} occurrences of '{description}'")
            for idx, loc in enumerate(locations):
                Logger.info(f"  #{idx}: {loc}")
            return locations
        except pyautogui.ImageNotFoundException:
            Logger.info(f"No occurrences of '{description}' found")
            return []
        except Exception as e:
            Logger.warning(f"Error locating all '{description}': {e}")
            return []

    def _click_box_center(self, box, description: str = "") -> bool:
        """Click the center of a given Box."""
        if not box:
            return False
        center = pyautogui.center(box)
        try:
            pyautogui.moveTo(center, duration=0.2)
            pyautogui.click()
            Logger.info(f"Clicked '{description}' at center {center}")
            self._debug_screenshot(f"click_{description.replace(' ','')}")
            time.sleep(WAIT_SHORT)
            return True
        except Exception as e:
            Logger.warning(f"Click failed for '{description}': {e}")
            return False

    # ----------------------------------------------------------
    # Page status detection
    # ----------------------------------------------------------
    def is_page_loaded(self) -> bool:
        r"""Check if line selection page loaded by looking for '充值' anchor."""
        return self._find_image(IMAGE_RECHARGE, "充值 anchor",
                                confidence=CONFIDENCE_ANCHOR) is not None

    def is_connected(self) -> bool:
        """Check if VPN is connected by looking for '连接成功' text."""
        Logger.info("Checking connection status...")
        return self._find_image(IMAGE_STATUS_CONNECTED, "连接成功",
                                confidence=CONFIDENCE_CONNECTED) is not None

    # ----------------------------------------------------------
    # Tag-based line selection (direct full-screen search)
    # ----------------------------------------------------------
    def _is_tag_near_full_status(self, tag_box) -> bool:
        """
        Check if there is a red '100%' near the given tag.
        Search region: to the LEFT of the tag (percentage usually appears
        between line name and tag).
        """
        left, top, width, height = tag_box

        # Search left of tag, ~400px wide area
        search_left = max(0, left - 500)
        search_top = max(0, top - 5)
        search_width = 500  # from search_left to just left of tag
        search_height = min(height + 10, self.screen_height - search_top)

        if search_left + search_width > self.screen_width:
            search_width = self.screen_width - search_left
        if search_width < 50 or search_height < 10:
            return False

        Logger.info(f"Checking '100%' near tag: region=({search_left}, {search_top}, "
                     f"{search_width}, {search_height})")

        try:
            location = pyautogui.locateOnScreen(
                str(Path(IMAGE_STATUS_FULL)),
                region=(search_left, search_top, search_width, search_height),
                confidence=CONFIDENCE_FULL
            )
            if location:
                Logger.info(f"Red '100%' found near tag → line FULL")
                return True
            Logger.info("No '100%' near tag → line AVAILABLE")
            return False
        except pyautogui.ImageNotFoundException:
            Logger.info("No '100%' near tag → line AVAILABLE")
            return False
        except Exception as e:
            Logger.warning(f"Error checking full status near tag: {e}")
            return False

    def click_change_line(self) -> bool:
        """Click the '更换线路' button on the main page."""
        Logger.info("Clicking '更换线路' button...")
        location = self._find_image(IMAGE_CHANGE_LINE, "更换线路",
                                    confidence=CONFIDENCE)
        if not location:
            Logger.error("[ERROR] button image not found: 更换线路")
            return False
        return self._click_box_center(location, "更换线路")

    # ----------------------------------------------------------
    # Main connection logic
    # ----------------------------------------------------------
    def auto_connect(self) -> bool:
        """
        Main automation loop (pure image-based, no name text):

        1. Find window
        2. Click "更换线路" → enter line list
        3. Search ALL occurrences of "普通用户" tag on screen
           → For each (top-to-bottom):
              - Check if "100%" exists near it
              - If not FULL → click tag center → wait → check connected
        4. If none worked → search "永久用户" tag → same logic
        5. If none worked → go back (ESC) → retry
        """
        if not self.find_window():
            return False

        for attempt in range(1, MAX_RETRIES + 1):
            Logger.info(f"--- Attempt {attempt}/{MAX_RETRIES} ---")
            self.find_window()

            # --------------------------------------------------
            # Step 1: Click "更换线路"
            # --------------------------------------------------
            Logger.info("Step 1: Clicking '更换线路'...")
            if not self.click_change_line():
                Logger.warning("Could not find '更换线路', retrying...")
                time.sleep(WAIT_BEFORE_RETRY)
                continue

            # --------------------------------------------------
            # Step 2: Wait for page
            # --------------------------------------------------
            Logger.info("Step 2: Waiting for line selection page...")
            time.sleep(WAIT_MEDIUM)
            if not self.is_page_loaded():
                Logger.warning("Page not fully loaded, waiting more...")
                time.sleep(WAIT_MEDIUM)

            # --------------------------------------------------
            # Step 3: Search tags in priority order
            # --------------------------------------------------
            Logger.info("Step 3: Searching for available line tags...")
            connected = False

            for tag_image, tag_desc in self.TAG_SEARCH_ORDER:
                Logger.info(f"Searching all '{tag_desc}' tags on screen...")
                tag_locations = self._find_all_images(tag_image, tag_desc,
                                                      confidence=CONFIDENCE_TAG)

                for idx, tag_box in enumerate(tag_locations):
                    Logger.info(f"Checking '{tag_desc}' tag #{idx} at y={tag_box[1]}")

                    # Check if this tag's line is FULL
                    if self._is_tag_near_full_status(tag_box):
                        Logger.info(f"Tag #{idx} line is FULL, skipping...")
                        continue

                    # Available → click tag center
                    Logger.success(f"Tag #{idx} appears AVAILABLE → clicking...")
                    clicked = self._click_box_center(tag_box, f"{tag_desc} tag #{idx}")

                    if not clicked:
                        Logger.warning(f"Click failed for tag #{idx}")
                        continue

                    # Wait for connection
                    time.sleep(WAIT_CONNECT)

                    if self.is_connected():
                        Logger.success(f"Connected via '{tag_desc}' tag #{idx}!")
                        connected = True
                        break
                    else:
                        Logger.warning(f"Clicked tag #{idx} but not connected yet")

                if connected:
                    break

            # --------------------------------------------------
            # Step 4: Success
            # --------------------------------------------------
            if connected:
                Logger.info("Step 4: Final verification...")
                time.sleep(WAIT_MEDIUM)
                if self.is_connected():
                    Logger.success("VPN connected!")
                    return True

            # --------------------------------------------------
            # Step 5: No line worked → go back and retry
            # --------------------------------------------------
            Logger.info("No line connected; going back and retrying...")
            self.go_back()
            Logger.info(f"Waiting {WAIT_REFRESH}s...")
            time.sleep(WAIT_REFRESH)

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
