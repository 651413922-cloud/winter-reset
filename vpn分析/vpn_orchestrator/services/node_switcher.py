"""
节点切换器。
自动/手动切换 sing-box 的活动节点。
"""

import logging
import time
import sys, os
from typing import List, Optional, Tuple

_orch_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _orch_root not in sys.path:
    sys.path.insert(0, _orch_root)

from models.profile import ProfileItem
from core.db_manager import DbManager
from core.config_builder import apply_profile_to_config
from core.process_manager import ProcessManager
from services.proxy_checker import ProxyChecker

logger = logging.getLogger(__name__)


class NodeSwitcher:
    """节点切换与自动选优"""

    def __init__(self):
        self.db = DbManager()
        self.proc = ProcessManager()
        self.checker = ProxyChecker()

    # ========== 按名称切换 ==========

    def switch_to(self, name_or_index) -> bool:
        self.db.connect()
        try:
            profiles = self.db.get_all_profiles()
            if not profiles:
                logger.error("数据库中没有节点")
                return False

            if isinstance(name_or_index, int) or name_or_index.isdigit():
                idx = int(name_or_index) - 1
                if 0 <= idx < len(profiles):
                    profile = profiles[idx]
                else:
                    logger.error("索引 %s 超出范围 (1-%d)", name_or_index, len(profiles))
                    return False
            else:
                profile = self.db.get_profile_by_name(str(name_or_index))
                if not profile:
                    logger.error("未找到匹配的节点: %s", name_or_index)
                    self.db.print_all_profiles()
                    return False

            return self._apply_and_restart(profile)
        finally:
            self.db.close()

    # ========== 选择最优节点 ==========

    def switch_to_best(self) -> bool:
        self.db.connect()
        try:
            profiles = self.db.get_all_profiles()
            scored: List[Tuple[ProfileItem, float, float]] = []

            for p in profiles:
                stats = self.db.get_profile_stats(p.index_id)
                delay = stats['delay']
                speed = stats['speed']
                scored.append((p, delay if delay > 0 else 99999, speed))

            scored.sort(key=lambda x: (x[1], -x[2]))

            if not scored:
                logger.error("无可用节点")
                return False

            best = scored[0]
            logger.info("最优节点: %s | 延迟: %.0fms | 速度: %.1fMB/s",
                        best[0].remarks, best[1], best[2])

            return self._apply_and_restart(best[0])
        finally:
            self.db.close()

    # ========== 遍历切换（直到可用） ==========

    def switch_until_working(self, max_attempts: int = 6) -> bool:
        self.db.connect()
        try:
            profiles = self.db.get_all_profiles()

            scored = []
            for p in profiles:
                stats = self.db.get_profile_stats(p.index_id)
                scored.append((p, stats['speed']))
            scored.sort(key=lambda x: -x[1])

            for i, (profile, speed) in enumerate(scored[:max_attempts]):
                logger.info("--- 尝试 %d/%d: %s ---",
                            i + 1, min(max_attempts, len(scored)), profile.remarks)
                ok = self._apply_and_restart(profile)
                if not ok:
                    continue

                online, delay = self.checker.check_connectivity()
                if online:
                    logger.info("%s 可用! 延迟: %.0fms", profile.remarks, delay)
                    return True
                else:
                    logger.warning("%s 不可用", profile.remarks)

            logger.error("所有节点均不可用")
            return False
        finally:
            self.db.close()

    # ========== 内部方法 ==========

    def _apply_and_restart(self, profile: ProfileItem) -> bool:
        logger.info("切换到: %s", profile.display())

        apply_profile_to_config(profile)

        if not self.proc.restart():
            logger.error("sing-box 重启失败")
            return False

        time.sleep(2)
        if self.proc.is_running():
            logger.info("sing-box 运行正常")
            return True
        else:
            logger.error("sing-box 未正常启动")
            return False
