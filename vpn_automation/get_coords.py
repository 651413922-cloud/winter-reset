"""
Helper tool: Display mouse coordinates and take screenshots for debugging.
Use this to find button positions and capture reference images for image recognition.

Usage:
    python get_coords.py              # Show mouse coordinates in real-time
    python get_coords.py --snapshot   # Take a screenshot of the VPN window
    python get_coords.py --capture    # Capture a region and save as reference image
"""

import sys
import time
import os
from datetime import datetime

import pyautogui
import pygetwindow as gw

from config import WINDOW_TITLE, SCREENSHOTS_DIR
from logger import Logger


def show_coordinates():
    """Display real-time mouse coordinates. Press Ctrl+C to exit."""
    Logger.info("Mouse Coordinate Tracker")
    Logger.info("Move your mouse over the VPN window to find button positions")
    Logger.info("Press Ctrl+C to stop")
    print("-" * 50)
    print(f"{'X':>5} {'Y':>5} {'R':>4} {'G':>4} {'B':>4}  Description")
    print("-" * 50)

    try:
        while True:
            x, y = pyautogui.position()
            # Get pixel color at mouse position
            try:
                pixel = pyautogui.pixel(x, y)
                r, g, b = pixel
            except Exception:
                r, g, b = 0, 0, 0

            print(f"\r{x:>5} {y:>5} {r:>4} {g:>4} {b:>4}  (move mouse)", end="")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n")
        Logger.info("Coordinate tracking stopped")


def take_snapshot():
    """Take a screenshot of the VPN window and save it."""
    Logger.info(f"Looking for window: '{WINDOW_TITLE}'")

    try:
        windows = gw.getWindowsWithTitle(WINDOW_TITLE)
        if not windows:
            Logger.error(f"Window '{WINDOW_TITLE}' not found")
            return

        window = windows[0]

        if window.isMinimized:
            window.restore()
            time.sleep(0.5)

        # Take screenshot of the window region
        screenshot = pyautogui.screenshot(region=(
            window.left, window.top, window.width, window.height
        ))

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"snapshot_{timestamp}.png"
        filepath = os.path.join(SCREENSHOTS_DIR, filename)
        screenshot.save(filepath)

        Logger.success(f"Snapshot saved: {filepath}")
        Logger.info(f"Window position: left={window.left}, top={window.top}")
        Logger.info(f"Window size: {window.width}x{window.height}")

    except Exception as e:
        Logger.error(f"Failed to take snapshot: {e}")


def capture_region():
    """
    Interactive region capture.
    Move mouse to top-left corner, press Enter.
    Move mouse to bottom-right corner, press Enter.
    Saves the region as a reference image.
    """
    # keyboard library is optional; we use input() for simplicity

    Logger.info("Interactive Region Capture")
    Logger.info("Step 1: Move mouse to TOP-LEFT corner of the button/area")
    Logger.info("         Then press ENTER to record position")
    input("Press ENTER to record top-left corner...")
    x1, y1 = pyautogui.position()
    Logger.info(f"Top-left recorded: ({x1}, {y1})")

    Logger.info("Step 2: Move mouse to BOTTOM-RIGHT corner of the button/area")
    Logger.info("         Then press ENTER to record position")
    input("Press ENTER to record bottom-right corner...")
    x2, y2 = pyautogui.position()
    Logger.info(f"Bottom-right recorded: ({x2}, {y2})")

    # Calculate region
    left = min(x1, x2)
    top = min(y1, y2)
    width = abs(x2 - x1)
    height = abs(y2 - y1)

    Logger.info(f"Region: left={left}, top={top}, width={width}, height={height}")

    # Take screenshot of the region
    screenshot = pyautogui.screenshot(region=(left, top, width, height))

    # Ask for a name
    name = input("Enter a name for this capture (e.g., 'btn_connect'): ").strip()
    if not name:
        name = f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    filename = f"{name}.png"
    filepath = os.path.join(SCREENSHOTS_DIR, filename)
    screenshot.save(filepath)

    Logger.success(f"Region saved: {filepath}")
    Logger.info(f"To use this image, add to config.py: IMAGE_{name.upper()} = '{filepath}'")


def print_help():
    """Print usage information."""
    print("""
VPN Automation - Helper Tools
=============================

Usage:
    python get_coords.py              Show real-time mouse coordinates
    python get_coords.py --snapshot   Take a screenshot of the VPN window
    python get_coords.py --capture    Capture a region as reference image
    python get_coords.py --help       Show this help message

Tips:
    1. Use --snapshot to capture the entire VPN window
    2. Use --capture to crop button images for image recognition
    3. Use the default mode to find exact button coordinates
    4. Save captured images to the screenshots/ folder
    5. Update config.py with the correct image paths
    """)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        show_coordinates()
    elif sys.argv[1] == "--snapshot":
        take_snapshot()
    elif sys.argv[1] == "--capture":
        capture_region()
    elif sys.argv[1] in ("--help", "-h"):
        print_help()
    else:
        print(f"Unknown option: {sys.argv[1]}")
        print_help()
