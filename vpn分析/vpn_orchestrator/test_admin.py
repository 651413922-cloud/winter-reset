"""
Test script: start sing-box (TUN) + Xray (proxy) with admin privileges.

Run this from an admin terminal:
    python "vpn分析/vpn_orchestrator/test_admin.py"

Or right-click PowerShell/Terminal → "Run as administrator".
"""

import subprocess
import time
import os
import sys

# Add project root to path
_orch_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _orch_dir)

from core.runtime_manager import RuntimeManager
from core.logging_config import setup_logging

setup_logging(debug=False)

print("=" * 60)
print("  Admin Test — sing-box (TUN) + Xray (proxy) dual start")
print("=" * 60)

rt = RuntimeManager()

# Check admin
if not rt.is_admin():
    print("ERROR: Admin privileges required!")
    print("Please re-run this script as Administrator.")
    print("  Right-click PowerShell → 'Run as administrator'")
    print("  cd D:\\d\\GitHub\\winter-reset")
    print("  python vpn分析\\vpn_orchestrator\\test_admin.py")
    sys.exit(1)

print("[OK] Running as admin")

# Cleanup first
rt.cleanup_legacy_processes()
time.sleep(0.5)

# Start both processes
print("\nStarting dual-process stack...")
success = rt.start()

if success:
    print("\n[SUCCESS] Both processes running!")
    rt.print_status()

    # Test proxy connectivity
    print("\nTesting proxy connectivity...")
    time.sleep(2)
    online, latency = rt.checker.check_connectivity()
    if online:
        print(f"[SUCCESS] Proxy working! Latency: {latency:.0f}ms")
    else:
        print("[FAIL] Proxy unreachable. The SS node may be slow or unreachable.")

    print("\nProcesses will keep running. Use Ctrl+C to stop.")
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nStopping processes...")
        rt.stop()
else:
    print("\n[FAIL] Could not start processes.")
    print("Check the log messages above for details.")
