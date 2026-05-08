"""
Logging module for VPN automation.
Provides formatted console output with timestamps.
"""

import sys
from datetime import datetime


class Logger:
    """Simple logger with colored output for VPN automation."""

    # ANSI color codes for terminal output
    COLORS = {
        "INFO": "\033[94m",      # Blue
        "SUCCESS": "\033[92m",   # Green
        "WARNING": "\033[93m",   # Yellow
        "ERROR": "\033[91m",     # Red
        "RESET": "\033[0m",      # Reset
    }

    @staticmethod
    def _timestamp() -> str:
        """Return current timestamp string."""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _log(level: str, message: str):
        """Internal log method with color support."""
        timestamp = Logger._timestamp()
        color = Logger.COLORS.get(level, Logger.COLORS["RESET"])
        reset = Logger.COLORS["RESET"]

        # Check if running in a terminal that supports colors
        if sys.stdout.isatty():
            print(f"{color}[{level}]{reset} [{timestamp}] {message}")
        else:
            print(f"[{level}] [{timestamp}] {message}")

    @classmethod
    def info(cls, message: str):
        """Log an info message."""
        cls._log("INFO", message)

    @classmethod
    def success(cls, message: str):
        """Log a success message."""
        cls._log("SUCCESS", message)

    @classmethod
    def warning(cls, message: str):
        """Log a warning message."""
        cls._log("WARNING", message)

    @classmethod
    def error(cls, message: str):
        """Log an error message."""
        cls._log("ERROR", message)
