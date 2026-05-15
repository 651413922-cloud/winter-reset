"""
代理连通性检测器。
通过 SOCKS5 代理发送 HTTP 请求来检测代理是否可用。
"""

import time
import sys, os
import requests
from typing import Tuple, Optional

_orch_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _orch_root not in sys.path:
    sys.path.insert(0, _orch_root)

from config import get_socks_proxy, CHECK_URL, TIMEOUT, SPEED_TEST_URL


class ProxyChecker:
    """检测代理连通性和性能"""

    def __init__(self, proxy_url: str = None,
                 check_url: str = CHECK_URL,
                 timeout: int = TIMEOUT):
        self.proxy_url = proxy_url or get_socks_proxy()
        self.check_url = check_url
        self.timeout = timeout

    def _get_session(self) -> requests.Session:
        """创建一个配置了代理的 requests Session"""
        session = requests.Session()
        session.proxies = {
            'http': self.proxy_url,
            'https': self.proxy_url,
        }
        session.verify = False
        # 禁用 SSL 警告
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return session

    # ========== 基础检测 ==========

    def check_connectivity(self, url: Optional[str] = None) -> Tuple[bool, float]:
        """
        检查代理连通性。
        
        Returns:
            (是否可用, 延迟秒数)
        """
        target = url or self.check_url
        session = self._get_session()

        try:
            start = time.time()
            resp = session.get(target, timeout=self.timeout)
            elapsed = time.time() - start

            if resp.status_code in (200, 204):
                return True, round(elapsed * 1000, 1)  # 转为毫秒
            else:
                return False, round(elapsed * 1000, 1)
        except requests.exceptions.ConnectTimeout:
            return False, self.timeout * 1000
        except requests.exceptions.ConnectionError:
            return False, -1
        except requests.exceptions.ProxyError:
            return False, -2
        except Exception:
            return False, -3

    # ========== 完整检测 ==========

    def full_check(self) -> dict:
        """
        完整检测：连通性 + 延迟 + 速度测试
        
        Returns:
            {
                'online': bool,
                'delay_ms': float,
                'speed_mb_s': float,
                'error': str
            }
        """
        result = {
            'online': False,
            'delay_ms': -1,
            'speed_mb_s': 0.0,
            'error': '',
        }

        # 第一步：连通性和延迟
        ok, delay = self.check_connectivity()
        result['delay_ms'] = delay

        if not ok:
            if delay == -1:
                result['error'] = '连接被拒绝（代理端口未监听）'
            elif delay == -2:
                result['error'] = '代理协议错误（SOCKS5 协商失败）'
            elif delay == -3:
                result['error'] = '未知网络错误'
            else:
                result['error'] = f'请求超时或返回异常 (延迟: {delay}ms)'
            return result

        result['online'] = True

        # 第二步：速度测试（可选，小文件）
        speed, err = self._speed_test()
        result['speed_mb_s'] = speed
        if err:
            result['error'] = err

        return result

    def _speed_test(self) -> Tuple[float, str]:
        """下载小文件测速，返回 (速度 MB/s, 错误信息)"""
        session = self._get_session()
        try:
            # 使用 Google 的一个大图标代替，约 100KB
            speed_url = 'https://www.google.com/images/phd/px.gif'
            start = time.time()
            resp = session.get(speed_url, timeout=30, stream=True)
            content_length = 0
            for chunk in resp.iter_content(chunk_size=8192):
                content_length += len(chunk)
                if content_length > 1024 * 1024:  # 最多 1MB
                    break
            elapsed = time.time() - start
            if elapsed > 0 and content_length > 0:
                speed = (content_length / 1024 / 1024) / elapsed
                return round(speed, 2), ''
            return 0.0, '无法获取数据'
        except Exception as e:
            return 0.0, str(e)

    # ========== 快速检测 ==========

    @staticmethod
    def quick_check() -> bool:
        """快速检测代理是否在线（静态方法）"""
        checker = ProxyChecker()
        ok, _ = checker.check_connectivity()
        return ok