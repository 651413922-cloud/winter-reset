"""
VPN Orchestrator — high-level facade combining all modules.

Integrates:
  - RuntimeManager   (process lifecycle + health check + auto-recovery)
  - StateMachine     (strict state transitions)
  - VpnStatus        (operational state + health tracking)
  - DbManager        (node database)
  - NodeSwitcher     (node switching)
  - BrowserLauncher  (browser tabs)
"""

import sys
import os
import logging

_orch_dir = os.path.dirname(os.path.abspath(__file__))
if _orch_dir not in sys.path:
    sys.path.insert(0, _orch_dir)

import time
from typing import Optional

from core.db_manager import DbManager
from core.process_manager import ProcessManager
from core.runtime_manager import RuntimeManager
from core.config_builder import apply_profile_to_config, read_current_config
from core.state import (
    VpnState, StateMachine, StateError, VpnStatus,
    RecoveryStrategy, HealthSnapshot,
)
from services.proxy_checker import ProxyChecker
from services.node_switcher import NodeSwitcher
from services.browser_launcher import BrowserLauncher

logger = logging.getLogger(__name__)


class VpnOrchestrator:
    """VPN orchestration — high-level control entry point."""

    def __init__(self, tick_interval: float = 30.0):
        self.db = DbManager()
        self.rt = RuntimeManager()
        self.proc = ProcessManager()  # backward-compat wrapper
        self.checker = ProxyChecker()
        self.switcher = NodeSwitcher()
        self.browser = BrowserLauncher()
        self.sm = StateMachine()
        self.status = VpnStatus()
        self.tick_interval = tick_interval

        # Sync initial state from reality
        self._sync_initial_state()

    def _sync_initial_state(self):
        """Detect actual sing-box state on startup."""
        if self.rt.is_running():
            self.sm.force(VpnState.CONNECTED)
            self._sync_current_node()
            online, latency = self.checker.check_connectivity()
            self.status.update_health(online, latency, True)
            if not online:
                self.sm.force(VpnState.DEGRADED)
                self.status.record_failure(self.status.current_node or 'unknown')

    def _sync_current_node(self):
        """Read current proxy outbound from config.json into status."""
        try:
            from adapters.xray_config import find_proxy_outbound, read_config
            cfg = read_config()
            ob, _ = find_proxy_outbound(cfg)
            if ob:
                proto = ob.get('protocol', ob.get('type', ''))
                if proto in ('vless', 'vmess', 'trojan'):
                    vnext = ob.get('settings', {}).get('vnext', [])
                    if vnext:
                        addr = vnext[0].get('address', '')
                        port = vnext[0].get('port', '')
                        self.status.current_node = f'{addr}:{port}'
                        return
                elif proto == 'shadowsocks':
                    servers = ob.get('settings', {}).get('servers', [])
                    if servers:
                        addr = servers[0].get('address', '')
                        port = servers[0].get('port', '')
                        self.status.current_node = f'{addr}:{port}'
                        return
                self.status.current_node = f'{proto}://{ob.get("server", "?")}'
        except Exception:
            pass

    # ================================================================
    #  State transitions
    # ================================================================

    def _try_transition(self, to: VpnState) -> bool:
        try:
            self.sm.transition(to)
            self.status.state = self.sm.state
            self.status.state_since = time.monotonic()
            logger.info('State: %s', to.name)
            return True
        except StateError:
            logger.warning('Illegal transition: %s → %s',
                          self.sm.state.name, to.name)
            return False

    # ================================================================
    #  Auto-connect (full flow)
    # ================================================================

    def auto_connect(self, open_browser: bool = True) -> bool:
        logger.info('=' * 50)
        logger.info('  VPN Orchestrator — Auto Connect')
        logger.info('=' * 50)

        # Step 1: Pick best node, patch config
        logger.info('[1/5] Selecting node & patching config...')
        profile = self._pick_best_profile()
        if not profile:
            logger.error('  No nodes in database')
            return False
        apply_profile_to_config(profile)
        self._sync_current_node()

        # Step 2: Stop old process
        logger.info('[2/5] Stopping old process...')
        self.rt.stop()

        # Step 3: Start
        logger.info('[3/5] Starting sing-box...')
        self._try_transition(VpnState.CONNECTING)
        if not self.rt.start():
            self._try_transition(VpnState.FAILED)
            logger.error('  Start failed')
            return False
        self._try_transition(VpnState.CONNECTED)

        # Step 4: Verify
        logger.info('[4/5] Checking proxy...')
        online, latency = self.checker.check_connectivity()
        self.status.update_health(online, latency, True)
        if online:
            logger.info('  Proxy OK (latency: %.0fms)', latency)
        else:
            logger.warning('  Proxy unreachable, trying failover...')
            self._try_transition(VpnState.RECOVERING)
            found = self.switcher.switch_until_working()
            if not found:
                self._try_transition(VpnState.FAILED)
                logger.error('  All nodes failed')
                return False
            self._try_transition(VpnState.CONNECTED)
            self.status.reset_failures()

        # Step 5: Browser
        if open_browser:
            logger.info('[5/5] Opening browser...')
            self.browser.open_all()
        else:
            logger.info('[5/5] Skipping browser')

        logger.info('  VPN Ready!')
        return True

    # ================================================================
    #  Node selection
    # ================================================================

    def _pick_best_profile(self):
        self.db.connect()
        try:
            profiles = self.db.get_all_profiles()
            if not profiles:
                return None
            scored = []
            for p in profiles:
                if self.status.is_node_blacklisted(p.remarks):
                    continue
                stats = self.db.get_profile_stats(p.index_id)
                delay = stats['delay'] if stats['delay'] > 0 else 99999
                speed = stats['speed']
                scored.append((p, delay, speed))
            if not scored:
                # All blacklisted, reset and try again
                self.status.node_failures.clear()
                return self._pick_best_profile()
            scored.sort(key=lambda x: (x[1], -x[2]))
            best = scored[0]
            logger.info('  Best node: %s (delay: %.0fms, speed: %.1fMB/s)',
                       best[0].remarks, best[1], best[2])
            return best[0]
        finally:
            self.db.close()

    # ================================================================
    #  Daemon tick (health check + auto-recovery)
    # ================================================================

    def tick(self) -> VpnState:
        """
        Single daemon tick: health check → recovery if needed.

        Returns current VpnState.
        """
        if self.sm.in_state(VpnState.STOPPED):
            return self.sm.state

        # Health check
        process_running = self.rt.is_running()
        online, latency = self.checker.check_connectivity() if process_running else (False, -1)
        self.status.update_health(online, latency, process_running)

        if not process_running:
            logger.warning('Process lost, attempting restart...')
            self._try_transition(VpnState.CONNECTING)
            if self.rt.start():
                self._try_transition(VpnState.CONNECTED)
                self.status.reset_failures()
            else:
                self._try_transition(VpnState.DISCONNECTED)
            return self.sm.state

        if online:
            if self.sm.in_state(VpnState.DEGRADED, VpnState.RECOVERING, VpnState.FAILED):
                logger.info('Connectivity restored (latency: %.0fms)', latency)
            self._try_transition(VpnState.CONNECTED)
            self.status.reset_failures()
        else:
            logger.warning('Proxy unreachable (latency: %.0fms)', latency)
            self._try_transition(VpnState.DEGRADED)
            self._sync_current_node()
            node = self.status.current_node or 'unknown'
            self.status.record_failure(node)

            logger.info('Node %s — %d consecutive failures (strategy: %s)',
                       node, self.status.consecutive_failures,
                       self.status.get_recovery_strategy().name)

            # Auto-recovery
            self._try_transition(VpnState.RECOVERING)
            recovered, desc = self.rt.attempt_recovery(
                self.status,
                on_switch_node=lambda: self.switcher.switch_until_working(),
                on_restore_config=lambda: self._restore_and_restart(),
            )

            if recovered:
                self._try_transition(VpnState.CONNECTED)
                self.status.reset_failures()
                self._sync_current_node()
                logger.info('Recovered: %s', desc)
            elif self.status.get_recovery_strategy() == RecoveryStrategy.GIVE_UP:
                self._try_transition(VpnState.FAILED)
                logger.error('Entered FAILED state — manual intervention needed')
            else:
                logger.warning('Recovery unsuccessful, will retry next tick')

        return self.sm.state

    def _restore_and_restart(self) -> bool:
        """Restore config from backup and restart."""
        from adapters.xray_config import restore_config
        return restore_config()

    # ================================================================
    #  Node management
    # ================================================================

    def list_nodes(self):
        self.db.connect()
        try:
            self.db.print_all_profiles()
        finally:
            self.db.close()

    def switch_node(self, name_or_index):
        self._try_transition(VpnState.SWITCHING)
        result = self.switcher.switch_to(name_or_index)
        if result:
            self._try_transition(VpnState.CONNECTED)
            self._sync_current_node()
            self.status.reset_failures()
        else:
            self._try_transition(VpnState.DEGRADED)
        return result

    def switch_best(self):
        self._try_transition(VpnState.SWITCHING)
        result = self.switcher.switch_to_best()
        if result:
            self._try_transition(VpnState.CONNECTED)
            self._sync_current_node()
            self.status.reset_failures()
        else:
            self._try_transition(VpnState.DEGRADED)
        return result

    def switch_working(self):
        self._try_transition(VpnState.RECOVERING)
        result = self.switcher.switch_until_working()
        if result:
            self._try_transition(VpnState.CONNECTED)
            self._sync_current_node()
            self.status.reset_failures()
        else:
            self._try_transition(VpnState.FAILED)
        return result

    # ================================================================
    #  Process control
    # ================================================================

    def start(self) -> bool:
        self._try_transition(VpnState.CONNECTING)
        if self.rt.start():
            self._try_transition(VpnState.CONNECTED)
            return True
        self._try_transition(VpnState.FAILED)
        return False

    def stop(self) -> bool:
        if self.rt.stop():
            self.sm.force(VpnState.STOPPED)
            self.status.state = self.sm.state
            return True
        return False

    def restart(self) -> bool:
        self._try_transition(VpnState.CONNECTING)
        if self.rt.restart():
            self._try_transition(VpnState.CONNECTED)
            return True
        self._try_transition(VpnState.FAILED)
        return False

    # ================================================================
    #  Status & diagnostics
    # ================================================================

    def status(self):
        """Print comprehensive status report."""
        self.rt.print_status()
        online, latency = self.checker.check_connectivity()
        self.status.update_health(online, latency, self.rt.is_running())

        if online:
            logger.info('  Proxy OK (latency: %.0fms)', latency)
        else:
            logger.warning('  Proxy UNREACHABLE')

        h = self.status.last_health
        logger.info(
            '  State: %s | Node: %s | Failures: %d | Switches: %d | '
            'Strategy: %s | State duration: %.0fs',
            self.sm.state.name,
            self.status.current_node or '?',
            self.status.consecutive_failures,
            self.status.total_switches,
            self.status.get_recovery_strategy().name,
            self.status.state_duration_seconds,
        )

    def check_proxy(self):
        """Full connectivity check."""
        self.rt.print_status()
        result = self.checker.full_check()
        if result['online']:
            logger.info('  Online | Latency: %.0fms | Speed: %.1fMB/s',
                       result['delay_ms'], result['speed_mb_s'])
        else:
            logger.error('  Offline | Reason: %s', result['error'])
        return result

    def open_browsers(self):
        self.browser.open_all()

    def list_subscriptions(self):
        self.db.connect()
        try:
            self.db.print_subscriptions()
        finally:
            self.db.close()
