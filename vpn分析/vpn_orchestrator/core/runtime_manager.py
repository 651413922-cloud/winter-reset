"""
Runtime Manager — process lifecycle + health check + auto-recovery.

Manages TWO processes: sing-box (TUN/routing/DNS infrastructure) and
Xray (proxy outbound). v2rayN uses this same dual-process architecture:
  - sing-box with configPre.json: TUN virtual NIC, routing, DNS
  - Xray with config.json: SOCKS inbound + proxy outbound to remote node

The proxy outbound's dialerProxy sends Xray's own connections through
sing-box's tun-protect-socks to avoid routing loops through the TUN.
"""

import ctypes
import logging
import subprocess
import time
import sys, os
from typing import Optional, Tuple

import psutil

from config import (
    SING_BOX_EXE, SING_BOX_CONFIG,
    XRAY_EXE, CONFIG_JSON,
    get_active_exe, get_active_core_type,
    CORE_TYPE_XRAY, CORE_TYPE_SING_BOX,
)
from core.state import (
    VpnState, StateMachine, StateError, VpnStatus,
    RecoveryStrategy, HealthSnapshot,
)
from services.proxy_checker import ProxyChecker

logger = logging.getLogger(__name__)

# Process name constants
SING_BOX_NAME = 'sing-box.exe'
XRAY_NAME = 'xray.exe'
PROXY_NAMES = {SING_BOX_NAME, XRAY_NAME, 'sing-box', 'xray'}


