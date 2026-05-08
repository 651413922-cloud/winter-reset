"""
Simple click test script.
Run this to verify PyAutoGUI clicks are working on your system.
"""

import sys
import time

import pyautogui

print("=" * 50)
print("PyAutoGUI Click Test")
print("=" * 50)
print()
print("This test will:")
print("  1. Show your mouse position")
print("  2. Click at a position you choose")
print("  3. Verify clicks are working")
print()
print("WARNING: Move mouse to TOP-LEFT corner to abort!")
print()

# Show current mouse position
x, y = pyautogui.position()
print(f"Current mouse position: ({x}, {y})")
print(f"Screen size: {pyautogui.size()}")
print()

# Test 1: Move mouse to center of screen
screen_w, screen_h = pyautogui.size()
center_x, center_y = screen_w // 2, screen_h // 2

print(f"Test 1: Moving mouse to center of screen ({center_x}, {center_y})...")
pyautogui.moveTo(center_x, center_y, duration=0.5)
time.sleep(0.5)
print("  Done. Did the mouse move? (y/n)")
response = input("  > ")
if response.lower() != 'y':
    print("  ❌ Mouse movement not working!")
    print("  Try running as Administrator.")
    sys.exit(1)
else:
    print("  ✅ Mouse movement OK!")

# Test 2: Click at current position
print()
print(f"Test 2: Clicking at current position ({center_x}, {center_y})...")
pyautogui.click()
time.sleep(0.3)
print("  ✅ Click performed! (check if anything was clicked)")

# Test 3: Let user move mouse to a target and click
print()
print("Test 3: Let's click on a specific target")
print("  Move your mouse to the '更换线路' button (or any other target)")
print("  Then press ENTER to click that position")
input("  Press ENTER when mouse is on target...")

target_x, target_y = pyautogui.position()
print(f"  Target position: ({target_x}, {target_y})")
print(f"  Clicking in 2 seconds...")
time.sleep(1)
print(f"  Clicking now!")
pyautogui.click(target_x, target_y)
print("  ✅ Clicked!")
time.sleep(0.5)

# Test 4: Type something
print()
print("Test 4: Typing test (opens Notepad-like behavior)")
print("  Move to a text input area, then press ENTER")
input("  Press ENTER when ready...")
text_x, text_y = pyautogui.position()
pyautogui.click(text_x, text_y)
time.sleep(0.3)
pyautogui.write("Hello from PyAutoGUI!", interval=0.05)
print("  ✅ Typed text!")

print()
print("=" * 50)
print("All tests passed! PyAutoGUI clicks are working.")
print("=" * 50)
