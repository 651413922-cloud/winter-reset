"""
Desktop click test for the GitHub folder icon.

Usage:
    cd vpn_automation
    python test_click_desktop.py

What it does:
  1. Shows the desktop (Win+D)
  2. Prompts you to move the mouse over the Desktop "GitHub" folder icon and press ENTER
  3. Performs several move+click attempts on that position and saves after-click debug screenshots
  4. Restores the previous window layout (Win+D again)

Notes:
  - Run the script as Administrator if clicks previously failed.
  - Keep the console open to see logs and debug screenshot filenames.
"""
import time
from datetime import datetime
from pathlib import Path
import pyautogui

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

def main():
    print("="*40)
    print("Desktop GitHub Folder Click Test")
    print("="*40)
    print("This test will show the desktop, let you point at the GitHub icon,")
    print("then perform automated clicks on that location.")
    print("Move mouse to TOP-LEFT corner to abort (PyAutoGUI failsafe).")
    print()

    # Show desktop
    print("[INFO] Showing desktop (Win+D)...")
    try:
        pyautogui.hotkey('win', 'd')
    except Exception as e:
        print(f"[WARN] hotkey failed: {e}")
    time.sleep(0.8)

    input("Move your mouse over the GitHub folder icon on the desktop, then press ENTER to record position...")

    x, y = pyautogui.position()
    print(f"[INFO] Recorded target position: ({x}, {y})")

    # Perform multiple clicks with small variations
    offsets = [(0,0), (3,0), (-3,0), (0,3)]
    for i, (dx, dy) in enumerate(offsets, start=1):
        tx = x + dx
        ty = y + dy
        print(f"[INFO] Attempt {i}: moving to ({tx},{ty}) and clicking...")
        try:
            pyautogui.moveTo(tx, ty, duration=0.2)
            pyautogui.click()
        except Exception as exc:
            print(f"[ERROR] Click attempt failed: {exc}")
        time.sleep(0.8)
        # Save after-click debug screenshot
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = SCREENSHOTS_DIR / f"debug_afterclick_desktop_{i}_{ts}.png"
        try:
            pyautogui.screenshot(str(out))
            print(f"[DEBUG] Saved after-click screenshot: {out}")
        except Exception as exc:
            print(f"[WARN] Failed to save screenshot: {exc}")

    # Restore previous windows (toggle desktop)
    print("[INFO] Restoring windows (Win+D)...")
    try:
        pyautogui.hotkey('win', 'd')
    except Exception as e:
        print(f"[WARN] hotkey failed: {e}")

    print("[INFO] Desktop click test finished. Check screenshots/ for debug images.")
    print("="*40)

if __name__ == "__main__":
    main()
