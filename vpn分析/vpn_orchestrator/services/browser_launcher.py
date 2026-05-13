"""
浏览器启动器。
打开 ChatGPT 和 Gemini 页面。
"""

import logging
import time
import webbrowser
import sys, os
from typing import List

_orch_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _orch_root not in sys.path:
    sys.path.insert(0, _orch_root)

from config import BROWSER_TARGETS

logger = logging.getLogger(__name__)


class BrowserLauncher:
    """启动系统浏览器打开目标网站"""

    def __init__(self, targets: List[str] = None):
        self.targets = targets or BROWSER_TARGETS

    def open_all(self, delay: float = 1.5):
        if not self.targets:
            logger.warning("没有配置目标 URL")
            return

        logger.info("正在打开 %d 个页面...", len(self.targets))
        for i, url in enumerate(self.targets):
            try:
                webbrowser.open_new_tab(url)
                logger.info("  %d. %s", i + 1, url)
                if i < len(self.targets) - 1:
                    time.sleep(delay)
            except Exception as e:
                logger.error("  %s: %s", url, e)

        logger.info("浏览器启动完成")

    def open_single(self, url: str):
        try:
            webbrowser.open_new_tab(url)
            logger.info("打开: %s", url)
            return True
        except Exception as e:
            logger.error("打开失败 %s: %s", url, e)
            return False

    @staticmethod
    def list_targets() -> List[str]:
        """列出所有目标 URL"""
        return BROWSER_TARGETS