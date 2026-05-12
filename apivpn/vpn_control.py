"""
VPN 控制与验证模块

包含：
- 基于 HTTP / psutil 的在线状态检测
- 基于 pywinauto 的控件点击（不使用像素坐标）
- 基于 scapy / pyshark 的流量闭环验证（检测 203.119.174.215 且负载长度 242，Magic 5f 00 1f ce）

注意：运行前请确保已安装 `pywinauto`, `requests`, `psutil`，以及 `scapy` 或 `pyshark`。
"""
from typing import Optional
import time
import logging
import json
import re
from datetime import datetime

log = logging.getLogger(__name__)

# 可选依赖
try:
    import requests
except Exception:
    requests = None

try:
    import psutil
except Exception:
    psutil = None

# 引入配置（相对导入尽量安全）
try:
    from . import config as cfg
except Exception:
    import config as cfg


# ------------------ 状态检测 ------------------
def is_vpn_online_via_http(timeout: float = 2.0) -> bool:
    """通过请求 72.247.155.83/connecttest.txt 判断链路存活（返回 200 即在线）。"""
    if requests is None:
        raise ImportError("requests is required for HTTP-based VPN check")
    url = "http://72.247.155.83/connecttest.txt"
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code == 200
    except Exception as e:
        log.debug("HTTP VPN check failed: %s", e)
        return False


def is_vpn_online_via_psutil() -> bool:
    """通过 psutil.net_connections 判断是否存在到 72.247.155.83 的已建立连接。"""
    if psutil is None:
        raise ImportError("psutil is required for psutil-based VPN check")
    target = "72.247.155.83"
    try:
        conns = psutil.net_connections(kind='inet')
        for c in conns:
            raddr = c.raddr
            if not raddr:
                continue
            if raddr and raddr[0] == target and c.status in ("ESTABLISHED", "SYN_SENT", "SYN_RECV"):
                return True
    except Exception as e:
        log.debug("psutil VPN check failed: %s", e)
    return False


def is_vpn_online() -> bool:
    """优先使用 HTTP 方法检测；失败则退回到 psutil 检查。"""
    try:
        if requests is not None:
            ok = is_vpn_online_via_http()
            if ok:
                return True
    except Exception:
        pass
    try:
        if psutil is not None:
            return is_vpn_online_via_psutil()
    except Exception:
        pass
    return False


# ------------------ UI 操作 ------------------
def click_replace_line(window_title: str = "小熊加速器") -> bool:
    """使用 pywinauto 点击“更换线路”按钮（尝试 UIA 与 win32 backend）。"""
    try:
        from pywinauto import Application
        from pywinauto.findwindows import ElementNotFoundError
    except Exception as e:
        log.error("pywinauto 未安装：%s", e)
        return False

    try:
        from pywinauto import findwindows
        app = Application(backend='uia')
        try:
            app.connect(title_re=f".*{window_title}.*")
            win = app.window(title_re=f".*{window_title}.*")
        except Exception:
            try:
                app = Application(backend='win32')
                app.connect(title_re=f".*{window_title}.*")
                win = app.window(title_re=f".*{window_title}.*")
            except Exception:
                # 通过枚举窗口按 title 关键词连接
                elems = findwindows.find_elements(visible_only=False)
                candidates = []
                for e in elems:
                    title = getattr(e, 'name', '') or ''
                    pid = getattr(e, 'process_id', None)
                    if title and window_title in title:
                        candidates.append((title, pid))
                if candidates:
                    _, pid = candidates[0]
                    app = Application(backend='uia')
                    app.connect(process=pid)
                    win = app.window(process=pid)
                else:
                    wnd_list = []
                    for e in elems[:60]:
                        wnd_list.append({
                            'title': getattr(e, 'name', ''),
                            'pid': getattr(e, 'process_id', None),
                            'class_name': getattr(e, 'class_name', None)
                        })
                    log.debug("未找到匹配窗口，列出前60个窗口: %s", wnd_list)
                    raise ElementNotFoundError({'title_re': f".*{window_title}.*"})

        # 常见控件名尝试列表
        candidates = ["更换线路", "切换线路", "换线", "更换节点"]
        for name in candidates:
            try:
                btn = win.child_window(title=name, control_type="Button")
                if btn.exists():
                    try:
                        btn.invoke()
                    except Exception:
                        btn.click_input()
                    return True
            except ElementNotFoundError:
                continue
            except Exception:
                continue

        # 扫描所有按钮匹配包含关键词的
        try:
            for b in win.descendants(control_type="Button"):
                try:
                    txt = getattr(b, 'element_info').name or ''
                    if any(k in txt for k in ("换", "更换", "线路", "切换")):
                        try:
                            b.invoke()
                        except Exception:
                            b.click_input()
                        return True
                except Exception:
                    continue
        except Exception:
            pass

    except Exception as e:
        log.exception("点击更换线路失败：%s", e)
    return False


