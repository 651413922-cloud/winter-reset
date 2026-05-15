"""
sing-box process manager (compatibility wrapper).

Delegates to RuntimeManager for Windows-safe process lifecycle.
Public API kept stable for backward compatibility.
"""

import logging
import sys, os
from typing import Optional

import psutil

_orch_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _orch_root not in sys.path:
    sys.path.insert(0, _orch_root)

from config import SING_BOX_EXE, CONFIG_JSON

logger = logging.getLogger(__name__)


class ProcessManager:
    """Manage sing-box process (delegates to RuntimeManager)."""

    def __init__(self, exe_path: str = SING_BOX_EXE,
                 config_path: str = CONFIG_JSON):
        self.exe_path = exe_path
        self.config_path = config_path
        self._process: Optional = None

        # Lazy-import to avoid circular dependency
        from core.runtime_manager import RuntimeManager
        self._rt = RuntimeManager(exe_path, config_path)

    # ========== Process Discovery ==========

    @staticmethod
    def find_singbox_process() -> Optional[psutil.Process]:
        from core.runtime_manager import RuntimeManager
        return RuntimeManager.find_singbox_process()

    @staticmethod
    def is_running() -> bool:
        from core.runtime_manager import RuntimeManager
        return RuntimeManager.is_running()

    # ========== Stop ==========

    @staticmethod
    def stop() -> bool:
        from core.runtime_manager import RuntimeManager
        return RuntimeManager.stop()

    # ========== Start ==========

    def start(self, timeout: float = 5.0) -> bool:
        self._rt._startup_timeout = timeout
        return self._rt.start()

    # ========== Restart ==========

    def restart(self) -> bool:
        return self._rt.restart()

    # ========== Status ==========

    def print_status(self):
        self._rt.print_status()
