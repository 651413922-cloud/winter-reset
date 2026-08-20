"""托盘弹窗：属性（多字段）与日志（滚动文本）。

两个弹窗都独立于 pystray 主线程，用 daemon 线程跑 tkinter 的
Tk().mainloop()，避免阻塞托盘图标的消息循环。
"""

import logging
import re
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext

logger = logging.getLogger(__name__)


# ================================================================
#  属性面板（多字段只读 + 复制）
# ================================================================

# 订阅里混入的套餐元数据节点命名规律（remarks 形如「套餐到期：2026-12-15」）
_PLAN_PATTERNS = {
    '套餐到期': re.compile(r'套餐到期[:：]\s*(\d{4}-\d{2}-\d{2})'),
    '剩余流量': re.compile(r'剩余流量[:：]\s*([\d.]+\s*GB)'),
    '距离下次重置': re.compile(r'距离下次重置剩余[:：]\s*(\d+\s*天)'),
}

# 属性展示顺序（仅显示实际取到的键）
_PROP_ORDER = [
    '版本', '核心引擎', '当前状态', '本地代理', '系统代理',
    '节点总数', '套餐到期', '剩余流量', '距离下次重置',
]


def _gather_properties(orch, version):
    """从编排器实时汇聚属性面板所需的日常字段。"""
    from config import (
        get_active_core_type, CORE_TYPE_SING_BOX,
        get_socks_port_from_config, SOCKS5_HOST,
    )
    props = {'版本': version}

    # 核心引擎
    try:
        ct = get_active_core_type()
        props['核心引擎'] = 'sing-box' if ct == CORE_TYPE_SING_BOX else 'xray'
    except Exception:
        props['核心引擎'] = '未知'

    # 当前状态（已连接·节点·延迟 / 已连接 / 未连接）
    try:
        running = orch.rt.is_running()
        node = orch.status.current_node or ''
        try:
            lat = orch.status.last_health.latency_ms
        except Exception:
            lat = 0
        if running and node:
            props['当前状态'] = f"已连接 · {node} · {lat:.0f}ms"
        elif running:
            props['当前状态'] = '已连接'
        else:
            props['当前状态'] = '未连接'
    except Exception:
        props['当前状态'] = '未知'

    # 本地代理地址
    try:
        port = get_socks_port_from_config()
        props['本地代理'] = f'{SOCKS5_HOST}:{port}'
    except Exception:
        props['本地代理'] = '未知'

    # 系统代理开关
    try:
        props['系统代理'] = '已开启' if orch.is_system_proxy_enabled() else '已关闭'
    except Exception:
        props['系统代理'] = '未知'

    # 节点总数 + 套餐元数据（从订阅节点 remarks 里解析）
    try:
        orch.db.connect()
        profiles = orch.db.get_all_profiles()
        props['节点总数'] = str(len(profiles))
        blob = ' '.join((p.remarks or '') for p in profiles)
        for label, pat in _PLAN_PATTERNS.items():
            m = pat.search(blob)
            props[label] = m.group(1) if m else '—'
    except Exception:
        props.setdefault('节点总数', '—')
        for label in _PLAN_PATTERNS:
            props.setdefault(label, '—')
    finally:
        try:
            orch.db.close()
        except Exception:
            pass

    return props


def _run_properties(orch, version):
    props = _gather_properties(orch, version)

    root = tk.Tk()
    root.title(f'VPN Orchestrator — 属性 v{version}')
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=14)
    frame.grid(row=0, column=0, sticky='nsew')

    r = 0
    for key in _PROP_ORDER:
        if key not in props:
            continue
        ttk.Label(frame, text=key, width=12, anchor='e',
                  font=('Microsoft YaHei', 10, 'bold')
                  ).grid(row=r, column=0, padx=(0, 10), pady=3, sticky='e')
        ttk.Label(frame, text=str(props[key]), anchor='w',
                  font=('Microsoft YaHei', 10)
                  ).grid(row=r, column=1, pady=3, sticky='w')
        r += 1

    def _copy():
        lines = [f"{k}：{props[k]}" for k in _PROP_ORDER if k in props]
        root.clipboard_clear()
        root.clipboard_append('\n'.join(lines))
        _copy_btn.config(text='已复制')
        root.after(1200, lambda: _copy_btn.config(text='复制'))

    _copy_btn = ttk.Button(frame, text='复制', command=_copy)
    _copy_btn.grid(row=r, column=0, columnspan=2, pady=(10, 0))

    root.mainloop()