class RuntimeManager:
    """
    Manages sing-box (TUN infrastructure) and Xray (proxy outbound)
    process lifecycle with health monitoring and auto-recovery.

    Dual-process architecture matching v2rayN:
      - sing-box.exe with configPre.json — TUN, routing, DNS, tun-protect-socks
      - xray.exe with config.json — SOCKS inbound, proxy outbound to remote node

    Xray's proxy outbound has dialerProxy → sing-box tun-protect-socks (:58481),
    which prevents routing loops when the system has TUN active.
    """

    def __init__(self, exe_path: str = None,
                 config_path: str = CONFIG_JSON):
        self.singbox_exe = SING_BOX_EXE
        self.singbox_config = SING_BOX_CONFIG
        self.xray_exe = XRAY_EXE
        self.xray_config = config_path
        self.checker = ProxyChecker()
        self._singbox_proc: Optional[subprocess.Popen] = None
        self._xray_proc: Optional[subprocess.Popen] = None
        self._startup_timeout = 5.0

    # ================================================================
    #  Admin Check
    # ================================================================

    @staticmethod
    def is_admin() -> bool:
        """Check if the current process has administrator privileges.

        Required for sing-box TUN interface creation.
        """
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

    # ================================================================
    #  Process Discovery
    # ================================================================

    @staticmethod
    def find_singbox_process() -> Optional[psutil.Process]:
        """Find a running sing-box.exe process."""
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                name = (proc.info.get('name') or '').lower()
                if name == SING_BOX_NAME:
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    @staticmethod
    def find_xray_process() -> Optional[psutil.Process]:
        """Find a running xray.exe process."""
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                name = (proc.info.get('name') or '').lower()
                if name == XRAY_NAME:
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    @staticmethod
    def find_any_proxy_process() -> Optional[psutil.Process]:
        """Find any running proxy process (sing-box or xray)."""
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                name = (proc.info.get('name') or '').lower()
                if name in PROXY_NAMES:
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    @staticmethod
    def is_running() -> bool:
        return RuntimeManager.find_any_proxy_process() is not None

    @staticmethod
    def is_singbox_running() -> bool:
        return RuntimeManager.find_singbox_process() is not None

    @staticmethod
    def is_xray_running() -> bool:
        return RuntimeManager.find_xray_process() is not None

    @staticmethod
    def find_v2rayn_gui() -> Optional[psutil.Process]:
        """Detect if v2rayN GUI is running (will conflict with us).

        Only checks the process NAME (e.g. 'v2rayN.exe'), NOT the full
        executable path.  Previously we checked proc.info['exe'] which
        includes directory names like '.../v2rayn/.../xray.exe', causing
        false positives on xray.exe / sing-box.exe.
        """
        gui_names = {'v2rayn.exe', 'v2rayn', 'v2rayngui.exe'}
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                name = (proc.info.get('name') or '').lower()
                if name in gui_names:
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    @staticmethod
    def check_coexistence() -> list[str]:
        """
        Check for conflicting processes. Returns list of warnings.

        v2rayN GUI and this orchestrator MUST NOT run simultaneously -
        they will fight over config.json and the proxy process.
        """
        warnings = []
        gui = RuntimeManager.find_v2rayn_gui()
        if gui:
            warnings.append(
                f'v2rayN GUI is running (PID {gui.pid}). '
                'Stop v2rayN before using the orchestrator - '
                'they will fight over config.json.'
            )
        return warnings

    @staticmethod
    def get_process_info() -> Optional[dict]:
        """Get process details for diagnostics (both processes)."""
        sb = RuntimeManager.find_singbox_process()
        xr = RuntimeManager.find_xray_process()
        if not sb and not xr:
            return None

        info = {}
        if sb:
            try:
                info['singbox'] = {
                    'pid': sb.pid,
                    'memory_mb': round(sb.memory_info().rss / 1024 / 1024, 1),
                    'cpu_percent': sb.cpu_percent(),
                    'create_time': sb.create_time(),
                }
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if xr:
            try:
                info['xray'] = {
                    'pid': xr.pid,
                    'memory_mb': round(xr.memory_info().rss / 1024 / 1024, 1),
                    'cpu_percent': xr.cpu_percent(),
                    'create_time': xr.create_time(),
                }
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return info

    # ================================================================
    #  Process Control
    # ================================================================

    @staticmethod
    def cleanup_legacy_processes() -> int:
        """
        Kill ALL xray.exe / sing-box.exe processes on the system.

        Call this before starting to ensure a clean slate.
        Returns the number of processes killed.
        """
        killed = 0
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                name = (proc.info.get('name') or '').lower()
                if name in PROXY_NAMES:
                    logger.info("Cleaning up legacy process %s (PID %d)",
                                name, proc.pid)
                    proc.kill()
                    try:
                        proc.wait(timeout=3)
                    except psutil.TimeoutExpired:
                        pass
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if killed:
            logger.info("Cleaned up %d legacy process(es)", killed)
            time.sleep(0.5)
        return killed

    @staticmethod
    def _stop_process(proc_info, name: str, timeout: float = 8.0) -> bool:
        """Stop a single process by name. Returns True if stopped/not running."""
        proc = None
        if name == 'sing-box':
            proc = RuntimeManager.find_singbox_process()
        elif name == 'xray':
            proc = RuntimeManager.find_xray_process()

        if not proc:
            logger.info("%s is not running", name)
            return True

        pid = proc.pid
        logger.info("Stopping %s (PID: %d)...", name, pid)

        try:
            proc.terminate()
            try:
                proc.wait(timeout=timeout)
                logger.info("%s stopped gracefully", name)
            except psutil.TimeoutExpired:
                logger.warning("Terminate timed out, force killing %s...", name)
                proc.kill()
                proc.wait(timeout=3)
                logger.info("%s force-killed", name)
            time.sleep(0.3)
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.error("Stop %s failed: %s", name, e)
            return False

    @staticmethod
    def stop(timeout: float = 8.0) -> bool:
        """Stop both processes: Xray first, then sing-box."""
        success = True
        # Stop Xray first (depends on sing-box tun-protect-socks)
        if not RuntimeManager._stop_process(None, 'xray', timeout):
            success = False
        time.sleep(0.3)
        # Then stop sing-box
        if not RuntimeManager._stop_process(None, 'sing-box', timeout):
            success = False
        return success

    @staticmethod
    def stop_xray(timeout: float = 8.0) -> bool:
        """Stop only Xray (for node switching). sing-box keeps running."""
        return RuntimeManager._stop_process(None, 'xray', timeout)

    # ---- Start ----

    def start(self) -> bool:
        """
        Start both processes: sing-box (TUN) then Xray (proxy).

        1. Check for admin rights (required for TUN)
        2. Clean up legacy processes
        3. Start sing-box with configPre.json (TUN infrastructure)
        4. Wait for sing-box to be ready
        5. Start Xray with config.json (proxy outbound)
        6. Wait for Xray to be ready
        """
        if not self.is_admin():
            logger.error("Admin privileges required for TUN mode. "
                         "Run as administrator.")
            return False

        if self.is_running():
            logger.info("Proxy processes already running")
            return True

        # Clean up orphans from previous runs
        self.cleanup_legacy_processes()

        # --- Start sing-box (TUN infrastructure) ---
        if not self._start_singbox():
            return False

        # --- Start Xray (proxy outbound) ---
        if not self._start_xray():
            # Clean up sing-box if Xray fails
            self._stop_process(None, 'sing-box')
            return False

        logger.info("Both processes running — TUN + proxy ready")
        return True

    def _start_singbox(self) -> bool:
        """Start sing-box with configPre.json (TUN/routing/DNS)."""
        if self.is_singbox_running():
            logger.info("sing-box already running")
            return True

        if not os.path.exists(self.singbox_exe):
            logger.error("sing-box.exe not found: %s", self.singbox_exe)
            return False

        if not os.path.exists(self.singbox_config):
            logger.error("sing-box config not found: %s", self.singbox_config)
            return False

        try:
            logger.info("Starting sing-box (TUN mode)...")
            env = os.environ.copy()
            env['ENABLE_DEPRECATED_LEGACY_DNS_SERVERS'] = 'true'
            env['ENABLE_DEPRECATED_MISSING_DOMAIN_RESOLVER'] = 'true'

            self._singbox_proc = subprocess.Popen(
                [self.singbox_exe, 'run', '-c', self.singbox_config],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=env,
            )

            # Wait for sing-box to appear
            deadline = time.time() + self._startup_timeout
            while time.time() < deadline:
                if self.is_singbox_running():
                    logger.info("sing-box started (PID: %d)", self._singbox_proc.pid)
                    time.sleep(1.0)  # Let TUN interface initialize
                    return True
                time.sleep(0.3)

            # Check if process exited
            poll = self._singbox_proc.poll()
            if poll is not None:
                _, stderr = self._singbox_proc.communicate(timeout=2)
                err_msg = stderr.decode('utf-8', errors='replace')[:800] if stderr else ''
                logger.error("sing-box exited immediately (code: %d)", poll)
                for line in err_msg.split('\n'):
                    if any(kw in line for kw in ('FATAL', 'ERROR', 'error', 'fatal')):
                        logger.error("  %s", line.strip())
            else:
                logger.error("sing-box did not appear as running process")
            return False

        except FileNotFoundError:
            logger.error("sing-box.exe not found at: %s", self.singbox_exe)
            return False
        except Exception as e:
            logger.error("Start sing-box exception: %s", e)
            return False

    def _start_xray(self) -> bool:
        """Start Xray with config.json (proxy outbound)."""
        if self.is_xray_running():
            logger.info("Xray already running")
            return True

        if not os.path.exists(self.xray_exe):
            logger.error("xray.exe not found: %s", self.xray_exe)
            return False

        if not os.path.exists(self.xray_config):
            logger.error("config.json not found: %s", self.xray_config)
            return False

        try:
            logger.info("Starting Xray...")
            self._xray_proc = subprocess.Popen(
                [self.xray_exe, 'run', '-c', self.xray_config],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            deadline = time.time() + self._startup_timeout
            while time.time() < deadline:
                if self.is_xray_running():
                    logger.info("Xray started (PID: %d)", self._xray_proc.pid)
                    return True
                time.sleep(0.3)

            poll = self._xray_proc.poll()
            if poll is not None:
                _, stderr = self._xray_proc.communicate(timeout=2)
                err_msg = stderr.decode('utf-8', errors='replace')[:800] if stderr else ''
                logger.error("Xray exited immediately (code: %d)", poll)
                for line in err_msg.split('\n'):
                    if any(kw in line for kw in ('FATAL', 'ERROR', 'error', 'fatal')):
                        logger.error("  %s", line.strip())
            else:
                logger.error("Xray did not appear as running process")
            return False

        except FileNotFoundError:
            logger.error("xray.exe not found at: %s", self.xray_exe)
            return False
        except Exception as e:
            logger.error("Start Xray exception: %s", e)
            return False

    # ---- Restart ----

    def restart(self) -> bool:
        """Full restart: stop both, then start both."""
        logger.info("Restarting both processes...")
        self.stop()
        time.sleep(0.5)
        return self.start()

    def restart_xray(self) -> bool:
        """
        Restart Xray only (for node switching).

        sing-box TUN infrastructure stays running — no need to
        tear down and recreate the TUN interface.
        """
        logger.info("Restarting Xray (node switch)...")
        if not self._stop_process(None, 'xray'):
            logger.warning("Xray stop had issues, proceeding anyway")
            time.sleep(0.5)
        time.sleep(0.3)
        return self._start_xray()

    # ================================================================
    #  Health Check
    # ================================================================

    def health_check(self) -> HealthSnapshot:
        """
        Perform a full health check: process liveness + proxy connectivity.
        """
        sb_running = self.is_singbox_running()
        xr_running = self.is_xray_running()
        process_running = sb_running and xr_running
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
        """Execute the recovery strategy determined by VpnStatus."""
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
            time.sleep(min(backoff, 60))
            return self._recover_restart(status)

        elif strategy == RecoveryStrategy.GIVE_UP:
            logger.error("All recovery strategies exhausted after %d failures",
                        status.consecutive_failures)
            return False, "All strategies exhausted - manual intervention required"

        return False, f"Unknown strategy: {strategy}"

    def _recover_restart(self, status: VpnStatus) -> Tuple[bool, str]:
        """Recovery: restart both processes."""
        logger.info("Recovery: restarting both processes...")
        if self.restart():
            time.sleep(2)
            online, latency = self.checker.check_connectivity()
            status.update_health(online, latency, self.is_running())
            if online:
                logger.info("Recovery successful after restart (latency: %.0fms)", latency)
                return True, "Restored via process restart"
        return False, "Process restart did not restore connectivity"

    def _recover_switch_node(self, status: VpnStatus,
                             on_switch_node) -> Tuple[bool, str]:
        """Recovery: switch to next best node (restarts Xray only)."""
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
        """Recovery: restore config from backup, then restart."""
        logger.info("Recovery: restoring config from backup...")
        restored = on_restore_config()
        if restored:
            if self.restart_xray():
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
        """Print current process status for both processes."""
        info = self.get_process_info()
        if info:
            if 'singbox' in info:
                sb = info['singbox']
                logger.info("sing-box  RUNNING | PID: %d | Memory: %.1f MB | CPU: %.1f%%",
                           sb['pid'], sb['memory_mb'], sb['cpu_percent'])
            else:
                logger.info("sing-box  NOT RUNNING")
            if 'xray' in info:
                xr = info['xray']
                logger.info("Xray      RUNNING | PID: %d | Memory: %.1f MB | CPU: %.1f%%",
                           xr['pid'], xr['memory_mb'], xr['cpu_percent'])
            else:
                logger.info("Xray      NOT RUNNING")
        else:
            logger.info("No proxy processes running")
