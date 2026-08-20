r"""
Windows 系统代理控制。

v2rayN 连接后会把「系统代理」设成本机 SOCKS/HTTP，使**所有**浏览器与
应用程序自动走代理（全局模式）。本模块用同一方式：写注册表
`HKCU\...\Internet Settings` 并广播 `InternetSetOption` 让改动立即生效，
从而让编排器的行为与 v2rayN 一致——不再是"只给某个浏览器窗口配代理"。
"""

import logging
import ctypes

try:
    import winreg
    _HAS_WINREG = True
except ImportError:  # 非 Windows（如沙箱）
    _HAS_WINREG = False

logger = logging.getLogger(__name__)

_INTERNET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
_INTERNET_OPTION_SETTINGS_CHANGED = 39
_INTERNET_OPTION_REFRESH = 37


def _refresh() -> None:
    """广播代理变更，使已运行的浏览器/应用立即生效（无需重启/注销）。"""
    try:
        wininet = ctypes.windll.wininet  # type: ignore[attr-defined]
        wininet.InternetSetOptionW(0, _INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
        wininet.InternetSetOptionW(0, _INTERNET_OPTION_REFRESH, 0, 0)
    except Exception as e:  # 不影响代理本身生效
        logger.debug("InternetSetOption refresh skipped: %s", e)


def set_global_proxy(host: str, port: int) -> bool:
    """
    把 Windows 系统代理设为 `host:port`（HTTP+SOCKS 同时声明）。

    xray 的 inbound 是 `mixed`（同端口既服务 SOCKS5 也服务 HTTP），
    因此这里同时声明 http/https/socks，兼容性最好。
    """
    if not _HAS_WINREG:
        logger.warning("非 Windows 环境，无法设置系统代理（仅本机开发/沙箱）。")
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _INTERNET_SETTINGS, 0, winreg.KEY_SET_VALUE
        )
        # 同时声明三种协议，mixed 入站都能接
        proxy_server = (
            f"http={host}:{port};https={host}:{port};socks={host}:{port}"
        )
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, proxy_server)
        # 仅对 <local> 直连，其余全部走代理
        winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, "<local>")
        key.Close()
        _refresh()
        logger.info("系统代理已设为全局 %s (http/https/socks)", proxy_server)
        return True
    except Exception as e:
        logger.error("设置系统代理失败: %s", e)
        return False


def clear_global_proxy() -> bool:
    """关闭 Windows 系统代理（恢复直连）。"""
    if not _HAS_WINREG:
        logger.warning("非 Windows 环境，无需清除系统代理。")
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _INTERNET_SETTINGS, 0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        key.Close()
        _refresh()
        logger.info("系统代理已清除（恢复直连）")
        return True
    except Exception as e:
        logger.error("清除系统代理失败: %s", e)
        return False


def is_global_proxy_set(host: str = "", port: int = 0) -> bool:
    """查询系统代理是否启用（可选校验 host:port）。"""
    if not _HAS_WINREG:
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _INTERNET_SETTINGS, 0, winreg.KEY_READ
        )
        enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
        if enabled != 1:
            return False
        if host and port:
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
            return f"{host}:{port}" in server
        return True
    except Exception:
        return False
