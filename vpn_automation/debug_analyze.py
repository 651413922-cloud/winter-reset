"""
Analyze debug screenshots vs templates and print match scores.
Saves visualizations to vpn_automation/screenshots/debug_vis_*.png
Usage:
  cd vpn_automation
  python debug_analyze.py
"""
from pathlib import Path
import cv2
import numpy as np
from config import SCREENSHOTS_DIR

DEBUG_DIR = SCREENSHOTS_DIR
TEMPLATES = {
    "line": SCREENSHOTS_DIR / "line_aa1_label.png",
    "status_full": SCREENSHOTS_DIR / "status_full.png",
    "status_connected": SCREENSHOTS_DIR / "status_connected.png",
    "recharge": SCREENSHOTS_DIR / "btn_recharge.png",
}

def match_and_save(source_path: Path, template_path: Path, out_name: str):
    a = cv2.imread(str(source_path), cv2.IMREAD_GRAYSCALE)
    b = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
    if a is None or b is None:
        print(f"ERROR: cannot load {source_path} or {template_path}")
        return None
    # resize template if larger than source
    ah, aw = a.shape
    bh, bw = b.shape
    if bh > ah or bw > aw:
        scale = min(ah/bh, aw/bw, 1.0)
        new_w = max(1, int(bw * scale * 0.9))
        new_h = max(1, int(bh * scale * 0.9))
        b = cv2.resize(b, (new_w, new_h), interpolation=cv2.INTER_AREA)
        bh, bw = b.shape
    res = cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)
    _, maxv, _, maxloc = cv2.minMaxLoc(res)
    # save visualization
    vis = cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)
    cv2.rectangle(vis, (maxloc[0], maxloc[1]), (maxloc[0]+bw, maxloc[1]+bh), (0,0,255), 2)
    out = DEBUG_DIR / f"debug_vis_{out_name}.png"
    cv2.imwrite(str(out), vis)
    return maxv, maxloc, out

def main():
    # Look for debug files
    debug_files = sorted(DEBUG_DIR.glob("debug_*.png"))
    if not debug_files:
        print("No debug_*.png files found in", DEBUG_DIR)
        return
    print("Found debug files:")
    for f in debug_files:
        print(" ", f.name)
    # Analyze the two recent relevant files if present
    targets = []
    for name in ("debug_afterclick_美国直连节点AA1(clickattempt)_002517.png",
                 "debug_notfound_充值anchor_002513.png"):
        p = DEBUG_DIR / name
        if p.exists():
            targets.append(p)
    if not targets:
        # fallback: analyze all debug files
        targets = debug_files
    for src in targets:
        print("\nAnalyzing:", src.name)
        for key, tpl in TEMPLATES.items():
            if not tpl.exists():
                print(f"  template missing: {tpl.name}")
                continue
            result = match_and_save(src, tpl, f"{src.stem}_{key}")
            if result is None:
                continue
            score, loc, vis = result[0], result[1], result[2]
            print(f"  template={tpl.name:20s} score={score:.4f} vis={vis.name}")
    print("\nAnalysis complete. Inspect debug_vis_*.png files in screenshots/ for visuals.")

if __name__ == "__main__":
    main()
