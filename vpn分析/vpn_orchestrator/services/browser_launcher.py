"""
浏览器启动器。
打开 ChatGPT 和 Gemini 页面。
"""

import webbrowser
import sys, os
from typing import List

_orch_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _orch_root not in sys.path:
    sys.path.insert(0, _orch_root)

from config import BROWSER_TARGETS


class BrowserLauncher:
    """启动系统浏览器打开目标网站"""

    def __init__(self, targets: List[str] = None):
        self.targets = targets or BROWSER_TARGETS

    def open_all(self, delay: float = 1.5):
        """
        打开所有目标网站（新标签页）
        
        Args:
            delay: 每个标签页之间的延迟（秒）
        """
        if not self.targets:
            print("[浏览器] 没有配置目标 URL")
            return

        print(f"\n[浏览器] 正在打开 {len(self.targets)} 个页面...")
        for i, url in enumerate(self.targets):
            try:
                webbrowser.open_new_tab(url)
                print(f"  ✅ {i+1}. {url}")
                import time
                if i < len(self.targets) - 1:
                    time.sleep(delay)
            except Exception as e:
                print(f"  ❌ {url}: {e}")

        print("[浏览器] 完成")

    def open_single(self, url: str):
        """打开单个 URL"""
        try:
            webbrowser.open_new_tab(url)
            print(f"  ✅ {url}")
            return True
        except Exception as e:
            print(f"  ❌ {url}: {e}")
            return False

    @staticmethod
    def list_targets() -> List[str]:
        """列出所有目标 URL"""
        return BROWSER_TARGETS