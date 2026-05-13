"""
sing-box 进程管理器。
查找、启动、停止、重启 sing-box 核心。
"""

import subprocess
import signal
import time
import sys, os
from typing import Optional

import psutil

_orch_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _orch_root not in sys.path:
    sys.path.insert(0, _orch_root)

from config import SING_BOX_EXE, CONFIG_JSON


class ProcessManager:
    """管理 sing-box 进程"""

    def __init__(self, exe_path: str = SING_BOX_EXE,
                 config_path: str = CONFIG_JSON):
        self.exe_path = exe_path
        self.config_path = config_path
        self._process: Optional[subprocess.Popen] = None

    # ========== 查找进程 ==========

    @staticmethod
    def find_singbox_process() -> Optional[psutil.Process]:
        """查找系统中正在运行的 sing-box.exe 进程"""
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] and 'sing-box' in proc.info['name'].lower():
                    return proc
                if proc.info['cmdline']:
                    cmd = ' '.join(proc.info['cmdline']).lower()
                    if 'sing-box' in cmd:
                        return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    @staticmethod
    def is_running() -> bool:
        """检查 sing-box 是否正在运行"""
        return ProcessManager.find_singbox_process() is not None

    # ========== 停止进程 ==========

    @staticmethod
    def stop() -> bool:
        """停止正在运行的 sing-box
        
        Returns:
            True 表示成功停止（或本来就没运行）
        """
        proc = ProcessManager.find_singbox_process()
        if not proc:
            print("[进程] sing-box 未在运行")
            return True

        try:
            print(f"[进程] 正在停止 sing-box (PID: {proc.pid})...")
            # 先优雅终止
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                print("[进程] 超时，强制终止...")
                proc.kill()
                proc.wait(timeout=3)
            print("[进程] sing-box 已停止")
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            print(f"[进程] 停止失败: {e}")
            return False

    # ========== 启动进程 ==========

    def start(self, timeout: float = 5.0) -> bool:
        """启动 sing-box
        
        Args:
            timeout: 等待启动完成的最长时间（秒）
            
        Returns:
            True 表示启动成功且进程运行正常
        """
        if self.is_running():
            print("[进程] sing-box 已在运行")
            return True

        if not self._check_exe():
            return False

        try:
            print(f"[进程] 启动 sing-box...")
            # sing-box 1.12+ 需要该环境变量以兼容旧版 DNS 配置
            env = os.environ.copy()
            env['ENABLE_DEPRECATED_LEGACY_DNS_SERVERS'] = 'true'
            
            self._process = subprocess.Popen(
                [self.exe_path, 'run', '-c', self.config_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=env,
            )

            # 等待进程启动
            time.sleep(1.5)
            if not self.is_running():
                # 检查是否立即退出了
                poll = self._process.poll()
                if poll is not None:
                    _, stderr = self._process.communicate(timeout=2)
                    err_msg = stderr.decode('utf-8', errors='replace')[:500] if stderr else ''
                    print(f"[进程] 启动失败 (退出码: {poll})")
                    if err_msg:
                        # 只显示关键行
                        for line in err_msg.split('\n'):
                            if 'FATAL' in line or 'ERROR' in line:
                                print(f"  {line.strip()}")
                else:
                    print("[进程] 启动失败（进程未出现）")
                return False

            print(f"[进程] sing-box 已启动 (PID: {self._process.pid})")
            return True

        except Exception as e:
            print(f"[进程] 启动异常: {e}")
            return False

    # ========== 重启 ==========

    def restart(self) -> bool:
        """重启 sing-box（停止 → 启动）"""
        print("\n[进程] 重启 sing-box...")
        self.stop()
        time.sleep(1)
        return self.start()

    # ========== 工具方法 ==========

    def _check_exe(self) -> bool:
        """验证 sing-box.exe 是否存在"""
        import os
        if not os.path.exists(self.exe_path):
            print(f"[错误] 找不到 sing-box: {self.exe_path}")
            return False
        return True

    def print_status(self):
        """打印当前 sing-box 状态"""
        proc = self.find_singbox_process()
        if proc:
            mem = proc.memory_info().rss / 1024 / 1024
            cpu = proc.cpu_percent()
            print(f"[状态] sing-box 运行中 (PID: {proc.pid})")
            print(f"       内存: {mem:.1f} MB | CPU: {cpu:.1f}%")
        else:
            print("[状态] sing-box 未运行")