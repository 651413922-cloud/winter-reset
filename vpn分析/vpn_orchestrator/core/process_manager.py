"""
sing-box 进程管理器。
查找、启动、停止、重启 sing-box 核心。
"""

import logging
import subprocess
import time
import sys, os
from typing import Optional

import psutil

_orch_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _orch_root not in sys.path:
    sys.path.insert(0, _orch_root)

from config import SING_BOX_EXE, CONFIG_JSON

logger = logging.getLogger(__name__)


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
        proc = ProcessManager.find_singbox_process()
        if not proc:
            logger.info("sing-box 未在运行")
            return True

        try:
            logger.info("正在停止 sing-box (PID: %d)...", proc.pid)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                logger.warning("停止超时，强制终止...")
                proc.kill()
                proc.wait(timeout=3)
            logger.info("sing-box 已停止")
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.error("停止失败: %s", e)
            return False

    # ========== 启动进程 ==========

    def start(self, timeout: float = 5.0) -> bool:
        if self.is_running():
            logger.info("sing-box 已在运行")
            return True

        if not self._check_exe():
            return False

        try:
            logger.info("启动 sing-box...")
            env = os.environ.copy()
            env['ENABLE_DEPRECATED_LEGACY_DNS_SERVERS'] = 'true'

            self._process = subprocess.Popen(
                [self.exe_path, 'run', '-c', self.config_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=env,
            )

            time.sleep(1.5)
            if not self.is_running():
                poll = self._process.poll()
                if poll is not None:
                    _, stderr = self._process.communicate(timeout=2)
                    err_msg = stderr.decode('utf-8', errors='replace')[:500] if stderr else ''
                    logger.error("启动失败 (退出码: %d)", poll)
                    if err_msg:
                        for line in err_msg.split('\n'):
                            if 'FATAL' in line or 'ERROR' in line:
                                logger.error("  %s", line.strip())
                else:
                    logger.error("启动失败（进程未出现）")
                return False

            logger.info("sing-box 已启动 (PID: %d)", self._process.pid)
            return True

        except Exception as e:
            logger.error("启动异常: %s", e)
            return False

    # ========== 重启 ==========

    def restart(self) -> bool:
        logger.info("重启 sing-box...")
        self.stop()
        time.sleep(1)
        return self.start()

    # ========== 工具方法 ==========

    def _check_exe(self) -> bool:
        import os
        if not os.path.exists(self.exe_path):
            logger.error("找不到 sing-box: %s", self.exe_path)
            return False
        return True

    def print_status(self):
        """打印当前 sing-box 状态"""
        proc = self.find_singbox_process()
        if proc:
            mem = proc.memory_info().rss / 1024 / 1024
            cpu = proc.cpu_percent()
            logger.info("sing-box 运行中 (PID: %d) | 内存: %.1f MB | CPU: %.1f%%",
                        proc.pid, mem, cpu)
        else:
            logger.info("sing-box 未运行")