def select_free_line(window_title: str = "小熊加速器") -> bool:
    """在共享线路列表中查找“免费试用”且负载 != 100% 的第一个条目并点击。

    优先匹配包含连续四字“美国节点”的条目，按负载升序尝试。
    若所有匹配项均为 100%，会调用 `report_quota_full` 上报并返回 False。
    """
    try:
        from pywinauto import Application
        from pywinauto.findwindows import ElementNotFoundError
    except Exception:
        log.error("pywinauto 未安装，无法选择线路")
        return False

    title_re = f".*{window_title}.*"
    try:
        app = Application(backend='uia')
        try:
            app.connect(title_re=title_re)
            win = app.window(title_re=title_re)
        except Exception:
            try:
                app = Application(backend='win32')
                app.connect(title_re=title_re)
                win = app.window(title_re=title_re)
            except Exception as e:
                log.exception("连接窗口失败: %s", e)
                return False

        # 收集候选控件：ListItem/DataItem/Group/Pane 中包含“免费”字样的控件
        items = []
        for ctrl in win.descendants():
            try:
                ctype = getattr(ctrl, 'control_type', None)
                name = getattr(ctrl, 'element_info').name or ''
                if ctype in ("ListItem", "DataItem", "Group") or re.search(r'免费|免费试用', name):
                    items.append(ctrl)
            except Exception:
                continue

        if not items:
            for ctrl in win.descendants(control_type="Pane"):
                try:
                    name = getattr(ctrl, 'element_info').name or ''
                    if re.search(r'免费|免费试用', name):
                        items.append(ctrl)
                except Exception:
                    continue

        candidates = []
        pct_re = re.compile(r"(\d{1,3})%")
        for it in items:
            try:
                name = getattr(it, 'element_info').name or ''
                if not re.search(r'免费|免费试用', name):
                    texts = []
                    for sub in it.descendants():
                        try:
                            txt = getattr(sub, 'element_info').name or ''
                            if txt:
                                texts.append(txt)
                        except Exception:
                            continue
                    combined = ' '.join(texts)
                else:
                    combined = name

                if re.search(r'免费试用|免费', combined):
                    pct = None
                    for sub in it.descendants():
                        try:
                            txt = getattr(sub, 'element_info').name or ''
                            m = pct_re.search(txt)
                            if m:
                                pct = int(m.group(1))
                                break
                        except Exception:
                            continue
                    candidates.append((it, combined, pct))
            except Exception:
                continue

        if not candidates:
            log.debug("未在窗口中找到任何包含'免费'字样的线路项")
            return False

        # 优先匹配包含 '美国节点' 的，并按 pct 升序
        def _priority_key(entry):
            it, text, pct = entry
            primary = 0 if '美国节点' in (text or '') else 1
            pct_val = pct if (pct is not None) else 1000
            return (primary, pct_val)

        candidates = sorted(candidates, key=_priority_key)

        for it, text, pct in candidates:
            try:
                if pct is None or pct < 100:
                    try:
                        it.invoke()
                    except Exception:
                        try:
                            it.click_input()
                        except Exception:
                            for sub in it.descendants(control_type='Button'):
                                try:
                                    sub.click_input()
                                    break
                                except Exception:
                                    continue
                    log.info("已点击线路项: %s (pct=%s)", text, pct)
                    return True
            except Exception:
                continue

        report_quota_full(window_title, detail="all_free_lines_100pct")
        return False

    except ElementNotFoundError as e:
        log.debug("选择免费线路时未找到窗口元素: %s", e)
    except Exception as e:
        log.exception("选择免费线路发生异常: %s", e)
    return False


# ------------------ 满额上报 ------------------
def detect_quota_full(window_title: str = "小熊加速器") -> bool:
    """检测窗口中是否存在“满额/已满”等提示，返回 True 表示满额。"""
    keywords = ("满额", "已满", "已达上限", "已满额", "人数已满", "已满报错")
    try:
        from pywinauto import Application, findwindows
    except Exception:
        log.debug("pywinauto 未安装，无法检测满额")
        return False

    try:
        app = Application(backend='uia')
        try:
            app.connect(title_re=f".*{window_title}.*")
            win = app.window(title_re=f".*{window_title}.*")
        except Exception:
            try:
                app = Application(backend='win32')
                app.connect(title_re=f".*{window_title}.*")
                win = app.window(title_re=f".*{window_title}.*")
            except Exception:
                elems = findwindows.find_elements(visible_only=False)
                for e in elems:
                    title = getattr(e, 'name', '') or ''
                    if window_title in title:
                        app = Application(backend='uia')
                        app.connect(process=e.process_id)
                        win = app.window(process=e.process_id)
                        break

        for ctrl in win.descendants():
            try:
                name = getattr(ctrl, 'element_info').name or ''
                if any(k in name for k in keywords):
                    log.debug("检测到满额提示控件: %s", name)
                    return True
            except Exception:
                continue
    except Exception as e:
        log.debug("检测满额失败: %s", e)
    return False


