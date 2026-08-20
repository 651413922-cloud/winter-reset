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

import logging
import time
from typing import Optional, List

from config import (
    get_active_core_type,
    CORE_TYPE_SING_BOX,
)
from core.db_manager import DbManager
from core.runtime_manager import RuntimeManager
from core.config_builder import apply_profile_to_config, read_current_config
from core.state import (
    VpnState, StateMachine, StateError, VpnStatus,
    RecoveryStrategy, HealthSnapshot,
)
from services.proxy_checker import ProxyChecker
from services.node_switcher import NodeSwitcher
from services.browser_launcher import BrowserLauncher
from core.system_proxy import set_global_proxy, clear_global_proxy, is_global_proxy_set

logger = logging.getLogger(__name__)


class VpnOrchestrator:
    """VPN orchestration — high-level control entry point."""

    def __init__(self, tick_interval: float = 30.0):
        self.db = DbManager()
        self.rt = RuntimeManager()
        # timeout=10（config.TIMEOUT 默认 20）：死节点一次健康检查最坏要
        # warmup 5s + 主请求 20s = 25s，会让守护/质量监控彻底钝化——实测
        # 90s 只够走一轮恢复。10s 对正常节点（80-150ms）完全够，死节点
        # 检测提速一半以上。
        self.checker = ProxyChecker(timeout=10)
        self.switcher = NodeSwitcher()
        self.browser = BrowserLauncher()
        self.sm = StateMachine()
        self.status = VpnStatus()
        self.tick_interval = tick_interval

        # 质量监控状态：延迟超标连续计数 / 上次自动切换时间（冷却用）
        self._quality_streak = 0
        self._last_quality_switch = 0.0

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
            from adapters.xray_config import find_proxy_outbound, read_config, extract_node_identifier
            cfg = read_config()
            ob, _ = find_proxy_outbound(cfg)
            if ob:
                self.status.current_node = extract_node_identifier(ob)
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

        # Step 0: Check prerequisites
        from config import get_active_core_type, CORE_TYPE_SING_BOX
        if get_active_core_type() == CORE_TYPE_SING_BOX and not RuntimeManager.is_admin():
            logger.error(
                'Admin privileges required. sing-box needs admin rights '
                'to create the TUN virtual network interface. '
                'Please run as administrator.'
            )
            return False

        warnings = self.rt.check_coexistence()
        if warnings:
            for w in warnings:
                logger.warning('CONFLICT: %s', w)
            logger.error(
                'v2rayN GUI and orchestrator cannot run simultaneously. '
                'Please close v2rayN GUI first.'
            )
            return False

        # Step 1: Pick best node, patch config
        logger.info('[1/5] Selecting node & patching config...')
        profile = self._pick_best_profile()
        if not profile:
            # 实时测速未筛出可用节点 → 直接进入兜底，按 TCP 延迟排序重试
            logger.warning('未筛到可用节点，进入兜底（按 TCP 排序重试）...')
            found = self.switcher.switch_until_working()
            if not found:
                logger.error('  All nodes failed')
                return False
            if open_browser:
                self.browser.open_all()
            logger.info('  VPN Ready! (via fallback)')
            return True

        # Step 2: Stop old processes
        logger.info('[2/5] Stopping old processes...')
        self.rt.stop()

        # Step 3: Start sing-box (TUN) + Xray (proxy)
        logger.info('[3/5] Starting sing-box + Xray...')
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

            # 缓存里没有任何可用测速数据 → 自己先实时测一轮（前 8 个候选），
            # 避免盲选到死节点。测完写回，本函数再用新鲜数据选优。
            if all(d >= 99999 for _, d, _ in scored):
                logger.warning('  缓存无可用测速数据，先实时测速一轮...')
                fresh = self.switcher.speedtest_all(limit=12, write_back=True)
                online = [r for r in fresh if r['online']]
                if online:
                    best = online[0]
                    logger.info('  Best node (fresh): %s (delay: %dms, speed: %.1fMB/s)',
                               best['profile'].remarks, best['delay'], best['speed'])
                    return best['profile']
                # 阶段2 全部节点真实校验失败 → 交给 connect_best 的兜底分支，
                # 不再盲选一个已知死节点再重连（那样只会多浪费一轮）。
                logger.warning('  [!] 实时测速无可用节点，转交兜底逻辑按 TCP 排序重试')
                return None

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
        # 按实际激活的 core type 判断"进程是否齐全"：xray-only 模式下
        # sing-box 本来就不运行，不能用 dual-process 的 sb & xray 判断，
        # 否则每轮 tick 都误判进程丢失而重启（旧 daemon 在纯 xray 机器
        # 上的隐藏 bug）。
        core_type = get_active_core_type()
        sb_running = RuntimeManager.is_singbox_running()
        xr_running = RuntimeManager.is_xray_running()
        if core_type == CORE_TYPE_SING_BOX:
            process_running = sb_running and xr_running
        else:
            process_running = xr_running
        online, latency = self.checker.check_connectivity() if process_running else (False, -1)
        self.status.update_health(online, latency, process_running)

        if not process_running:
            if not sb_running:
                logger.warning('sing-box (TUN) lost, full restart needed...')
            elif not xr_running:
                logger.warning('Xray (proxy) lost, restarting Xray only...')
                if self.rt.restart_xray():
                    time.sleep(2)
                    online, _ = self.checker.check_connectivity()
                    if online:
                        self._try_transition(VpnState.CONNECTED)
                        self.status.reset_failures()
                        self._sync_current_node()
                        return self.sm.state

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
            # 已 CONNECTED 时跳过 transition，避免每轮 tick 刷
            # "Illegal transition: CONNECTED → CONNECTED" 噪音日志
            self.status.reset_failures()
        else:
            logger.warning('Proxy unreachable (latency: %.0fms)', latency)
            if not self.sm.in_state(VpnState.DEGRADED):
                self._try_transition(VpnState.DEGRADED)
            self._sync_current_node()
            node = self.status.current_node or 'unknown'
            self.status.record_failure(node)

            logger.info('Node %s — %d consecutive failures (strategy: %s)',
                       node, self.status.consecutive_failures,
                       self.status.get_recovery_strategy().name)

            # Auto-recovery
            self._try_transition(VpnState.RECOVERING)
            # 自动恢复切节点强制「同地区交换」：只从与当前节点相同地区的
            # 节点里选，出口 IP 地区保持不变，避免目标站点（OpenAI、银行
            # 等）因 IP 地区跳变触发风控。get_current_region() 在 lambda
            # 执行时才调用，此时 config 里仍是死节点 → 拿到的正是要
            # 保持的地区。
            recovered, desc = self.rt.attempt_recovery(
                self.status,
                on_switch_node=lambda: self.switcher.switch_until_working(
                    current_region=self.switcher.get_current_region()),
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

    # ================================================================
    #  Quality monitoring (latency-threshold auto switch)
    # ================================================================

    def monitor_once(self, latency_threshold_ms: float = 600.0,
                     min_consecutive: int = 3,
                     cooldown_s: float = 60.0,
                     allow_cross_region: bool = False) -> VpnState:
        """Single quality-monitoring round: basic health tick first, then
        auto-switch when the current node is *online but consistently slow*.

        - 滞回: 单次抖动不切，必须连续 min_consecutive 次延迟超标
          （默认 3 次 ≈ 1.5 分钟），避免误切。
        - 冷却: 切换成功后 cooldown_s 秒内不再切换，防止来回横跳。
        - 预筛: 切换前先并发真实测速候选节点（临时端口，不影响当前
          连接），确认新节点可用才动主进程，把断流窗口压到最小。
        - 同地区交换: 自动切换默认只在与当前节点相同地区的候选里选，
          出口 IP 地区保持不变，避免目标站点因 IP 地区跳变触发风控；
          allow_cross_region=True 时才允许跨地区兜底。
        """
        state = self.tick()
        if state != VpnState.CONNECTED:
            return state

        latency = self.status.last_health.latency_ms
        if latency < 0 or latency <= latency_threshold_ms:
            self._quality_streak = 0
            return state

        self._quality_streak += 1
        if self._quality_streak < min_consecutive:
            logger.warning(
                '[质量] 延迟 %.0fms 超过阈值 %.0fms（连续 %d/%d，暂不切换）',
                latency, latency_threshold_ms,
                self._quality_streak, min_consecutive)
            return state

        since = time.monotonic() - self._last_quality_switch
        if self._last_quality_switch > 0 and since < cooldown_s:
            logger.warning('[质量] 冷却期内（%.0fs/%.0fs）不重复切换，继续观察',
                           since, cooldown_s)
            self._quality_streak = 0
            return state

        logger.warning('[质量] 延迟连续 %d 次超阈值（最近 %.0fms），准备切换...',
                       min_consecutive, latency)
        self._quality_streak = 0
        return self._quality_switch(latency_threshold_ms, allow_cross_region)

    def _quality_switch(self, latency_threshold_ms: float,
                        allow_cross_region: bool = False) -> VpnState:
        """Switch to the best candidate whose *measured* latency is below the
        threshold.  Candidates are probed concurrently on temp ports first, so
        the main proxy stays up during selection; only the final apply+restart
        (a few seconds) interrupts the connection.

        自动切换默认「同地区交换」：只在与当前节点相同地区的候选里选，
        出口 IP 地区保持不变，避免目标站点（OpenAI、银行等）因 IP 地区
        跳变触发风控；allow_cross_region=True 时才允许跨地区兜底。
        """
        current = self.status.current_node
        # 从 config.json 当前 outbound 反查当前节点地区（自动切换的
        # 基准地区）；解析失败返回 None → 退化为不限地区。
        current_region = self.switcher.get_current_region()
        self._try_transition(VpnState.SWITCHING)

        logger.info('[质量] 并发测速候选节点（不影响当前连接）...')
        try:
            # prefer_region: 阶段1 排序同地区节点优先进入真实校验，
            # 保证候选集覆盖当前地区（防风控同地区交换）。
            results = self.switcher.speedtest_all(
                limit=12, write_back=True, prefer_region=current_region)
        except Exception:
            logger.exception('[质量] 候选测速失败，保留当前节点')
            self._try_transition(VpnState.CONNECTED)
            return VpnState.CONNECTED

        online = [r for r in results if r['online']
                  and r['delay'] < latency_threshold_ms
                  and r['profile'].remarks != current]
        if current_region:
            # 同地区交换（防风控）：优先从同地区候选里选
            same_region = [r for r in online
                           if self.switcher.extract_region(
                               r['profile'].remarks) == current_region]
            if not same_region:
                if not allow_cross_region:
                    logger.warning(
                        '[质量] 同地区(%s)没有低于 %.0fms 的候选，'
                        '为防触发风控不跨地区切换，保留当前节点',
                        current_region, latency_threshold_ms)
                    self._try_transition(VpnState.CONNECTED)
                    return VpnState.CONNECTED
                logger.warning('[质量] 同地区(%s)无可用候选，跨地区兜底',
                               current_region)
            else:
                logger.info('[质量] 同地区(%s)候选 %d 个，优先同地区切换',
                            current_region, len(same_region))
                online = same_region
        if not online:
            logger.warning('[质量] 没有延迟低于 %.0fms 的候选，保留当前节点',
                           latency_threshold_ms)
            self._try_transition(VpnState.CONNECTED)
            return VpnState.CONNECTED

        best = online[0]
        logger.info('[质量] 候选最优: %s（%dms, %.2fMB/s）',
                    best['profile'].remarks, best['delay'], best['speed'])

        # 应用 → 重启 → 校验（此处才有几秒断流）
        apply_profile_to_config(best['profile'])
        self._sync_current_node()
        self.rt.stop()
        if not self.rt.start():
            logger.error('[质量] 新节点启动失败，进入降级')
            self._try_transition(VpnState.DEGRADED)
            return VpnState.DEGRADED

        ok, latency = ProxyChecker(timeout=10).check_connectivity()
        self.status.update_health(ok, latency, self.rt.is_running())
        if ok:
            from config import get_socks_port_from_config
            set_global_proxy('127.0.0.1', get_socks_port_from_config())
            self._try_transition(VpnState.CONNECTED)
            self.status.reset_failures()
            self._last_quality_switch = time.monotonic()
            logger.info('[质量] 已切换至 %s（%.0fms），系统代理保持全局',
                        best['profile'].remarks, latency)
            return VpnState.CONNECTED

        logger.error('[质量] 新节点 %s 校验失败，进入降级',
                     best['profile'].remarks)
        self._try_transition(VpnState.DEGRADED)
        return VpnState.DEGRADED

    def _restore_and_restart(self) -> bool:
        """Restore config from backup and restart."""
        from adapters.xray_config import restore_config
        return restore_config()

    # ================================================================
    #  Node management
    # ================================================================

    def get_regions(self) -> dict:
        """去重统计所有地区 {地区: 节点数}，供托盘设置菜单动态展示。"""
        return self.switcher.get_regions()

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

    def connect_best(self, open_browser: bool = False,
                     regions: Optional[List[str]] = None) -> bool:
        """
        扫描 → 选优 → 连接（一次性）。等价 v2rayN「测试后连接」，
        也是自动化入口：并发测速所有节点 → 选最优可用 → 应用配置 → 启动 → 校验。

        regions: 只测/选 remarks 含这些关键词的节点（None=全部），
                 用于「按地区选最优」（如 ['香港']、['日本']、['新加坡']）。
        """
        logger.info('=' * 50)
        logger.info('  VPN Orchestrator — Scan → Select → Connect')
        logger.info('=' * 50)

        # 前置检查
        from config import get_active_core_type, CORE_TYPE_SING_BOX
        if get_active_core_type() == CORE_TYPE_SING_BOX and not RuntimeManager.is_admin():
            logger.error(
                'Admin privileges required for sing-box TUN mode. '
                'Please run as administrator.'
            )
            return False
        warnings = self.rt.check_coexistence()
        if warnings:
            for w in warnings:
                logger.warning('CONFLICT: %s', w)
            logger.error(
                'v2rayN GUI and orchestrator cannot run simultaneously. '
                'Please close v2rayN GUI first.'
            )
            return False

        # Step 1: 并发测速所有节点
        logger.info('[1/4] 并发测速所有节点...')
        results = self.switcher.speedtest_all(limit=None, write_back=True,
                                              regions=regions)
        online = [r for r in results if r['online']]
        if not online:
            if regions:
                logger.error('[X] 指定地区 %s 没有可用节点，请稍后重试或换地区', regions)
                return False
            # 并发测速保守（部分节点 tunnel 建立慢）没筛出时，退化为
            # 顺序逐个实测，只要有一个节点真能连就一定能连上。
            logger.warning('[!] 并发测速未筛出可用节点，改用顺序逐个实测兜底...')
            return self.switcher.switch_until_working()

        # Step 2: 选最优
        best = online[0]
        chat_flag = 'ChatGPT[OK]' if best.get('chatgpt') else 'ChatGPT[x]'
        logger.info('[2/4] 最优节点: %s (%dms, %.2fMB/s, %s)',
                    best['profile'].remarks, best['delay'], best['speed'], chat_flag)

        # Step 3+4: 逐个候选应用 / 启动 / 校验（best 优先，失败自动试下一个 online 节点）
        # 之前只试 best[0]，一个抖动节点就会让整次自动连接失败；现在对扫描筛出的
        # 所有 online 节点顺序兜底，最大化「连上」的概率。
        for rank, cand in enumerate(online, start=1):
            logger.info('[3/4] 应用节点并启动 xray（候选 %d/%d: %s）...',
                        rank, len(online), cand['profile'].remarks)
            apply_profile_to_config(cand['profile'])
            self._sync_current_node()
            self.rt.stop()
            if not self.rt.start():
                logger.error('  [X] 启动失败，跳过该节点')
                continue
            # Step 4: 校验
            logger.info('[4/4] 校验连通性...')
            online_flag, latency = ProxyChecker(timeout=10).check_connectivity()
            if online_flag:
                logger.info('  [OK] 已连接 (延迟 %.0fms)', latency)
                # 把真实延迟写回状态机，托盘/状态栏才能显示正确数值
                # （否则 last_health 仍是过期值 -1，托盘会显示 -1ms）。
                self.status.update_health(online_flag, latency, self.rt.is_running())
                # 状态机：rt.stop() 后当前态为 DISCONNECTED/STOPPED，须先经
                # CONNECTING 再转 CONNECTED。直接 DISCONNECTED→CONNECTED 会
                # 触发 Illegal transition 告警（功能无碍，纯日志噪音）。
                self._try_transition(VpnState.CONNECTING)
                self._try_transition(VpnState.CONNECTED)
                self.status.reset_failures()
                # 像 v2rayN 一样把系统代理设为全局，所有浏览器/应用自动走代理
                from config import get_socks_port_from_config
                set_global_proxy('127.0.0.1', get_socks_port_from_config())
                if open_browser:
                    self.browser.open_all()
                return True
            logger.warning('  [!] 候选 %d/%d（%s）连接后校验失败，自动尝试下一个节点',
                           rank, len(online), cand['profile'].remarks)
            self.rt.stop()

        # 所有 online 候选都未通过连接后校验
        logger.error('  [x] 所有候选节点连接后校验均失败')
        # 失败路径状态机：先 CONNECTING 再 DEGRADED（STOPPED→DEGRADED 非法，
        # 会触发 Illegal transition 告警；与成功路径 CONNECTING→CONNECTED 对称）。
        self._try_transition(VpnState.CONNECTING)
        self._try_transition(VpnState.DEGRADED)
        return False

    # ================================================================
    #  系统代理（全局，镜像 v2rayN 行为）
    # ================================================================

    def enable_system_proxy(self) -> bool:
        """将 Windows 系统代理设为全局 SOCKS/HTTP（127.0.0.1:<入站端口>）。

        使所有浏览器与应用程序自动走代理，无需为每个浏览器单独配置。
        """
        from config import get_socks_port_from_config
        return set_global_proxy('127.0.0.1', get_socks_port_from_config())

    def disable_system_proxy(self) -> bool:
        """关闭系统代理（恢复直连）。"""
        return clear_global_proxy()

    def is_system_proxy_enabled(self) -> bool:
        from config import get_socks_port_from_config
        return is_global_proxy_set('127.0.0.1', get_socks_port_from_config())

    def speedtest_nodes(self, limit: int = None, write_back: bool = True):
        """实时测速并（可选）写回数据库。等价于 v2rayN 的「测试」功能。"""
        results = self.switcher.speedtest_all(limit=limit, write_back=write_back)
        print(f"\n测速完成 {len(results)} 个节点:")
        print("-" * 70)
        for r in results:
            p = r['profile']
            if r['online']:
                cg = 'ChatGPT[OK]' if r.get('chatgpt') else 'ChatGPT[x]'
                print(f"  [OK] {p.remarks} | {p.address}:{p.port} | "
                      f"{r['delay']}ms | {r['speed']:.2f}MB/s | {cg}")
            else:
                print(f"  [x] {p.remarks} | {p.address}:{p.port} | {r['error']}")
        online = [r for r in results if r['online']]
        if online:
            best = online[0]
            cg = 'ChatGPT[OK]' if best.get('chatgpt') else 'ChatGPT[x]'
            print(f"\n最优可用节点: {best['profile'].remarks} | "
                  f"{best['delay']}ms | {best['speed']:.2f}MB/s | {cg}")
        else:
            print("\n[!] 没有节点可用（全部离线/被封锁/数据损坏）")
        return results

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

    def print_status_report(self):
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
