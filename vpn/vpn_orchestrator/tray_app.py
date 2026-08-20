#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VPN Orchestrator — 系统托盘应用（单 exe 入口）

替代 launch_vpn.bat / stop_vpn.bat：
  - 常驻进程，右下角托盘图标，右键菜单操作
  - 启动即同步现有连接状态（上一会话残留的 xray 也会被接管）
  - 退出 / 关闭 / 信号终止时，统一杀 xray + 清系统代理
  - 不再需要第二个 bat：一个 exe 搞定「开 / 关 / 关掉就像正常软件」

用法:
  python tray_app.py          # 开发 / 调试（带控制台）
  VPNOrchestrator.exe         # 打包后的单文件（双击即运行，无控制台窗口）
"""

import os
import sys
import logging
import threading
import signal

# ---- windowed 模式下 sys.stdout / sys.stderr 为 None，
#      setup_logging 的控制台 handler 会读 sys.stdout.encoding 而崩溃，
#      这里用 devnull 兜底，控制台日志静默丢弃（文件日志照常）。 ----
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ---- 日志：固定写到 %LOCALAPPDATA%/VPNOrchestrator/，跨运行稳定可查 ----
from core.logging_config import setup_logging
_LOG_DIR = os.path.join(
    os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
    'VPNOrchestrator',
)
try:
    os.makedirs(_LOG_DIR, exist_ok=True)
except OSError:
    _LOG_DIR = _HERE
_LOG_FILE = os.path.join(_LOG_DIR, 'vpn_orchestrator.log')
setup_logging(log_file=_LOG_FILE)

logger = logging.getLogger('tray')

# ---- GUI 依赖（延迟到此处才 import，便于无 GUI 环境做 import 检查） ----
from pystray import Icon, Menu, MenuItem
from PIL import Image, ImageDraw


# ================================================================
#  全局状态 + 编排器实例（常驻，持有 xray 子进程）
# ================================================================

_STATE = {
    'status': 'disconnected',   # disconnected | connecting | connected | error
    'node': '',
    'latency': 0,
    'detail': '',
}
_state_lock = threading.Lock()

# 单例编排器：其 RuntimeManager 以子进程方式启动 xray/sing-box，
# 本进程退出时这些子进程仍能被 rt.stop() 按名杀掉 → 一个动作全清理。
from orchestrator import VpnOrchestrator
from config import __version__
from ui.panels import show_properties, show_log
orch = VpnOrchestrator()

_tray_icon = None  # pystray.Icon，启动后赋值


def set_state(**kw):
    with _state_lock:
        _STATE.update(kw)
    _refresh_ui()


def get_state():
    with _state_lock:
        return dict(_STATE)


# ================================================================
#  托盘图标绘制（纯 PIL 生成，无需外部图标文件，便于单文件打包）
# ================================================================

_COLORS = {
    'disconnected': (120, 120, 120, 255),
    'connecting':   (230, 180, 30, 255),
    'connected':    (40, 170, 70, 255),
    'error':        (210, 60, 60, 255),
}


def _make_icon(color_rgba):
    size = 64
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, size - 6, size - 6), fill=color_rgba)
    # 简单的 "V" 标记（VPN 的首字母意象）
    d.line([(20, 22), (32, 44), (44, 22)], fill=(255, 255, 255, 255), width=6)
    return img


def _status_color():
    return _COLORS.get(get_state()['status'], _COLORS['disconnected'])


# ================================================================
#  UI 刷新
# ================================================================

def _refresh_ui():
    if _tray_icon is None:
        return
    try:
        _tray_icon.icon = _make_icon(_status_color())
    except Exception:
        pass
    try:
        _tray_icon.menu = _build_menu()
        _tray_icon.update_menu()
    except Exception:
        pass


def _status_text():
    st = get_state()
    if st['status'] == 'connected':
        node = st['node'] or '未知节点'
        return f"已连接 · {node} · {st['latency']:.0f}ms"
    if st['status'] == 'connecting':
        return "连接中…（TCP 预筛 + 真实校验，约 10-30 秒）"
    if st['status'] == 'error':
        return f"连接失败 · {st['detail'] or ''}"
    if st['node']:
        return f"已断开（上次: {st['node']}）"
    return "未连接"


def _region_menu():
    """动态生成地区子菜单：从节点命名提取地区 → 去重 → 每地区一键选最优。"""
    try:
        regions = orch.get_regions()
    except Exception:
        regions = {}
    items = [MenuItem(f'{r}（{c} 个节点）', _on_connect_region(r))
             for r, c in regions.items()]
    if not items:
        items = [MenuItem("（无可用节点）", None, enabled=False)]
    return Menu(*items)


def _build_menu():
    return Menu(
        MenuItem(_status_text(), None, enabled=False),
        Menu.SEPARATOR,
        MenuItem("连接（扫描 + 选最优节点）", _on_connect),
        MenuItem("设置", Menu(
            MenuItem("地区（按地区选最优）", _region_menu()),
            MenuItem("属性", _on_show_properties),
        )),
        MenuItem("断开并清除代理", _on_disconnect),
        MenuItem("日志", _on_show_log),
        Menu.SEPARATOR,
        MenuItem("退出（自动断开）", _on_exit),
    )


# ================================================================
#  动作（重活在后台线程执行，避免冻结托盘菜单）
# ================================================================

def _do_connect(region=None):
    region_label = region or ''
    set_state(status='connecting', detail='')
    _notify(f'连接中… 正在扫描并选择{region_label}最优节点（约 10-30 秒）')
    try:
        regions = [region] if region else None
        ok = orch.connect_best(open_browser=False, regions=regions)
        if ok:
            node = orch.status.current_node or ''
            try:
                lat = orch.status.last_health.latency_ms
            except Exception:
                lat = 0
            set_state(status='connected', node=node, latency=lat)
            logger.info('连接成功: %s (%.0fms)', node, lat)
            _notify(f'已连接 · {node} · {lat:.0f}ms，正常浏览器即可上网')
        else:
            set_state(status='error',
                      detail='请确认 v2rayN 已关闭，详见日志')
            logger.error('连接失败')
            _notify('连接失败，请确认已关闭 v2rayN，右键「查看日志」')
    except Exception as e:
        set_state(status='error', detail=str(e)[:60])
        logger.exception('connect exception')


def _do_disconnect():
    try:
        orch.stop()
        orch.disable_system_proxy()
        logger.info('已断开并清除系统代理')
        _notify('已断开，系统代理已清除')
    except Exception:
        logger.exception('disconnect exception')
    finally:
        set_state(status='disconnected')


def _on_connect(icon, item):
    threading.Thread(target=_do_connect, daemon=True).start()


def _on_connect_region(region):
    def _action(icon, item):
        threading.Thread(target=_do_connect, args=(region,), daemon=True).start()
    return _action


def _on_disconnect(icon, item):
    threading.Thread(target=_do_disconnect, daemon=True).start()


def _on_exit(icon, item):
    logger.info('退出：先断开…')
    _do_disconnect()
    icon.stop()


def _on_show_properties(icon, item):
    """弹出属性窗口（多字段，含版本/核心/状态/套餐等）。"""
    show_properties(orch, __version__)


def _on_show_log(icon, item):
    """弹出日志窗口（滚动文本，tail 历史日志 + 最近测速摘要）。"""
    show_log(_LOG_FILE)


def _notify(message, title='VPN Orchestrator'):
    """线程安全地弹托盘气泡（失败静默，不阻塞主流程）。"""
    if _tray_icon is None:
        return
    try:
        _tray_icon.notify(message, title)
    except Exception:
        pass


# ================================================================
#  清理钩子（信号 / atexit）—— 保证「关掉就像正常软件」
# ================================================================

def _cleanup():
    try:
        orch.stop()
        orch.disable_system_proxy()
    except Exception:
        pass


import atexit
atexit.register(_cleanup)


def _on_signal(signum, frame):
    logger.info('收到信号 %s，清理退出', signum)
    _cleanup()
    if _tray_icon is not None:
        _tray_icon.stop()


for _sig in (signal.SIGINT, signal.SIGTERM):
    try:
        signal.signal(_sig, _on_signal)
    except Exception:
        pass


# ================================================================
#  主入口
# ================================================================

def main():
    global _tray_icon

    # 启动即同步现有状态：若已有 xray 在跑（上一会话残留），接管为「已连接」
    try:
        if orch.rt.is_running():
            try:
                lat = orch.status.last_health.latency_ms
            except Exception:
                lat = 0
            set_state(status='connected',
                      node=orch.status.current_node or '',
                      latency=lat or 0)
        else:
            set_state(status='disconnected')
    except Exception:
        set_state(status='disconnected')

    _tray_icon = Icon(
        'VPNOrchestrator',
        _make_icon(_status_color()),
        f'VPN Orchestrator v{__version__}',
        _build_menu(),
    )
    logger.info('托盘应用启动，右键图标进行操作')
    _tray_icon.run()


if __name__ == '__main__':
    main()
