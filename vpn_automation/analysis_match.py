"""
Analyze template matching between a debug screenshot and a template.
Usage:
    python analysis_match.py debug_image.png template_image.png
Outputs match score and saves visualization to screenshots/debug_match_vis.png
"""
import sys
from pathlib import Path
import cv2

def main():
    if len(sys.argv) < 3:
        print("Usage: python analysis_match.py <debug_image> <template_image>")
        return

    debug_path = Path(sys.argv[1])
    template_path = Path(sys.argv[2])

    if not debug_path.exists():
        print(f"ERROR: debug image not found: {debug_path}")
        return
    if not template_path.exists():
        print(f"ERROR: template image not found: {template_path}")
        return

    a = cv2.imread(str(debug_path), cv2.IMREAD_GRAYSCALE)
    b = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)

    if a is None or b is None:
        print("ERROR: failed to load one of the images (cv2 returned None)")
        return

    # If template is larger than source, resize template down (best-effort)
    ah, aw = a.shape
    bh, bw = b.shape
    if bh > ah or bw > aw:
        print("Warning: template larger than source; resizing template to fit")
        scale = min(ah / bh, aw / bw, 1.0)
        new_w = max(1, int(bw * scale * 0.9))
        new_h = max(1, int(bh * scale * 0.9))
        b = cv2.resize(b, (new_w, new_h), interpolation=cv2.INTER_AREA)
        bh, bw = b.shape

    res = cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)
    minv, maxv, minloc, maxloc = cv2.minMaxLoc(res)

    print(f"match_score={maxv:.4f}")
    print(f"match_top_left={maxloc}")
    # save visualization
    vis = cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)
    cv2.rectangle(vis, (maxloc[0], maxloc[1]), (maxloc[0]+bw, maxloc[1]+bh), (0,0,255), 2)
    out = Path("vpn_automation") / "screenshots" / "debug_match_vis_AA1.png"
    cv2.imwrite(str(out), vis)
    print(f"saved_vis={out}")

if __name__ == "__main__":
    main()