def report_quota_full(window_title: str, detail: str = "quota_full_detected") -> None:
    """写入本地事件并尝试触发 Windows toast 与 webhook 上报。"""
    record = {
        "event": "quota_full",
        "ts": datetime.utcnow().isoformat() + "Z",
        "window": window_title,
        "detail": detail,
    }
    try:
        out = getattr(cfg, 'OUTPUT_FILE', 'vpn_events.jsonl')
        with open(out, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        log.info("已写入满额事件到 %s", out)
    except Exception as e:
        log.exception("写入满额事件失败: %s", e)

    # toast
    try:
        from win10toast import ToastNotifier
        tn = ToastNotifier()
        tn.show_toast("小熊加速器提示", f"线路已满额：{detail}", duration=5, threaded=True)
        log.debug("已触发 Windows toast 通知")
    except Exception:
        log.debug("Toast 通知不可用或失败")

    # webhook
    try:
        if getattr(cfg, 'WEBHOOK_ENABLED', False) and getattr(cfg, 'WEBHOOK_URL', ''):
            try:
                _req = requests if requests is not None else __import__('requests')
                _req.post(cfg.WEBHOOK_URL, json=record, timeout=getattr(cfg, 'WEBHOOK_TIMEOUT', 5))
                log.debug("已向 webhook 发送事件到 %s", cfg.WEBHOOK_URL)
            except Exception as e:
                log.exception("发送 webhook 失败: %s", e)
    except Exception:
        pass


# ------------------ 流量监听 ------------------
def listen_for_switch_packet(timeout: float = 3.0, iface: Optional[str] = None) -> bool:
    """在短时窗口内监听是否出现到目标 IP 的 POST 包（目标 IP 203.119.174.215，负载长度 242，Magic 开头）。"""
    target_ip = "203.119.174.215"
    magic = b"\x5f\x00\x1f\xce"
    expected_len = 242

    # 优先 scapy
    try:
        from scapy.all import sniff, Raw, IP, TCP

        found = {"ok": False}

        def _check(pkt):
            try:
                if IP in pkt:
                    ip = pkt[IP]
                    if not (ip.dst == target_ip or ip.src == target_ip):
                        return
                if Raw in pkt and TCP in pkt:
                    payload = bytes(pkt[Raw].load)
                    if len(payload) == expected_len and payload.startswith(magic):
                        found["ok"] = True
            except Exception:
                pass

        sniff(filter=f"tcp and host {target_ip}", timeout=timeout, iface=iface, prn=_check, store=0)
        return bool(found["ok"])
    except Exception as e:
        log.debug("scapy 不可用或监听失败，尝试 pyshark: %s", e)

    # 回退 pyshark
    try:
        import pyshark
        capture = pyshark.LiveCapture(interface=iface, bpf_filter=f"host {target_ip} and tcp")
        start = time.time()
        for pkt in capture.sniff_continuously(packet_count=0):
            try:
                if time.time() - start > timeout:
                    break
                raw = None
                if hasattr(pkt, 'tcp') and hasattr(pkt.tcp, 'payload'):
                    payload_hex = getattr(pkt.tcp, 'payload', '')
                    if payload_hex:
                        raw = bytes.fromhex(payload_hex.replace(':', ''))
                if not raw and hasattr(pkt, 'data') and hasattr(pkt.data, 'data'):
                    data_hex = getattr(pkt.data, 'data', '')
                    if data_hex:
                        raw = bytes.fromhex(data_hex.replace(':', ''))
                if raw and len(raw) == expected_len and raw.startswith(magic):
                    capture.close()
                    return True
            except Exception:
                continue
        try:
            capture.close()
        except Exception:
            pass
    except Exception as e:
        log.debug("pyshark 不可用或监听失败：%s", e)

    return False


def attempt_switch_and_verify(window_title: str = "小熊加速器", verify_timeout: float = 3.0) -> bool:
    """执行点击换线动作并在短时间内验证流量指纹，返回是否成功。"""
    clicked = click_replace_line(window_title=window_title)
    if not clicked:
        log.info("未能触发更换线路控件")
        return False
    time.sleep(0.15)
    ok = listen_for_switch_packet(timeout=verify_timeout)
    return ok


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("HTTP online:", is_vpn_online_via_http() if requests is not None else "requests missing")
    if psutil is not None:
        print("psutil online:", is_vpn_online_via_psutil())
    else:
        print("psutil missing")
