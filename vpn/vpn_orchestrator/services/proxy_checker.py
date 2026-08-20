"""
代理连通性检测器。
通过 SOCKS5 代理发送 HTTP 请求来检测代理是否可用。
"""

import time
import requests
from typing import Tuple, Optional

from config import get_socks_proxy, CHECK_URL, TIMEOUT


class ProxyChecker:
    """检测代理连通性和性能"""

    def __init__(self, proxy_url: str = None,
                 check_url: str = CHECK_URL,
                 timeout: int = TIMEOUT):
        self.proxy_url = proxy_url or get_socks_proxy()
        self.check_url = check_url
        self.timeout = timeout
        self._last_error = ''

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

    def check_connectivity(self, url: Optional[str] = None,
                           warmup: bool = True) -> Tuple[bool, float]:
        """
        检查代理连通性。

        With warmup=True (default), a throwaway request is sent first so the
        DNS-through-proxy + tunnel-establish cost is excluded — the measured
        latency then reflects the node's TRUE RTT (comparable to v2rayN's
        test), instead of being inflated ~3x by the one-off DNS lookup that
        would otherwise dominate and bias node ranking.

        Returns:
            (是否可用, 延迟毫秒)
        """
        target = url or self.check_url
        session = self._get_session()
        if warmup:
            # Prime DNS + tunnel with the SAME session, then measure with it.
            # A fresh requests.Session opens a new connection to the SOCKS
            # proxy and re-establishes the upstream tunnel (~200ms), so using
            # a *different* session for the warm-up would discard the warm
            # tunnel and the timed request would pay the cold cost again.
            # Reusing one session lets the timed request ride the warm tunnel
            # and report the node's true RTT. Dead nodes just waste a few
            # seconds here and are caught by the timed request.
            try:
                session.get(target, timeout=5)
            except Exception:
                pass

        try:
            start = time.time()
            resp = session.get(target, timeout=self.timeout)
            elapsed = time.time() - start

            if resp.status_code in (200, 204):
                return True, round(elapsed * 1000, 1)  # 转为毫秒
            else:
                return False, round(elapsed * 1000, 1)
        except requests.exceptions.ConnectTimeout:
            self._last_error = 'ConnectTimeout'
            return False, self.timeout * 1000
        except requests.exceptions.ReadTimeout:
            # Tunnel established but no response — node alive-but-dead / blocked.
            self._last_error = 'ReadTimeout'
            return False, -5
        except requests.exceptions.ConnectionError:
            self._last_error = 'ConnectionError'
            return False, -1
        except requests.exceptions.ProxyError:
            # SOCKS proxy returned a failure (e.g. outbound unreachable).
            self._last_error = 'ProxyError'
            return False, -2
        except Exception as e:
            self._last_error = f'{type(e).__name__}: {e}'
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
                result['error'] = '代理协议错误（SOCKS5 协商失败/节点出站不可达）'
            elif delay == -3:
                result['error'] = f'未知网络错误（{self._last_error or "未捕获异常"}）'
            elif delay == -5:
                result['error'] = '节点已连通但读取超时（节点无响应/被封锁）'
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

    def is_reachable(self, url: str) -> bool:
        """Return True if the target server responded (HTTP status < 500).

        A connection failure / timeout / proxy error means the node cannot
        reach the target (e.g. OpenAI is region-blocked on that node), so we
        return False. A 401/403/429 from the server still counts as reachable
        — that's bot-protection, not a proxy-level block.
        """
        session = self._get_session()
        try:
            resp = session.get(url, timeout=self.timeout)
            return resp.status_code < 500
        except (requests.exceptions.ConnectTimeout,
                requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.ProxyError):
            return False
        except Exception:
            return False

    # ========== 快速检测 ==========

    @staticmethod
    def quick_check() -> bool:
        """快速检测代理是否在线（静态方法）"""
        checker = ProxyChecker()
        ok, _ = checker.check_connectivity()
        return ok