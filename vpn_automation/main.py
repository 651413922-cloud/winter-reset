"""
Main entry point for VPN automation script.
Usage: python main.py
"""

import sys
import time

from config import MAX_RETRIES
from logger import Logger
from vpn_controller import VPNController


def main():
    """Main entry point."""
    Logger.info("=" * 50)
    Logger.info("VPN Automation Script Started")
    Logger.info("=" * 50)
    Logger.info(f"Max retries: {MAX_RETRIES}")
    Logger.info("Press Ctrl+C to abort at any time")
    Logger.info("Move mouse to top-left corner for emergency stop")
    Logger.info("=" * 50)

    # Step 1: Check all required screenshot files before starting
    if not VPNController.check_required_files():
        Logger.error("Startup check failed. Please add the missing screenshot files.")
        sys.exit(1)

    controller = VPNController()

    try:
        success = controller.auto_connect()

        if success:
            Logger.success("=" * 50)
            Logger.success("[SUCCESS] VPN connected!")
            Logger.success("=" * 50)

            # Open target URL in browser
            controller.open_target_url()
        else:
            Logger.error("=" * 50)
            Logger.error("[FAILED] Could not connect VPN after all retries")
            Logger.error("=" * 50)
            sys.exit(1)

    except KeyboardInterrupt:
        Logger.warning("\nScript interrupted by user (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        Logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
