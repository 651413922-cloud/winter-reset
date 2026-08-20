"""
节点切换器。
自动/手动切换 sing-box 的活动节点。
"""

import logging
import os
import re
import json
import time
import subprocess
import tempfile
import concurrent.futures as cf
from typing import List, Optional, Tuple

from config import CONFIG_JSON, XRAY_EXE, BASE_DIR
from models.profile import ProfileItem
from core.db_manager import DbManager
from core.config_builder import apply_profile_to_config
from core.runtime_manager import RuntimeManager
from services.proxy_checker import ProxyChecker

logger = logging.getLogger(__name__)

# 节点命名规律（用于从 Remarks 提取地区）：
#   SS 节点   "[1x] [直连] [SS] 香港 02"  -> 地区 = 最后一个 ] 之后的中文
#   专线节点   "香港 01 | 专线"             -> 地区 = 行首中文
_REGION_BRACKET = re.compile(r'\]\s*([一-鿿]{2,6})')
_REGION_DEDICATED = re.compile(r'^([一-鿿]{2,6})\s+\d+\s*\|')


class NodeSwitcher:
    """节点切换与自动选优"""

    def __init__(self):
        self.db = DbManager()
        self.proc = RuntimeManager()
        self.checker = ProxyChecker()

    # ========== 地区发现 ==========

    @staticmethod
    def extract_region(remarks: str) -> Optional[str]:
        """从节点命名提取地区：'[SS] 香港 02'→'香港'，'香港 01 | 专线'→'香港'。"""
        if not remarks:
            return None
        s = remarks.strip()
        m = _REGION_DEDICATED.match(s)
        if m:
            return m.group(1)
        m = _REGION_BRACKET.search(s)
        if m:
            return m.group(1)
        return None

    def get_regions(self) -> dict:
        """去重统计所有地区，返回 {地区: 节点数}（按名称排序）。"""
        self.db.connect()
        try:
            regions = {}
            for p in self.db.get_all_profiles():
                r = self.extract_region(p.remarks)
                if r:
                    regions[r] = regions.get(r, 0) + 1
            return dict(sorted(regions.items()))
        finally:
            self.db.close()

    def get_current_region(self) -> Optional[str]:
        """读取 config.json 当前 proxy outbound，反查 DB 提取节点地区。

        供自动切换（tick 恢复、质量切换）做「同地区交换」：切换前后保持
        出口 IP 地区一致，避免目标站点（OpenAI、银行等）因 IP 地区跳变
        触发风控。解析失败返回 None（调用方退化为不限地区）。
        """
        try:
            from adapters.xray_config import (
                read_config, find_proxy_outbound, extract_node_identifier)
            cfg = read_config()
            ob, _ = find_proxy_outbound(cfg)
            if not ob:
                return None
            ident = extract_node_identifier(ob)  # "host:port"
            host, _, port = ident.rpartition(':')
            if not host or not port.isdigit():
                return None
            host = host.strip().lower()
            port = int(port)
            self.db.connect()
            try:
                for p in self.db.get_all_profiles():
                    if (p.address or '').strip().lower() == host \
                            and int(p.port or 0) == port:
                        return self.extract_region(p.remarks)
            finally:
                self.db.close()
        except Exception:
            logger.warning('解析当前节点地区失败，自动切换不启用同地区限制',
                           exc_info=True)
        return None

    # ========== 按名称切换 ==========

    def switch_to(self, name_or_index) -> bool:
        self.db.connect()
        try:
            profiles = self.db.get_all_profiles()
            if not profiles:
                logger.error("数据库中没有节点")
                return False

            if isinstance(name_or_index, int) or name_or_index.isdigit():
                idx = int(name_or_index) - 1
                if 0 <= idx < len(profiles):
                    profile = profiles[idx]
                else:
                    logger.error("索引 %s 超出范围 (1-%d)", name_or_index, len(profiles))
                    return False
            else:
                profile = self.db.get_profile_by_name(str(name_or_index))
                if not profile:
                    logger.error("未找到匹配的节点: %s", name_or_index)
                    self.db.print_all_profiles()
                    return False

            return self._apply_and_restart(profile)
        finally:
            self.db.close()

    # ========== 选择最优节点 ==========

    def switch_to_best(self) -> bool:
        self.db.connect()
        try:
            profiles = self.db.get_all_profiles()
            scored: List[Tuple[ProfileItem, float, float]] = []

            for p in profiles:
                stats = self.db.get_profile_stats(p.index_id)
                delay = stats['delay']
                speed = stats['speed']
                scored.append((p, delay if delay > 0 else 99999, speed))

            scored.sort(key=lambda x: (x[1], -x[2]))

            if not scored:
                logger.error("无可用节点")
                return False

            best = scored[0]
            logger.info("最优节点: %s | 延迟: %.0fms | 速度: %.1fMB/s",
                        best[0].remarks, best[1], best[2])

            return self._apply_and_restart(best[0])
        finally:
            self.db.close()

    # ========== 遍历切换（直到可用） ==========

    def switch_until_working(self, max_attempts: int = 0, prefer_tcp: bool = True,
                             current_region: Optional[str] = None,
                             allow_cross_region: bool = False) -> bool:
        """Try nodes until one works.

        max_attempts=0 表示按默认上限尝试（不再无脑遍历全部 63 个）。
        默认按 TCP 延迟排序（而非 DB 缓存的 speed，后者恒为 0 无意义），
        并跳过 TCP 不可达的节点，避免把时间浪费在已确认死的节点上。

        current_region: 当前节点地区（自动切换场景传入）。给定后强制
            「同地区交换」——只从同一地区的节点里选，出口 IP 地区保持
            不变，避免目标站点（OpenAI、银行等）因 IP 地区跳变触发风控。
            allow_cross_region=False（默认）时同地区无可用节点就直接放弃
            本次切换；True 时才退而求其次跨地区兜底。
        """
        self.db.connect()
        try:
            profiles = self.db.get_all_profiles()
            profiles = [p for p in profiles if not self._is_broken(p)]
            # 按 (address, port) 去重（与 speedtest_all 一致），避免同一
            # 端点被重复订阅导入后重试两遍——实测兜底对同一 grpc 端点
            # 重复尝试白白花掉 ~15s。
            _seen = set()
            _uniq = []
            for p in profiles:
                key = (p.address or '').strip().lower(), int(p.port or 0)
                if key not in _seen:
                    _seen.add(key)
                    _uniq.append(p)
            profiles = _uniq

            if prefer_tcp:
                # 全量 TCP Ping，按延迟升序；超时或不可达的丢弃。
                # 并发执行（与阶段1相同的策略）：串行逐个 ping 时死节点
                # 每个吃满 2s 超时，61 个节点可能拖慢兜底数十秒——上次实测
                # 兜底仅 TCP Ping 就耗时 60s，是整个连接流程的最大瓶颈。
                with cf.ThreadPoolExecutor(
                        max_workers=min(32, len(profiles) or 1)) as _ex:
                    _tp = list(_ex.map(
                        lambda p: (p, self._tcp_ping(p.address, p.port, 2.0)),
                        profiles))
                tp = [(p, ms) for p, ms in _tp if ms is not None]
                if current_region:
                    # 同地区交换（防风控）：同地区节点优先，同一地区内按
                    # 延迟升序；默认严格同地区，跨地区节点直接排除。
                    same = [(p, ms) for p, ms in tp
                            if self.extract_region(p.remarks) == current_region]
                    other = [(p, ms) for p, ms in tp
                             if self.extract_region(p.remarks) != current_region]
                    same.sort(key=lambda x: x[1])
                    other.sort(key=lambda x: x[1])
                    if allow_cross_region:
                        ordered = [p for p, _ in same] + [p for p, _ in other]
                        logger.info(
                            '[兜底] 同地区(%s)优先：%d 个同地区 + %d 个跨地区兜底',
                            current_region, len(same), len(other))
                    else:
                        ordered = [p for p, _ in same]
                        logger.info(
                            '[兜底] 严格同地区(%s)：%d 个同地区节点，'
                            '排除 %d 个跨地区节点（防触发风控）',
                            current_region, len(same), len(other))
                    if not ordered:
                        logger.error(
                            '[兜底] 同地区(%s)没有 TCP 可达节点，放弃切换'
                            '（保持当前地区，避免出口 IP 跳变触发风控）',
                            current_region)
                        return False
                else:
                    tp.sort(key=lambda x: x[1])
                    ordered = [p for p, _ in tp]
                    logger.info('[兜底] TCP 可达节点 %d 个，按延迟升序尝试',
                                len(ordered))
            else:
                ordered = profiles

            # 默认上限：最多尝试 12 个，避免最坏情况遍历全部节点耗时几十分钟
            limit = max_attempts if max_attempts > 0 else min(12, len(ordered))
            for i, profile in enumerate(ordered[:limit]):
                logger.info("--- 尝试 %d/%d: %s ---",
                            i + 1, limit, profile.remarks)
                ok = self._apply_and_restart(profile)
                if not ok:
                    continue

                online, delay = ProxyChecker(timeout=10).check_connectivity()
                if online:
                    logger.info("%s 可用! 延迟: %.0fms", profile.remarks, delay)
                    # 兜底成功路径此前漏掉了系统全局代理（与 connect_best
                    # 成功路径对齐）：连接虽已建立，但 Windows 应用不会
                    # 自动走代理，用户会误以为"没连上"。
                    try:
                        from config import get_socks_port_from_config
                        from core.system_proxy import set_global_proxy
                        set_global_proxy(
                            '127.0.0.1', get_socks_port_from_config())
                    except Exception:
                        logger.warning(
                            '设置系统代理失败（不影响已建立的连接）',
                            exc_info=True)
                    return True
                else:
                    logger.warning("%s 不可用", profile.remarks)

            logger.error("所有候选节点均不可用（已尝试 %d 个）", limit)
            return False
        finally:
            self.db.close()

    # ========== 实时测速扫描（并发，对标 v2rayN「全部同时测速」） ==========

    @staticmethod
    def _is_broken(p: ProfileItem) -> bool:
        a = (p.address or '').strip().lower()
        if a in ('', '127.0.0.1', 'localhost', '0.0.0.0'):
            return True
        if not isinstance(p.port, int) or p.port <= 0 or p.port >= 65535:
            return True
        return False

    @staticmethod
    def _wait_for_port(port: int, timeout: float = 6.0) -> bool:
        """Block until 127.0.0.1:<port> accepts a TCP connection.

        xray binds its SOCKS inbound a moment AFTER the process starts. The
        old code only slept 1.5s, so the checker often connected before the
        port existed -> ConnectionError -> "代理端口未监听" -> every node
        looked dead (false negative). Polling the port removes that race.
        """
        import socket
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                    return True
            except OSError:
                time.sleep(0.2)
        return False

    @staticmethod
    def _tcp_ping(address: str, port, timeout: float = 2.0):
        """TCP 握手延迟(ms)，对标 v2rayN「测试延迟 / TCP Ping」。

        仅量到节点服务器 address:port 的 TCP 连接耗时 —— 不起 xray 核心、
        不下文件，每个节点亚秒级，60+ 节点并发几秒测完。失败返回 None。
        """
        import socket
        if not address or not isinstance(port, int) or not (0 < port < 65535):
            return None
        try:
            start = time.time()
            with socket.create_connection((address, port), timeout=timeout):
                return round((time.time() - start) * 1000, 1)
        except (OSError, ValueError):
            return None

    def speedtest_all(self, limit: int = None, write_back: bool = True,
                      concurrency: int = 8, base_port: int = 20000,
                      top_k: int = 10, tcp_timeout: float = 2.0,
                      regions: Optional[List[str]] = None,
                      prefer_region: Optional[str] = None) -> list:
        """
        两阶段并发测速（对标 v2rayN 的快测 + 真实校验）：

          阶段1 TCP Ping：对全部候选节点并发量 TCP 握手延迟（不起 xray、不下
                文件，秒级），按延迟升序预筛；
          阶段2 真实校验：只对 TCP 延迟最低的 top_k 个节点起 xray，做「204 延迟
                + ChatGPT 可达」真实代理校验（去掉 1MB 下载测速，与 v2rayN
                延迟测试一致）。

        因此 60+ 节点通常 10~30 秒出结果；若 top_k 全部真实校验失败，调用方
        （connect_best）会退化为顺序逐个实测兜底。

        Args:
            limit:       只测前 N 个（None=全部）。
            write_back:  是否把结果写回数据库。
            concurrency: 阶段2 同时并发的 xray 实例数（默认 8）。
            base_port:   并发测速用的本地端口基底（默认 20000，避免占用主 10826）。
            top_k:       阶段2 真实校验的节点数（默认 6，取 TCP 延迟最低的前 N 个）。
            tcp_timeout: 阶段1 TCP Ping 超时（秒，默认 2.0）。
            regions:     只测 remarks 含这些关键词的节点（None=全部）。
            prefer_region: 同地区交换偏好：给定后阶段1 排序时同地区节点优先
                进入 top_k 做真实校验，保证候选集中包含当前地区节点
                （供质量切换等自动切换场景，防出口 IP 地区跳变触发风控）。
        Returns:
            排序后的结果列表（在线优先，ChatGPT 可达优先，延迟升序，速度降序），
            每项: {'profile', 'online', 'delay', 'speed', 'error', 'chatgpt'}
        """
        from adapters.xray_config import generate_node_config

        asset_dir = os.path.dirname(os.path.dirname(XRAY_EXE))
        tmp_dir = os.path.join(tempfile.gettempdir(), 'vpn_orch_speedtest')
        os.makedirs(tmp_dir, exist_ok=True)

        self.db.connect()
        try:
            RuntimeManager.cleanup_legacy_processes()  # 清掉残留代理进程
            profiles = self.db.get_all_profiles()
            candidates = [p for p in profiles if not self._is_broken(p)]
            # 按 (address, port) 去重：同一节点可能被多个订阅重复导入
            # （remarks 不同但端点是同一个），重复测试纯属浪费——实测兜底
            # 曾对同一 grpc 端点重试两次白白花掉 ~15s。
            _seen = set()
            _uniq = []
            for p in candidates:
                key = (p.address or '').strip().lower(), int(p.port or 0)
                if key not in _seen:
                    _seen.add(key)
                    _uniq.append(p)
            candidates = _uniq
            if regions:
                keys = [str(r).lower() for r in regions]
                candidates = [p for p in candidates
                              if any(k in (p.remarks or '').lower() for k in keys)]
            if limit:
                candidates = candidates[:limit]
            if not candidates:
                logger.warning('没有可测节点（全部为坏条目）')
                return []

            results = []  # list of (profile, online, delay, speed, error)

            def _launch(p, port, cpath, cfg):
                try:
                    with open(cpath, 'w', encoding='utf-8') as f:
                        json.dump(cfg, f, indent=2, ensure_ascii=False)
                    env = os.environ.copy()
                    env['XRAY_LOCATION_ASSET'] = asset_dir
                    proc = subprocess.Popen(
                        [XRAY_EXE, 'run', '-c', cpath],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        env=env,
                    )
                    return proc
                except Exception as e:
                    logger.warning('  启动 xray 失败 %s: %s', p.remarks, e)
                    return None

            def _kill(proc):
                if proc is not None and proc.poll() is None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass

            def _test_one(slot):
                p, proc, port, cpath, cfg = slot

                def _attempt():
                    try:
                        checker = ProxyChecker(
                            proxy_url=f'socks5://127.0.0.1:{port}', timeout=10)
                        online, delay = checker.check_connectivity()
                        res = {'online': online, 'delay_ms': delay,
                               'speed_mb_s': 0.0, 'error': '', 'chatgpt': False}
                        if online:
                            res['chatgpt'] = checker.is_reachable(
                                'https://chatgpt.com/')
                        else:
                            if delay == -1:
                                res['error'] = '连接被拒绝（代理端口未监听）'
                            elif delay == -2:
                                res['error'] = '代理协议错误（SOCKS5 协商失败/出站不可达）'
                            elif delay == -3:
                                res['error'] = '未知网络错误'
                            elif delay == -5:
                                res['error'] = '节点已连通但读取超时（无响应/被封锁）'
                            else:
                                res['error'] = f'请求超时或返回异常 (延迟: {delay}ms)'
                        return res
                    except Exception as e:
                        return {'online': False,
                                'error': f'{type(e).__name__}: {e}',
                                'chatgpt': False}

                if proc is None or proc.poll() is not None:
                    return (p, False, -1, 0.0, 'xray 启动失败', False)

                # Wait until xray's SOCKS inbound is actually listening so the
                # checker never hits a 'connection refused / port not
                # listening' race (the previous false-negative bug).
                if not self._wait_for_port(port, timeout=8.0):
                    # xray didn't bind in time — give it one more chance.
                    # Under concurrent load a freshly launched instance can
                    # take longer to open its SOCKS port; a relaunch + wait
                    # recovers these slow-starters instead of marking them dead.
                    _kill(proc)
                    time.sleep(0.3)
                    proc2 = _launch(p, port, cpath, cfg)
                    if proc2 is not None and self._wait_for_port(port, timeout=5.0):
                        res = _attempt()
                        if res['online']:
                            return (p, True, int(round(res['delay_ms'])),
                                    res['speed_mb_s'], '',
                                    res.get('chatgpt', False))
                        err = res.get('error', '代理端口未监听(启动超时)')
                        return (p, False, -1, 0.0, err, False)
                    return (p, False, -1, 0.0, '代理端口未监听(启动超时)', False)

                res = _attempt()
                if res['online']:
                    return (p, True, int(round(res['delay_ms'])),
                            res['speed_mb_s'], '',
                            res.get('chatgpt', False))

                # Transient failure (port not ready / SOCKS negotiation /
                # connection error)? Relaunch this node's xray once and
                # re-check — many nodes just need more time to establish
                # their tunnel. Only genuinely dead nodes stay offline.
                err = res.get('error', '')
                transient = (res.get('delay_ms') in (-1, -2, -3)
                             or '未监听' in err or '代理协议' in err
                             or '连接被拒绝' in err)
                if transient and cpath:
                    _kill(proc)
                    time.sleep(0.3)
                    proc2 = _launch(p, port, cpath, cfg)
                    if proc2 is not None:
                        self._wait_for_port(port, timeout=4.0)
                        res2 = _attempt()
                        if res2['online']:
                            return (p, True, int(round(res2['delay_ms'])),
                                    res2['speed_mb_s'], '',
                                    res2.get('chatgpt', False))
                        err = res2.get('error', err)
                    return (p, False, -1, 0.0, err, False)

                return (p, False, -1, 0.0, err, False)

            # ===== 阶段1：TCP Ping 全量预筛（不起 xray、不下文件，秒级） =====
            logger.info('[阶段1] TCP Ping 预筛 %d 个节点...', len(candidates))
            def _ping(p):
                return (p, self._tcp_ping(p.address, p.port, tcp_timeout))
            with cf.ThreadPoolExecutor(max_workers=min(32, len(candidates) or 1)) as _ex:
                _tcp = list(_ex.map(_ping, candidates))
            if prefer_region:
                # 同地区交换：同地区节点优先进入 top_k 做真实校验，
                # 保证质量切换的候选集中优先包含当前地区的节点。
                _tcp.sort(key=lambda x: (
                    0 if self.extract_region(x[0].remarks) == prefer_region else 1,
                    x[1] if x[1] is not None else 1e9))
            else:
                _tcp.sort(key=lambda x: x[1] if x[1] is not None else 1e9)
            for p, ms in _tcp:
                logger.info('  TCP %s -> %sms', p.remarks,
                            ('%.0f' % ms) if ms is not None else 'timeout')

            top_k = max(1, min(top_k, len(_tcp)))
            _top = _tcp[:top_k]
            _rest = _tcp[top_k:]
            _real_profiles = [p for p, _ in _top]
            logger.info('[阶段2] 真实校验 TCP 最低的 %d 个节点（无 1MB 下载）...',
                        len(_real_profiles))

            for batch_start in range(0, len(_real_profiles), concurrency):
                batch = _real_profiles[batch_start:batch_start + concurrency]
                procs = []  # (profile, Popen, port, cpath, cfg)
                for i, p in enumerate(batch):
                    port = base_port + i
                    cpath = os.path.join(tmp_dir, f'st_{i}.json')
                    cfg = generate_node_config(p, port)
                    proc = _launch(p, port, cpath, cfg)
                    procs.append((p, proc, port, cpath, cfg))

                with cf.ThreadPoolExecutor(max_workers=len(batch)) as ex:
                    for r in ex.map(_test_one, procs):
                        results.append(r)

                # 杀掉本批 xray
                for p, proc, port, cpath, cfg in procs:
                    _kill(proc)

                # 进度日志
                done = min(batch_start + concurrency, len(_real_profiles))
                logger.info('  测速进度 %d/%d', done, len(_real_profiles))

            # 未进 top_k 的节点：仅 TCP 预筛数据，不做真实校验
            for (p, ms) in _rest:
                results.append((p, False, int(ms) if ms is not None else -1, 0.0,
                                'TCP预筛未进前%d(未做真实校验)' % top_k, False))

            # 写回数据库
            if write_back:
                for (p, online, delay, speed, err, chatgpt) in results:
                    self.db.update_profile_stats(
                        p.index_id, delay, speed, err or 'OK')

            # 排序：在线优先；同在线时优先「能到 ChatGPT」；再按延迟升序、速度降序
            results.sort(key=lambda r: (
                0 if r[1] else 1,
                0 if (r[1] and r[5]) else (1 if r[1] else 2),
                r[2] if r[2] > 0 else 9_000_000,
                -r[3],
            ))
            return [{'profile': p, 'online': o, 'delay': d,
                     'speed': s, 'error': e, 'chatgpt': c}
                    for (p, o, d, s, e, c) in results]
        finally:
            RuntimeManager.cleanup_legacy_processes()  # 收尾，确保无残留
            self.db.close()

    # ========== 内部方法 ==========

    def _apply_and_restart(self, profile: ProfileItem) -> bool:
        logger.info("切换到: %s", profile.display())

        apply_profile_to_config(profile)

        if not self.proc.restart_xray():
            logger.error("Xray 重启失败")
            return False

        time.sleep(2)
        if self.proc.is_running():
            logger.info("Xray 运行正常")
            return True
        else:
            logger.error("Xray 未正常启动")
            return False
