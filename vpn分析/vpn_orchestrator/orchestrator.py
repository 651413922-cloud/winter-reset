"""
VPN Orchestrator 高层编排器。
整合所有模块，提供一键式操作入口。
"""

import sys
import os

# 确保能找到同级包
_orch_dir = os.path.dirname(os.path.abspath(__file__))
if _orch_dir not in sys.path:
    sys.path.insert(0, _orch_dir)

import time
from typing import Optional

from core.db_manager import DbManager
from core.process_manager import ProcessManager
from core.config_builder import apply_profile_to_config
from services.proxy_checker import ProxyChecker
from services.node_switcher import NodeSwitcher
from services.browser_launcher import BrowserLauncher


class VpnOrchestrator:
    """VPN 编排器 - 高层控制入口"""

    def __init__(self):
        self.db = DbManager()
        self.proc = ProcessManager()
        self.checker = ProxyChecker()
        self.switcher = NodeSwitcher()
        self.browser = BrowserLauncher()

    # ========== 一键全流程 ==========

    def auto_connect(self, open_browser: bool = True) -> bool:
        """
        全自动连接流程：
        1. 检查当前状态
        2. 如果未运行，启动 sing-box
        3. 检测连通性
        4. 如果不可用，自动切换节点
        5. 打开 ChatGPT 和 Gemini
        
        Args:
            open_browser: 连接成功后是否打开浏览器
            
        Returns:
            是否成功连接
        """
        print("=" * 60)
        print("  VPN Orchestrator - 自动连接")
        print("=" * 60)

        # 步骤 1: 检查当前状态
        print("\n[1/5] 检查当前状态...")
        is_running = self.proc.is_running()
        if is_running:
            print("  ✅ sing-box 正在运行")
        else:
            print("  ⚠️  sing-box 未运行")

        # 步骤 2: 启动如果未运行
        print("\n[2/5] 确保 sing-box 运行中...")
        if not is_running:
            if not self.proc.start():
                print("  ❌ 启动失败")
                return False
        print("  ✅ sing-box 运行正常")

        # 步骤 3: 检测连通性
        print("\n[3/5] 检测代理连通性...")
        online, delay = self.checker.check_connectivity()
        if online:
            print(f"  ✅ 代理正常 (延迟: {delay}ms)")
        else:
            print(f"  ⚠️  代理不可用 (尝试自动切换)...")
            # 步骤 4: 自动切换
            print("\n[4/5] 自动切换节点...")
            found = self.switcher.switch_until_working()
            if not found:
                print("  ❌ 所有节点均不可用")
                return False
            print("  ✅ 已切换到可用节点")

        # 步骤 5: 打开浏览器
        if open_browser:
            print("\n[5/5] 打开浏览器...")
            self.browser.open_all()
        else:
            print("\n[5/5] 跳过浏览器")

        print("\n" + "=" * 60)
        print("  ✅ VPN 就绪!")
        print("=" * 60)
        return True

    # ========== 节点管理 ==========

    def list_nodes(self):
        """列出所有节点"""
        self.db.connect()
        try:
            self.db.print_all_profiles()
        finally:
            self.db.close()

    def switch_node(self, name_or_index):
        """切换到指定节点"""
        return self.switcher.switch_to(name_or_index)

    def switch_best(self):
        """切换到最优节点"""
        return self.switcher.switch_to_best()

    def switch_working(self):
        """切换到可用节点"""
        return self.switcher.switch_until_working()

    # ========== 进程控制 ==========

    def start(self) -> bool:
        """启动 VPN 核心"""
        return self.proc.start()

    def stop(self) -> bool:
        """停止 VPN 核心"""
        return self.proc.stop()

    def restart(self) -> bool:
        """重启 VPN 核心"""
        return self.proc.restart()

    def status(self) -> dict:
        """查看状态"""
        self.proc.print_status()
        online, delay = self.checker.check_connectivity()
        if online:
            print(f"  ✅ 代理可用 (延迟: {delay}ms)")
        else:
            print(f"  ⚠️  代理不可用")
        return {
            'running': self.proc.is_running(),
            'online': online,
            'delay_ms': delay,
        }

    # ========== 连通性检测 ==========

    def check_proxy(self) -> dict:
        """完整检测代理"""
        self.proc.print_status()
        result = self.checker.full_check()
        if result['online']:
            print(f"  ✅ 在线 | 延迟: {result['delay_ms']}ms | 速度: {result['speed_mb_s']}MB/s")
        else:
            print(f"  ❌ 离线 | 原因: {result['error']}")
        return result

    def open_browsers(self):
        """打开 ChatGPT 和 Gemini"""
        self.browser.open_all()

    # ========== 订阅管理 ==========

    def list_subscriptions(self):
        """列出所有订阅"""
        self.db.connect()
        try:
            self.db.print_subscriptions()
        finally:
            self.db.close()