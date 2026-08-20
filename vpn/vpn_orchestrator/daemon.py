"""
VPN 守护进程。
持续监控代理健康状态，断线自动恢复。

用法:
    python daemon.py              # 直接运行，默认 30s 间隔
    python daemon.py --interval 15  # 15s 检查间隔
    python main.py daemon 10      # 通过主入口，10s 间隔

特性:
    - 周期性代理连通性检测
    - 断线自动切换节点（按速度从高到低尝试）
    - 所有节点不可用时进入退避等待（backoff）然后重试
    - 优雅退出（Ctrl+C / SIGTERM）
    - 结构化日志 + 状态变更事件
"""

import logging
import signal
import sys
import time
from typing import Optional

from orchestrator import VpnOrchestrator

logger = logging.getLogger(__name__)


class VpnDaemon:
    """VPN 守护进程：周期性健康检查 + 自动故障转移"""

    def __init__(self,
                 orchestrator: Optional[VpnOrchestrator] = None,
                 interval: float = 30.0,
                 max_backoff: float = 300.0,
                 latency_threshold_ms: float = 600.0,
                 min_consecutive: int = 3,
                 cooldown_s: float = 60.0,
                 allow_cross_region: bool = False):
        """
        Args:
            orchestrator: 已有的 VpnOrchestrator 实例（None 则新建）
            interval: 健康检查间隔（秒）
            max_backoff: 全部节点失败后的最大等待时间（秒）
            latency_threshold_ms: 质量阈值——当前节点延迟连续超过该值
                将自动切换到更优节点（0 表示关闭质量自动切换）
            min_consecutive: 延迟超标需连续多少次才触发切换（滞回）
            cooldown_s: 两次自动切换之间的最小间隔（防止来回横跳）
            allow_cross_region: 是否允许跨地区切换。默认 False：自动切换
                强制「同地区交换」，只在与当前节点相同地区的节点里选，
                出口 IP 地区保持不变，避免目标站点因 IP 地区跳变触发风控；
                True 时才在同地区无可用节点时跨地区兜底。
        """
        self.orch = orchestrator or VpnOrchestrator(tick_interval=interval)
        self.interval = interval
        self.max_backoff = max_backoff
        self.latency_threshold_ms = latency_threshold_ms
        self.min_consecutive = min_consecutive
        self.cooldown_s = cooldown_s
        self.allow_cross_region = allow_cross_region
        self._running = False
        self._backoff = interval  # 当前退避等待时间，随连续失败增长
        self._tick_count = 0

        # 注册信号处理
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    # ========== 主循环 ==========

    def run(self):
        """启动守护循环（阻塞直到退出）"""
        self._running = True
        logger.info("=" * 50)
        logger.info("  VPN Daemon 启动")
        logger.info("  检查间隔: %.0fs | 最大退避: %.0fs", self.interval, self.max_backoff)
        if self.latency_threshold_ms > 0:
            logger.info("  质量监控: 延迟 > %.0fms 连续 %d 次自动切换（冷却 %ds）",
                        self.latency_threshold_ms, self.min_consecutive,
                        self.cooldown_s)
            logger.info("  切换策略: %s",
                        "允许跨地区兜底" if self.allow_cross_region
                        else "同地区交换（防触发风控）")
        logger.info("=" * 50)

        # 首次启动：确保 VPN 在线
        if not self.orch.rt.is_running():
            logger.info("首次启动，执行 auto_connect...")
            self.orch.auto_connect(open_browser=False)

        # 主循环
        while self._running:
            try:
                self._tick_count += 1

                if self.latency_threshold_ms > 0:
                    # 质量监控模式：在线但延迟持续超标 → 自动切换更优节点
                    # （默认同地区交换，防出口 IP 地区跳变触发风控）
                    state = self.orch.monitor_once(
                        self.latency_threshold_ms,
                        self.min_consecutive,
                        self.cooldown_s,
                        self.allow_cross_region,
                    )
                else:
                    state = self.orch.tick()

                if state.name in ('CONNECTED',):
                    self._backoff = self.interval  # 恢复后重置退避
                elif state.name in ('DEGRADED', 'DISCONNECTED', 'FAILED'):
                    # 退避增长
                    self._backoff = min(self._backoff * 1.5, self.max_backoff)
                    logger.warning(
                        "所有节点不可用, 将在 %.0f 秒后重试 (tick #%d)",
                        self._backoff, self._tick_count
                    )
                    time.sleep(self._backoff)
                    continue

                time.sleep(self.interval)

            except KeyboardInterrupt:
                break
            except Exception:
                logger.exception("tick 异常 (#%d), 继续下一轮", self._tick_count)
                time.sleep(self.interval)

        self._shutdown()

    # ========== 优雅退出 ==========

    def _handle_signal(self, signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info("收到信号 %s，正在退出...", sig_name)
        self._running = False

    def _shutdown(self):
        logger.info("Daemon 退出")

        # 打印运行摘要
        self.orch.print_status_report()

        logger.info(
            "摘要: %d ticks | 切换 %d 次 | 连续失败 %d",
            self._tick_count,
            self.orch.status.total_switches,
            self.orch.status.consecutive_failures,
        )

        if self.orch.status.node_failures:
            logger.info("节点故障统计:")
            for node, count in sorted(
                self.orch.status.node_failures.items(),
                key=lambda x: -x[1]
            ):
                logger.info("  %s: %d 次", node, count)


# ========== 独立运行入口 ==========

if __name__ == '__main__':
    import os
    _orch_root = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, _orch_root)
    from core.logging_config import setup_logging

    _debug = '--debug' in sys.argv
    setup_logging(debug=_debug)

    # 解析 --interval N
    interval = 30.0
    for i, arg in enumerate(sys.argv):
        if arg == '--interval' and i + 1 < len(sys.argv):
            interval = float(sys.argv[i + 1])
            break

    daemon = VpnDaemon(interval=interval)
    try:
        daemon.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.exception("致命错误: %s", e)
        sys.exit(1)