def show_properties(orch, version):
    """在独立线程弹出属性窗口（不阻塞托盘主线程）。"""
    threading.Thread(target=_run_properties, args=(orch, version),
                     daemon=True).start()


# ================================================================
#  日志面板（滚动文本 + tail 历史 + 最近测速摘要 + 筛选）
# ================================================================

# 关键事件：连接/切换/扫描/冲突/代理等
_KEY_EVENT_RE = re.compile(
    r'连接成功|已连接|切换到|尝试 \d|并发测速|所有节点|CONFLICT|代理|断开|退出|最优节点|Xray'
)
# 失败 & 警告：日志级别标记
_FAIL_RE = re.compile(r'\b(WARNING|ERROR)\b')

# 从历史日志里解析「最近测速摘要」
_SPEEDTEST_BEST_RE = re.compile(
    r'\[2/4\] 最优节点: (.+?) \((\d+)ms, ([\d.]+)MB/s, (ChatGPT[✅❌])\)'
)
_SPEEDTEST_COUNT_RE = re.compile(r'\[阶段1\] TCP Ping 预筛 (\d+) 个节点')


def _parse_recent_speedtest(text):
    """返回 (最优节点摘要, 扫描节点数) 或 (None, None)。"""
    best = None
    for m in _SPEEDTEST_BEST_RE.finditer(text):
        best = f"{m.group(1)} | {m.group(2)}ms | {m.group(4)}"
    n = None
    for m in _SPEEDTEST_COUNT_RE.finditer(text):
        n = m.group(1)
    return best, n


def _load_log_lines(path, max_lines=200):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except Exception:
        return []
    if max_lines and len(lines) > max_lines:
        lines = lines[-max_lines:]
    return lines


def _run_log(log_file):
    lines = _load_log_lines(log_file)
    best, n = _parse_recent_speedtest(''.join(lines))

    root = tk.Tk()
    root.title('VPN Orchestrator — 日志')
    root.geometry('820x560')

    # 顶部：最近测速摘要
    sum_frame = ttk.LabelFrame(root, text='最近测速摘要', padding=8)
    sum_frame.grid(row=0, column=0, padx=10, pady=(10, 4), sticky='ew')
    if best:
        ttk.Label(sum_frame, text=f"最优节点：{best}").grid(
            row=0, column=0, sticky='w')
        ttk.Label(sum_frame, text=f"扫描节点数：{n or '—'}").grid(
            row=1, column=0, sticky='w')
    else:
        ttk.Label(sum_frame, text='（历史日志中暂无测速记录）').grid(
            row=0, column=0, sticky='w')

    # 筛选
    mode = tk.StringVar(value='all')
    frm = ttk.Frame(root)
    frm.grid(row=1, column=0, padx=10, pady=(0, 4), sticky='w')
    ttk.Label(frm, text='筛选：').pack(side='left')
    for val, lab in (('all', '全部'),
                     ('fail', '仅失败&警告'),
                     ('key', '仅关键事件')):
        ttk.Radiobutton(frm, text=lab, variable=mode, value=val,
                        command=lambda: _apply_filter()
                        ).pack(side='left', padx=4)

    txt = scrolledtext.ScrolledText(root, wrap='word', font=('Consolas', 9))
    txt.grid(row=2, column=0, padx=10, pady=(0, 10), sticky='nsew')
    root.rowconfigure(2, weight=1)
    root.columnconfigure(0, weight=1)

    def _filtered():
        m = mode.get()
        out = []
        for ln in lines:
            if m == 'all':
                out.append(ln)
            elif m == 'fail':
                if _FAIL_RE.search(ln):
                    out.append(ln)
            elif m == 'key':
                if _KEY_EVENT_RE.search(ln):
                    out.append(ln)
        return out

    def _apply_filter():
        txt.config(state='normal')
        txt.delete('1.0', 'end')
        txt.insert('1.0', ''.join(_filtered()))
        txt.config(state='disabled')
        txt.see('end')

    _apply_filter()
    root.mainloop()


def show_log(log_file):
    """在独立线程弹出日志窗口（不阻塞托盘主线程）。"""
    threading.Thread(target=_run_log, args=(log_file,), daemon=True).start()
