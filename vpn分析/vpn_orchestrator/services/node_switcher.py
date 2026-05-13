"""
节点切换器。
自动/手动切换 sing-box 的活动节点。
"""

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


class NodeSwitcher:
    """节点切换与自动选优"""

    def __init__(self):
        self.db = DbManager()
        self.proc = ProcessManager()
        self.checker = ProxyChecker()

    # ========== 按名称切换 ==========

    def switch_to(self, name_or_index) -> bool:
        """
        切换到指定节点（名称模糊匹配或数字索引）
        
        Args:
            name_or_index: 节点名称（支持模糊匹配）或数字（1-based 索引）
            
        Returns:
            是否切换成功
        """
        self.db.connect()
        try:
            profiles = self.db.get_all_profiles()
            if not profiles:
                print("[错误] 数据库中没有节点")
                return False

            # 按数字索引
            if isinstance(name_or_index, int) or name_or_index.isdigit():
                idx = int(name_or_index) - 1
                if 0 <= idx < len(profiles):
                    profile = profiles[idx]
                else:
                    print(f"[错误] 索引 {name_or_index} 超出范围 (1-{len(profiles)})")
                    return False
            else:
                # 按名称模糊匹配
                profile = self.db.get_profile_by_name(str(name_or_index))
                if not profile:
                    print(f"[错误] 未找到匹配的节点: {name_or_index}")
                    # 列出可用节点
                    self.db.print_all_profiles()
                    return False

            return self._apply_and_restart(profile)
        finally:
            self.db.close()

    # ========== 选择最优节点 ==========

    def switch_to_best(self) -> bool:
        """
        自动选择最优节点（延迟最低且速度最快）
        
        排序策略：
        1. 有延迟数据且 > 0 的优先
        2. 按延迟升序
        3. 同延迟按速度降序
        
        Returns:
            是否切换成功
        """
        self.db.connect()
        try:
            profiles = self.db.get_all_profiles()
            scored: List[Tuple[ProfileItem, float, float]] = []

            for p in profiles:
                stats = self.db.get_profile_stats(p.index_id)
                delay = stats['delay']
                speed = stats['speed']
                scored.append((p, delay if delay > 0 else 99999, speed))

            # 排序：延迟升序 → 速度降序
            scored.sort(key=lambda x: (x[1], -x[2]))

            if not scored:
                print("[错误] 无可用节点")
                return False

            best = scored[0]
            print(f"[最优] {best[0].remarks} | 延迟: {best[1]}ms | 速度: {best[2]}MB/s")

            return self._apply_and_restart(best[0])
        finally:
            self.db.close()

    # ========== 遍历切换（直到可用） ==========

    def switch_until_working(self, max_attempts: int = 6) -> bool:
        """
        逐个切换节点，直到找到一个能正常工作的。
        按速度从高到低尝试。
        
        Args:
            max_attempts: 最多尝试几个节点
            
        Returns:
            是否找到可用节点
        """
        self.db.connect()
        try:
            profiles = self.db.get_all_profiles()

            # 按速度降序排列
            scored = []
            for p in profiles:
                stats = self.db.get_profile_stats(p.index_id)
                scored.append((p, stats['speed']))
            scored.sort(key=lambda x: -x[1])

            for i, (profile, speed) in enumerate(scored[:max_attempts]):
                print(f"\n--- 尝试 {i+1}/{min(max_attempts, len(scored))}: {profile.remarks} ---")
                ok = self._apply_and_restart(profile)
                if not ok:
                    continue

                # 检测连通性
                online, delay = self.checker.check_connectivity()
                if online:
                    print(f"✅ [{profile.remarks}] 可用! 延迟: {delay}ms")
                    return True
                else:
                    print(f"❌ [{profile.remarks}] 不可用")

            print("[失败] 所有节点均不可用")
            return False
        finally:
            self.db.close()

    # ========== 内部方法 ==========

    def _apply_and_restart(self, profile: ProfileItem) -> bool:
        """应用配置并重启核心"""
        print(f"\n[切换] 切换到: {profile.display()}")

        # 1. 写 config.json
        apply_profile_to_config(profile)

        # 2. 重启 sing-box
        if not self.proc.restart():
            print("[错误] sing-box 重启失败")
            return False

        # 3. 等待启动并检测
        time.sleep(2)
        if self.proc.is_running():
            print("[切换] sing-box 运行正常")
            return True
        else:
            print("[错误] sing-box 未正常启动")
            return False