"""
Validate all template images before the automation starts.
Ensures files exist, dimensions are reasonable,
and outputs clear OK / WARN / ERROR per template.
"""

from pathlib import Path

from config import TEMPLATE, TEMPLATE_MIN_WIDTH, TEMPLATE_MIN_HEIGHT
from logger import Logger


def validate_all() -> bool:
    """Check every registered template. Returns False if any ERROR."""
    all_ok = True
    Logger.info("=" * 50)
    Logger.info("Template Validation")
    Logger.info("=" * 50)

    for key, path_str in TEMPLATE.items():
        path = Path(path_str)
        if not path.exists():
            Logger.error(f"  [ERROR] {key}: file not found → {path}")
            all_ok = False
            continue

        w, h = _get_png_size(path)
        issues = []

        if w < TEMPLATE_MIN_WIDTH:
            issues.append(f"width={w} < {TEMPLATE_MIN_WIDTH}")
        if h < TEMPLATE_MIN_HEIGHT:
            issues.append(f"height={h} < {TEMPLATE_MIN_HEIGHT}")

        if issues:
            msg = "; ".join(issues)
            Logger.warning(f"  [WARN]  {key}: {msg} ({w}x{h})")
        else:
            Logger.info(f"  [OK]    {key}: {w}x{h} → {path.name}")

    if all_ok:
        Logger.info("Template validation: ALL PASSED")
    else:
        Logger.error("Template validation: SOME FILES MISSING")
    Logger.info("=" * 50)
    return all_ok


def _get_png_size(path: Path):
    """
    Fast PNG dimension read without requiring PIL / OpenCV.
    Parses the IHDR chunk from the raw file header.
    """
    try:
        with open(path, "rb") as f:
            header = f.read(24)
            if header[:8] != b"\x89PNG\r\n\x1a\n":
                return (0, 0)
            w = int.from_bytes(header[16:20], "big")
            h = int.from_bytes(header[20:24], "big")
            return (w, h)
    except Exception:
        return (0, 0)
