"""
Runtime Manager — process lifecycle + health check + auto-recovery.

Windows-aware: handles GBK encoding, file locks (EBUSY), subprocess lifecycle,
and Defender interference.

Integrates StateMachine + VpnStatus for health-driven automation.
"""

import logging
import subprocess
import time
import sys, os
from typing import Optional, Tuple

import psutil

_orch_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _orch_root not in sys.path:
    sys.path.insert(0, _orch_root)

from config import SING_BOX_EXE, CONFIG_JSON, SOCKS5_PROXY, CHECK_URL, TIMEOUT
from core.state import (
    VpnState, StateMachine, StateError, VpnStatus,
    RecoveryStrategy, HealthSnapshot,
)
from services.proxy_checker import ProxyChecker

logger = logging.getLogger(__name__)


class RuntimeManager:
    """
    Manages the sing-box process lifecycle with health monitoring
    and automatic recovery.

    Responsibilities:
      - Process start/stop/restart with Windows-safe subprocess handling
      - Health check loop (process liveness + proxy connectivity)
      - Auto-recovery escalation (restart → switch node → reset config → backoff)
      - State machine integration
    """

    def __init__(self, exe_path: str = SING_BOX_EXE,
                 config_path: str = CONFIG_JSON):
        self.exe_path = exe_path
        self.config_path = config_path
        self.checker = ProxyChecker()
        self._process: Optional[subprocess.Popen] = None
        self._startup_timeout = 5.0  # seconds to wait for process to appear

    # ================================================================
    #  Process Discovery
    # ================================================================

    @staticmethod
    def find_singbox_process() -> Optional[psutil.Process]:
        """Find any running sing-box.exe process on the system."""
        for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
            try:
                name = (proc.info.get('name') or '').lower()
                exe = (proc.info.get('exe') or '').lower()
                if 'sing-box' in name or 'sing-box' in exe:
                    return proc
                cmdline = proc.info.get('cmdline')
                if cmdline and any('sing-box' in str(c).lower() for c in cmdline):
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    @staticmethod
    def is_running() -> bool:
        return RuntimeManager.find_singbox_process() is not None

    @staticmethod
    def get_process_info() -> Optional[dict]:
        """Get process details for diagnostics."""
        proc = RuntimeManager.find_singbox_process()
        if not proc:
            return None
        try:
            return {
                'pid': proc.pid,
                'memory_mb': round(proc.memory_info().rss / 1024 / 1024, 1),
                'cpu_percent': proc.cpu_percent(),
                'create_time': proc.create_time(),
                'cmdline': proc.cmdline(),
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    # ================================================================
    #  Process Control (Windows-safe)
    # ================================================================

    @staticmethod
    def stop(timeout: float = 8.0) -> bool:
        """Stop sing-box gracefully (terminate → wait → kill if needed)."""
        proc = RuntimeManager.find_singbox_process()
        if not proc:
            logger.info("sing-box is not running")
            return True

        pid = proc.pid
        logger.info("Stopping sing-box (PID: %d)...", pid)

        try:
            # Graceful termination
            proc.terminate()
            try:
                proc.wait(timeout=timeout)
                logger.info("sing-box stopped gracefully")
            except psutil.TimeoutExpired:
                logger.warning("Terminate timed out, force killing...")
                proc.kill()
                proc.wait(timeout=3)
                logger.info("sing-box force-killed")

            # Windows: wait for file handles to be released
            time.sleep(0.5)
            return True

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.error("Stop failed: %s", e)
            return False
        except Exception as e:
            logger.error("Unexpected stop error: %s", e)
            return False

    def start(self) -> bool:
        """
        Start sing-box.exe with the current config.

        Windows considerations:
          - CREATE_NO_WINDOW prevents console windows from popping up
          - Legacy DNS env vars for sing-box ≥1.12 compatibility
          - Validates the process actually started
        """
        if self.is_running():
            logger.info("sing-box already running")
            return True

        if not os.path.exists(self.exe_path):
            logger.error("sing-box.exe not found: %s", self.exe_path)
            return False

        if not os.path.exists(self.config_path):
            logger.error("config.json not found: %s", self.config_path)
            return False

        try:
            logger.info("Starting sing-box...")
            env = os.environ.copy()
            env['ENABLE_DEPRECATED_LEGACY_DNS_SERVERS'] = 'true'
            env['ENABLE_DEPRECATED_MISSING_DOMAIN_RESOLVER'] = 'true'

            self._process = subprocess.Popen(
                [self.exe_path, 'run', '-c', self.config_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=env,
            )

            # Wait for process to appear as a system process
            deadline = time.time() + self._startup_timeout
            while time.time() < deadline:
                if self.is_running():
                    logger.info("sing-box started (PID: %d)", self._process.pid)
                    return True
                time.sleep(0.3)

            # Check if process exited immediately (config error)
            poll = self._process.poll()
            if poll is not None:
                _, stderr = self._process.communicate(timeout=2)
                err_msg = stderr.decode('utf-8', errors='replace')[:800] if stderr else ''
                logger.error("sing-box exited immediately (code: %d)", poll)
                # Print FATAL/ERROR lines for diagnosis
                for line in err_msg.split('\n'):
                    if any(kw in line for kw in ('FATAL', 'ERROR', 'error', 'fatal')):
                        logger.error("  %s", line.strip())
                return False
            else:
                logger.error("sing-box did not appear as running process")
                return False

        except FileNotFoundError:
            logger.error("sing-box.exe not found at: %s", self.exe_path)
            return False
        except Exception as e:
            logger.error("Start exception: %s", e)
            return False

    def restart(self) -> bool:
        """Restart sing-box: stop → wait → start."""
        logger.info("Restarting sing-box...")
        if not self.stop():
            logger.warning("Stop had issues, proceeding with start anyway")
            time.sleep(1)
        time.sleep(0.5)  # Let file handles release
        return self.start()

    # ================================================================
    #  Health Check
    # ================================================================

    def health_check(self) -> HealthSnapshot:
        """
        Perform a full health check: process liveness + proxy connectivity.

        Returns a HealthSnapshot with all metrics populated.
        """
        process_running = self.is_running()
        online = False
        latency = -1.0

        if process_running:
            online, latency = self.checker.check_connectivity()

        return HealthSnapshot(
            online=online,
            latency_ms=latency,
            process_running=process_running,
        )

    # ================================================================
    #  Recovery Engine
    # ================================================================

    def attempt_recovery(self, status: VpnStatus,
                         on_switch_node, on_restore_config) -> Tuple[bool, str]:
        """
        Execute the recovery strategy determined by VpnStatus.

        Args:
            status: Current VpnStatus with failure counters
            on_switch_node: Callable that switches to next best node → bool
            on_restore_config: Callable that restores config from backup → bool

        Returns:
            (recovered: bool, description: str)
        """
        strategy = status.get_recovery_strategy()
        status.recovery_attempts += 1
        status.last_recovery_at = time.monotonic()

        logger.info("Recovery attempt #%d, strategy: %s (failures: %d)",
                    status.recovery_attempts, strategy.name,
                    status.consecutive_failures)

        if strategy == RecoveryStrategy.RESTART_PROCESS:
            return self._recover_restart(status)

        elif strategy == RecoveryStrategy.SWITCH_NODE:
            return self._recover_switch_node(status, on_switch_node)

        elif strategy == RecoveryStrategy.RESET_CONFIG:
            return self._recover_reset_config(status, on_restore_config)

        elif strategy == RecoveryStrategy.WAIT_RETRY:
            backoff = min(status.consecutive_failures * 10, 300)
            logger.warning("Backing off for %ds before next retry...", backoff)
            time.sleep(min(backoff, 60))  # Don't sleep too long in one tick
            return self._recover_restart(status)

        elif strategy == RecoveryStrategy.GIVE_UP:
            logger.error("All recovery strategies exhausted after %d failures",
                        status.consecutive_failures)
            return False, "All strategies exhausted — manual intervention required"

        return False, f"Unknown strategy: {strategy}"

    def _recover_restart(self, status: VpnStatus) -> Tuple[bool, str]:
        """Recovery: restart sing-box process."""
        logger.info("Recovery: restarting sing-box...")
        if self.restart():
            # Verify
            time.sleep(2)
            online, latency = self.checker.check_connectivity()
            status.update_health(online, latency, self.is_running())
            if online:
                logger.info("Recovery successful after restart (latency: %.0fms)", latency)
                return True, "Restored via process restart"
        return False, "Process restart did not restore connectivity"

    def _recover_switch_node(self, status: VpnStatus,
                             on_switch_node) -> Tuple[bool, str]:
        """Recovery: switch to next best node."""
        logger.info("Recovery: switching node...")
        success = on_switch_node()
        if success:
            online, latency = self.checker.check_connectivity()
            status.update_health(online, latency, self.is_running())
            if online:
                logger.info("Recovery successful after node switch")
                return True, "Restored via node switch"
        return False, "Node switch did not restore connectivity"

    def _recover_reset_config(self, status: VpnStatus,
                              on_restore_config) -> Tuple[bool, str]:
        """Recovery: restore config.json from backup, then restart."""
        logger.info("Recovery: restoring config from backup...")
        restored = on_restore_config()
        if restored:
            if self.restart():
                time.sleep(2)
                online, latency = self.checker.check_connectivity()
                status.update_health(online, latency, self.is_running())
                if online:
                    logger.info("Recovery successful after config restore")
                    return True, "Restored via config backup"
        return False, "Config restore did not restore connectivity"

    # ================================================================
    #  Status Report
    # ================================================================

    def print_status(self):
        """Print current sing-box process status."""
        info = self.get_process_info()
        if info:
            logger.info("sing-box RUNNING | PID: %d | Memory: %.1f MB | CPU: %.1f%%",
                       info['pid'], info['memory_mb'], info['cpu_percent'])
        else:
            logger.info("sing-box NOT RUNNING")
