"""
VPN Orchestrator 高层编排器。
整合所有模块，提供一键式操作入口。
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
from core.config_builder import apply_profile_to_config
from core.state import VpnState, StateMachine, StateError, VpnStatus
from services.proxy_checker import ProxyChecker
from services.node_switcher import NodeSwitcher
from services.browser_launcher import BrowserLauncher

logger = logging.getLogger(__name__)


class VpnOrchestrator:
    """VPN 编排器 - 高层控制入口"""

    def __init__(self, tick_interval: float = 30.0):
        self.db = DbManager()
        self.proc = ProcessManager()
        self.checker = ProxyChecker()
        self.switcher = NodeSwitcher()
        self.browser = BrowserLauncher()
        self.sm = StateMachine()
        self.status = VpnStatus()
        self.tick_interval = tick_interval

        # 初始化时检测真实状态
        if self.proc.is_running():
            self.sm.force(VpnState.CONNECTED)
            self._sync_current_node()
            # 快速验证代理是否真的可用
            ok, delay = self.checker.check_connectivity()
            self.status.last_check_ms = delay
            if not ok:
                self.sm.force(VpnState.DEGRADED)
                self.status.record_failure(self.status.current_node or "unknown")

    def _sync_current_node(self):
        """从 config.json 读取当前活动节点名，同步到状态"""
        try:
            from core.config_builder import read_current_config
            cfg = read_current_config()
            for ob in cfg.get('outbounds', []):
                if ob.get('tag') == 'proxy':
                    for vn in ob.get('settings', {}).get('vnext', []):
                        addr = vn.get('address', '')
                        port = vn.get('port', '')
                        self.status.current_node = f"{addr}:{port}"
                        return
        except Exception:
            pass

    def _try_transition(self, to: VpnState) -> bool:
        try:
            self.sm.transition(to)
            self.status.state = self.sm.state
            self.status.state_since = time.monotonic()
            logger.info(f"状态: {to.name}")
            return True
        except StateError:
            logger.warning(f"非法状态转换: {self.sm.state.name} → {to.name}")
            return False

    # ========== 一键全流程 ==========

    def auto_connect(self, open_browser: bool = True) -> bool:
        logger.info("=" * 50)
        logger.info("  VPN Orchestrator - 自动连接")
        logger.info("=" * 50)

        # Step 1: 用我们的模板生成干净 config（选最优节点）
        logger.info("[1/5] 选择节点并生成配置...")
        profile = self._pick_best_profile()
        if not profile:
            logger.error("  数据库中没有节点")
            return False
        from core.config_builder import apply_profile_to_config
        apply_profile_to_config(profile)
        self._sync_current_node()

        # Step 2: 如有旧进程先停
        logger.info("[2/5] 检查旧进程...")
        if self.proc.is_running():
            logger.info("  发现运行中的 sing-box，先停止...")
            self.proc.stop()

        # Step 3: 启动
        logger.info("[3/5] 启动 sing-box...")
        self._try_transition(VpnState.CONNECTING)
        if not self.proc.start():
            self._try_transition(VpnState.DISCONNECTED)
            logger.error("  启动失败")
            return False
        self._try_transition(VpnState.CONNECTED)

        # Step 4: 验证代理
        logger.info("[4/5] 检测代理连通性...")
        online, delay = self.checker.check_connectivity()
        self.status.last_check_ms = delay
        if online:
            logger.info("  代理正常 (延迟: %.0fms)", delay)
        else:
            logger.warning("  代理不可用，尝试切换...")
            self._try_transition(VpnState.RECOVERING)
            found = self.switcher.switch_until_working()
            if not found:
                self._try_transition(VpnState.DEGRADED)
                logger.error("  所有节点均不可用")
                return False
            self._try_transition(VpnState.CONNECTED)
            self.status.reset_failures()

        # Step 5: browser
        if open_browser:
            logger.info("[5/5] 打开浏览器...")
            self.browser.open_all()
        else:
            logger.info("[5/5] 跳过浏览器")

        logger.info("  VPN 就绪!")
        return True

    def _pick_best_profile(self):
        """从数据库选最优节点（优先速度，其次延迟）。"""
        self.db.connect()
        try:
            profiles = self.db.get_all_profiles()
            if not profiles:
                return None
            scored = []
            for p in profiles:
                stats = self.db.get_profile_stats(p.index_id)
                delay = stats['delay'] if stats['delay'] > 0 else 99999
                speed = stats['speed']
                scored.append((p, delay, speed))
            scored.sort(key=lambda x: (x[1], -x[2]))
            best = scored[0]
            logger.info("  最优节点: %s (延迟: %.0fms, 速度: %.1fMB/s)",
                        best[0].remarks, best[1], best[2])
            return best[0]
        finally:
            self.db.close()

    # ========== 守护模式 (daemon tick) ==========

    def tick(self) -> VpnState:
        """
        单次健康检查 tick。供 daemon 循环调用。

        Returns:
            当前 VpnState
        """
        if self.sm.in_state(VpnState.STOPPED):
            return self.sm.state

        is_running = self.proc.is_running()
        if not is_running:
            if self.sm.in_state(VpnState.DISCONNECTED):
                logger.warning("sing-box 未运行，尝试启动...")
            else:
                logger.warning("sing-box 进程丢失，尝试重启...")
            self._try_transition(VpnState.CONNECTING)
            if self.proc.start():
                self._try_transition(VpnState.CONNECTED)
                self.status.reset_failures()
            else:
                self._try_transition(VpnState.DISCONNECTED)
                return self.sm.state

        online, delay = self.checker.check_connectivity()
        self.status.last_check_ms = delay

        if online:
            if self.sm.in_state(VpnState.DEGRADED, VpnState.RECOVERING):
                logger.info("代理恢复, 延迟: %.0fms", delay)
            self._try_transition(VpnState.CONNECTED)
            self.status.reset_failures()
        else:
            logger.warning("代理不可用 (延迟: %.0fms), 进入恢复模式", delay)
            self._try_transition(VpnState.DEGRADED)

            # 记录当前节点故障
            self._sync_current_node()
            node = self.status.current_node or "unknown"
            self.status.record_failure(node)
            logger.info("节点 %s 连续失败 %d 次", node, self.status.consecutive_failures)

            # 自动恢复
            self._try_transition(VpnState.RECOVERING)
            found = self.switcher.switch_until_working()
            self.status.total_switches += 1
            if found:
                self._try_transition(VpnState.CONNECTED)
                self.status.reset_failures()
                self._sync_current_node()
            else:
                self._try_transition(VpnState.DEGRADED)
                logger.error("所有节点不可用, %d 秒后重试", self.tick_interval)

        return self.sm.state

    # ========== 节点管理 ==========

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
        else:
            self._try_transition(VpnState.DEGRADED)
        return result

    def switch_best(self):
        self._try_transition(VpnState.SWITCHING)
        result = self.switcher.switch_to_best()
        if result:
            self._try_transition(VpnState.CONNECTED)
            self._sync_current_node()
        else:
            self._try_transition(VpnState.DEGRADED)
        return result

    def switch_working(self):
        self._try_transition(VpnState.RECOVERING)
        result = self.switcher.switch_until_working()
        if result:
            self._try_transition(VpnState.CONNECTED)
            self._sync_current_node()
        else:
            self._try_transition(VpnState.DEGRADED)
        return result

    # ========== 进程控制 ==========

    def start(self) -> bool:
        self._try_transition(VpnState.CONNECTING)
        if self.proc.start():
            self._try_transition(VpnState.CONNECTED)
            return True
        self._try_transition(VpnState.DISCONNECTED)
        return False

    def stop(self) -> bool:
        if self.proc.stop():
            self.sm.force(VpnState.STOPPED)
            self.status.state = self.sm.state
            return True
        return False

    def restart(self) -> bool:
        self._try_transition(VpnState.CONNECTING)
        if self.proc.restart():
            self._try_transition(VpnState.CONNECTED)
            return True
        self._try_transition(VpnState.DISCONNECTED)
        return False

    def status(self):
        """打印状态报告"""
        self.proc.print_status()
        online, delay = self.checker.check_connectivity()
        self.status.last_check_ms = delay
        if online:
            logger.info("  代理可用 (延迟: %.0fms)", delay)
        else:
            logger.warning("  代理不可用")

        logger.info("  状态: %s | 节点: %s | 连续失败: %d | 总切换: %d",
                     self.sm.state.name,
                     self.status.current_node or "未知",
                     self.status.consecutive_failures,
                     self.status.total_switches)

    def check_proxy(self):
        self.proc.print_status()
        result = self.checker.full_check()
        if result['online']:
            logger.info("  在线 | 延迟: %.0fms | 速度: %.1fMB/s",
                        result['delay_ms'], result['speed_mb_s'])
        else:
            logger.error("  离线 | 原因: %s", result['error'])
        return result

    def open_browsers(self):
        self.browser.open_all()

    def list_subscriptions(self):
        self.db.connect()
        try:
            self.db.print_subscriptions()
        finally:
            self.db.close()
