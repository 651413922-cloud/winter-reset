"""
Debug visualization module.
Uses OpenCV to annotate screenshots with bounding boxes and markers:
  - Green = available_line match
  - Red   = full_line match
  - Blue  = popup / anchor
  - Cyan  = click point

Saves result to DEBUG_DIR / debug_{label}_{timestamp}.png
"""

from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional

import pyautogui
import numpy as np

from config import DEBUG_DIR
from logger import Logger

# Try to import cv2; if not available, silently degrade
try:
    import cv2
    _HAVE_CV2 = True
except ImportError:
    _HAVE_CV2 = False
    Logger.warning("[debug_visualizer] OpenCV not installed — annotations disabled")


def capture_and_annotate(
    label: str,
    boxes: Optional[List[Tuple]] = None,
    box_labels: Optional[List[str]] = None,
    box_colors: Optional[List[Tuple[int, int, int]]] = None,
    points: Optional[List[Tuple[int, int]]] = None,
    point_labels: Optional[List[str]] = None,
    colors: Optional[List[Tuple[int, int, int]]] = None,
    text_offset: int = 5,
):
    """
    Capture a full-screen screenshot, annotate it with boxes and points,
    and save to DEBUG_DIR / debug_{label}_{timestamp}.png.

    Args:
        label:       Short description (used in filename).
        boxes:       List of (left, top, width, height) tuples.
        box_labels:  Text per box (e.g. "available", "full").
        box_colors:  BGR color per box (e.g. (0, 255, 0) for green).
        points:      List of (x, y) tuples.
        point_labels: Text per point.
        colors:      BGR color per point.
    """
    if not _HAVE_CV2:
        # Fallback: save plain screenshot
        _save_plain_screenshot(label)
        return

    try:
        # Capture
        screen = pyautogui.screenshot()
        img = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)

        # Draw rectangles
        if boxes:
            for i, box in enumerate(boxes):
                if len(box) != 4:
                    continue
                left, top, width, height = box
                color = box_colors[i] if box_colors and i < len(box_colors) else (0, 255, 0)
                text = box_labels[i] if box_labels and i < len(box_labels) else ""
                # Rectangle
                cv2.rectangle(img, (left, top), (left + width, top + height), color, 2)
                # Label
                if text:
                    cv2.putText(img, text, (left, top - text_offset),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

        # Draw points
        if points:
            for i, (px, py) in enumerate(points):
                color = colors[i] if colors and i < len(colors) else (0, 255, 0)
                text = point_labels[i] if point_labels and i < len(point_labels) else ""
                # Circle
                cv2.circle(img, (px, py), 6, color, -1)  # filled
                cv2.circle(img, (px, py), 8, (255, 255, 255), 1)  # white outline
                # Label
                if text:
                    cv2.putText(img, text, (px + 10, py - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

        _save_annotated(img, label)
    except Exception as e:
        Logger.warning(f"[debug_visualizer] Annotation error: {e}")
        _save_plain_screenshot(label)


def _save_annotated(img: np.ndarray, label: str):
    """Save annotated image to debug_output directory."""
    try:
        ts = datetime.now().strftime("%H%M%S")
        filename = f"debug_{label}_{ts}.png"
        filepath = DEBUG_DIR / filename
        cv2.imwrite(str(filepath), img)
        Logger.info(f"[debug] Annotated screenshot saved: {filepath}")
    except Exception as e:
        Logger.warning(f"[debug] Failed to save annotated: {e}")


def _save_plain_screenshot(label: str):
    """Fallback: save plain screenshot without annotations."""
    try:
        ts = datetime.now().strftime("%H%M%S")
        filename = f"debug_{label}_{ts}.png"
        filepath = DEBUG_DIR / filename
        pyautogui.screenshot(str(filepath))
        Logger.info(f"[debug] Plain screenshot saved: {filepath}")
    except Exception as e:
        Logger.warning(f"[debug] Failed to save plain screenshot: {e}")
