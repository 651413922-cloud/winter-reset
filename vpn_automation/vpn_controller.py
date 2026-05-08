"""
Core VPN controller module.
Handles window management, line status detection, and auto-connection via image recognition.

Logic:
  1. Click "更换线路" to enter line selection page
  2. Check three free lines by reverse-matching their RED (unavailable) screenshots:
     - If RED image is NOT found → line is available (blue/yellow) → click it → auto-connect
     - If RED image IS found → line is unavailable → check next
  3. If all three are red → wait → go back → retry
  4. After clicking a line → verify connection status
"""

import os
import time
import webbrowser

import pyautogui
import pygetwindow as gw

from config import (
    WINDOW_TITLE,
    IMAGE_CHANGE_LINE,
    IMAGE_LINE_AA1_RED,
    IMAGE_LINE_AA2_RED,
    IMAGE_LINE_AA3_RED,
    IMAGE_STATUS_CONNECTED,
    CONFIDENCE,
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

    # List of free lines to check: (red_image_path, display_name)
    FREE_LINES = [
        (IMAGE_LINE_AA1_RED, "美国节点-免费试用AA1"),
        (IMAGE_LINE_AA2_RED, "美国节点-免费试用AA2"),
        (IMAGE_LINE_AA3_RED, "美国节点-永久用户AA3"),
    ]

    def __init__(self):
        self.window = None
        # Cache for last known positions of line buttons
        self._line_positions = {}
        # Fail-safe: move mouse to top-left corner to abort
        pyautogui.FAILSAFE = True

    # ----------------------------------------------------------
    # Window management
    # ----------------------------------------------------------
    def find_window(self) -> bool:
        """
        Find and activate the VPN client window.
        Returns True if window is found and activated.
        """
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

    # ----------------------------------------------------------
    # Image-based element detection
    # ----------------------------------------------------------
    def _find_image_on_screen(self, image_path: str, description: str = ""):
        """
        Try to locate an image on screen using PyAutoGUI.
        Returns (left, top, width, height) tuple if found, None otherwise.
        """
        if not image_path or not os.path.exists(image_path):
            Logger.warning(f"Image file not found: '{image_path}' for '{description}'")
            return None

        try:
            location = pyautogui.locateOnScreen(image_path, confidence=CONFIDENCE)
            if location:
                Logger.info(f"Found '{description}' at {location}")
                return location
            else:
                Logger.info(f"'{description}' not found on screen")
                return None
        except pyautogui.ImageNotFoundException:
            Logger.info(f"'{description}' not found on screen (ImageNotFoundException)")
            return None
        except Exception as e:
            Logger.warning(f"Error locating '{description}': {e}")
            return None

    def _click_image(self, image_path: str, description: str = "") -> bool:
        """
        Find an image on screen and click its center.
        Returns True if clicked successfully.
        """
        location = self._find_image_on_screen(image_path, description)
        if location:
            center = pyautogui.center(location)
            pyautogui.click(center)
            Logger.info(f"Clicked '{description}' at {center}")
            time.sleep(WAIT_SHORT)
            return True
        return False

    # ----------------------------------------------------------
    # Line status detection (reverse matching)
    # ----------------------------------------------------------
    def _is_line_available(self, red_image_path: str, line_name: str) -> tuple:
        """
        Check if a line is available using reverse matching.
        
        Logic:
        - We only have the RED (unavailable) version of the line screenshot.
        - If the RED image is NOT found on screen → the line has changed color
          (to blue/yellow) → it's AVAILABLE.
        - If the RED image IS found → the line is still red → UNAVAILABLE.
        
        Returns: (is_available: bool, position: tuple or None)
        """
        location = self._find_image_on_screen(red_image_path, f"{line_name} (red/unavailable)")
        
        if location is None:
            # RED image not found → line is NOT red anymore → it's available!
            Logger.info(f"'{line_name}' is AVAILABLE (red image not found)")
            # Use cached position if available
            cached_pos = self._line_positions.get(line_name)
            return (True, cached_pos)
        else:
            # RED image found → line is still red → unavailable
            # Cache the position for later use when it becomes available
            self._line_positions[line_name] = location
            Logger.info(f"'{line_name}' is UNAVAILABLE (still red)")
            return (False, None)

    def _click_available_line(self) -> bool:
        """
        Check all three free lines and click the first available one.
        Returns True if a line was clicked.
        """
        for red_image_path, line_name in self.FREE_LINES:
            is_available, cached_pos = self._is_line_available(red_image_path, line_name)
            
            if is_available:
                # Line is available - click it!
                # Since the line changed color, the red screenshot won't match.
                # Strategy: try to find the line by its red screenshot with very low confidence,
                # or use the cached position from a previous detection.
                
                clicked = False
                
                # Method 1: Try to find the red screenshot with very low confidence
                # (the button shape/position is the same, only color changed)
                try:
                    low_conf_location = pyautogui.locateOnScreen(red_image_path, confidence=0.3)
                    if low_conf_location:
                        center = pyautogui.center(low_conf_location)
                        pyautogui.click(center)
                        Logger.info(f"Clicked available line '{line_name}' (low confidence) at {center}")
                        time.sleep(WAIT_SHORT)
                        clicked = True
                except Exception:
                    pass
                
                # Method 2: Use cached position from when the line was red
                if not clicked and cached_pos:
                    center = pyautogui.center(cached_pos)
                    pyautogui.click(center)
                    Logger.info(f"Clicked available line '{line_name}' (cached position) at {center}")
                    time.sleep(WAIT_SHORT)
                    clicked = True
                
                # Method 3: Try to find the line by its name text using OCR-like approach
                # (take a screenshot of the line area and check pixel colors)
                if not clicked:
                    Logger.warning(f"Could not click '{line_name}' via image matching, trying screenshot region...")
                    clicked = self._click_line_by_region(line_name, red_image_path)
                
                if clicked:
                    return True
                else:
                    Logger.error(f"Failed to click available line '{line_name}'")
        
        return False

    def _click_line_by_region(self, line_name: str, red_image_path: str) -> bool:
        """
        Fallback: take a screenshot of the window and try to find the line
        by scanning for non-red pixels in the line list area.
        """
        if not self.window:
            return False
        
        try:
            # Take a screenshot of the VPN window
            screenshot = pyautogui.screenshot(region=(
                self.window.left, self.window.top, 
                self.window.width, self.window.height
            ))
            
            # Try to find the red image with very low confidence on the screenshot
            try:
                location = pyautogui.locateOnScreen(red_image_path, confidence=0.3)
                if location:
                    # Adjust coordinates relative to screen
                    center = pyautogui.center(location)
                    pyautogui.click(center)
                    Logger.info(f"Clicked '{line_name}' via screenshot region at {center}")
                    time.sleep(WAIT_SHORT)
                    return True
            except Exception:
                pass
                
        except Exception as e:
            Logger.warning(f"Screenshot region click failed: {e}")
        
        return False

    # ----------------------------------------------------------
    # Connection status detection
    # ----------------------------------------------------------
    def is_connected(self) -> bool:
        """
        Check if the VPN is connected by looking for '已连接' status.
        """
        Logger.info("Checking connection status...")
        location = self._find_image_on_screen(IMAGE_STATUS_CONNECTED, "status_connected (已连接)")
        return location is not None

    # ----------------------------------------------------------
    # Actions
    # ----------------------------------------------------------
    def click_change_line(self) -> bool:
        """Click the '更换线路' button on the main page."""
        Logger.info("Clicking '更换线路' button...")
        return self._click_image(IMAGE_CHANGE_LINE, "change line button (更换线路)")

    # ----------------------------------------------------------
    # Main automation loop
    # ----------------------------------------------------------
    def auto_connect(self) -> bool:
        """
        Main automation loop:
        1. Find window
        2. Loop up to MAX_RETRIES times:
           a. Click "更换线路" to enter line selection
           b. Check three free lines (reverse match red images)
           c. If an available line is found → click it → verify connection
           d. If all red → wait → retry
        3. On success → open browser
        """
        if not self.find_window():
            return False

        for attempt in range(1, MAX_RETRIES + 1):
            Logger.info(f"--- Attempt {attempt}/{MAX_RETRIES} ---")

            # Re-activate window
            self.find_window()

            # Check if already connected
            if self.is_connected():
                Logger.success("VPN already connected!")
                return True

            # Step 1: Click "更换线路" to enter line selection
            Logger.info("Step 1: Entering line selection page...")
            if not self.click_change_line():
                Logger.warning("Could not find '更换线路' button, retrying...")
                time.sleep(WAIT_BEFORE_RETRY)
                continue

            time.sleep(WAIT_MEDIUM)  # Wait for page to load

            # Step 2: Check free lines and click the first available one
            Logger.info("Step 2: Checking free lines status...")
            line_clicked = self._click_available_line()

            if line_clicked:
                # Step 3: Wait for auto-connection and verify
                Logger.info(f"Step 3: Waiting {WAIT_CONNECT}s for auto-connection...")
                time.sleep(WAIT_CONNECT)

                if self.is_connected():
                    Logger.success("VPN connected!")
                    return True
                else:
                    Logger.warning("Connection may have failed, retrying...")
                    time.sleep(WAIT_BEFORE_RETRY)
            else:
                # All three lines are red (unavailable)
                Logger.info("All three free lines are unavailable (red), refreshing...")
                Logger.info(f"Waiting {WAIT_REFRESH}s before retry...")
                time.sleep(WAIT_REFRESH)

        Logger.error(f"Failed to connect after {MAX_RETRIES} attempts")
        return False

    # ----------------------------------------------------------
    # Post-connection actions
    # ----------------------------------------------------------
    @staticmethod
    def open_target_url():
        """Open the target URL in the default browser."""
        Logger.info(f"Opening browser: {TARGET_URL}")
        try:
            webbrowser.open(TARGET_URL)
            Logger.success(f"Browser opened: {TARGET_URL}")
        except Exception as e:
            Logger.error(f"Failed to open browser: {e}")
