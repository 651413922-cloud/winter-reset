"""
Copy a debug screenshot matching AA1/美国直连 to debug_aa1.png for analysis.
Usage: python copy_debug.py
Prints the source filename copied, or 'NO_MATCH' if none found.
"""
import shutil, os, glob, sys
d = os.path.join(os.path.dirname(__file__), "screenshots")
patterns = ["*美国直连*", "*AA1*", "*AA1*"]
candidates = []
for p in patterns:
    candidates.extend(glob.glob(os.path.join(d, "debug_notfound_" + p)))
    candidates.extend(glob.glob(os.path.join(d, "debug_*" + p)))
# fallback: any debug_notfound file
if not candidates:
    candidates = glob.glob(os.path.join(d, "debug_notfound_*"))
if not candidates:
    print("NO_MATCH")
    sys.exit(1)
src = candidates[0]
dst = os.path.join(d, "debug_aa1.png")
shutil.copy(src, dst)
print(os.path.basename(src))
