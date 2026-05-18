#!/usr/bin/env python3
"""
节点管理工具：去重 + 测速 + 更新订阅

用法:
    python manage_nodes.py dedup     # 去除重复节点
    python manage_nodes.py test      # 测试所有节点连通性
    python manage_nodes.py update    # 更新订阅
    python manage_nodes.py all       # 全部执行（去重 → 测速 → 更新订阅）
"""

import sys
import os
import time
import json
import base64
import logging
from typing import List, Dict, Tuple, Optional

_orch_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _orch_root)

from core.logging_config import setup_logging
setup_logging()

from core.db_manager import DbManager
from core.runtime_manager import RuntimeManager
from core.config_builder import apply_profile_to_config
from models.profile import ProfileItem
from services.proxy_checker import ProxyChecker

logger = logging.getLogger(__name__)


# ================================================================
#  去重
# ================================================================

def dedup_nodes(db: DbManager):
    """删除重复节点。重复判断标准：(address, port, network, path, password) 完全相同。"""
    db.connect()
    try:
        profiles = db.get_all_profiles()
        logger.info("共 %d 个节点，开始去重...", len(profiles))

        seen: Dict[Tuple, str] = {}  # key -> index_id (保留的第一个)
        to_remove: List[str] = []     # index_id 列表

        for p in profiles:
            key = (p.address, p.port, p.network, p.path, p.password)
            if key in seen:
                to_remove.append(p.index_id)
                logger.info("  重复: %s (保留 %s)", p.display(), p.remarks)
            else:
                seen[key] = p.index_id

        if not to_remove:
            logger.info("  没有发现重复节点")
            return 0

        logger.info("  将删除 %d 个重复节点...", len(to_remove))
        cur = db._conn
        for index_id in to_remove:
            cur.execute("DELETE FROM ProfileItem WHERE IndexId = ?", (index_id,))
            cur.execute("DELETE FROM ProfileExItem WHERE IndexId = ?", (index_id,))
        db._conn.commit()
        logger.info("  已删除 %d 个重复节点，剩余 %d 个", len(to_remove), len(profiles) - len(to_remove))
        return len(to_remove)
    finally:
        db.close()


# ================================================================
#  测速
# ================================================================

def test_all_nodes(db: DbManager, restart_xray: bool = True):
    """测试所有节点连通性。如果 restart_xray=True，逐个切换节点测试（精确但慢）。
    否则只在当前代理下做 TCP 连通性检测（快但不够精确）。"""
    db.connect()
    try:
        profiles = db.get_all_profiles()
        logger.info("共 %d 个节点，开始测试...", len(profiles))

        results = []
        rt = RuntimeManager()
        checker = ProxyChecker()

        for i, p in enumerate(profiles):
            logger.info("[%d/%d] %s", i + 1, len(profiles), p.display())

            if restart_xray:
                # 切节点 → 重启 xray → 测试代理
                apply_profile_to_config(p)
                rt.restart_xray()
                time.sleep(2)
                online, latency = checker.check_connectivity()
            else:
                # TCP 直连测试（不经过代理）
                import socket
                start = time.time()
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(5)
                    sock.connect((p.address, p.port))
                    sock.close()
                    latency = (time.time() - start) * 1000
                    online = True
                except Exception:
                    latency = -1
                    online = False

            delay = round(latency) if latency > 0 else -1
            db.update_profile_stats(p.index_id, delay, 0, 'OK' if online else 'FAIL')
            status = f"{'OK' if online else 'FAIL'}"
            if delay > 0:
                status += f" ({delay}ms)"
            logger.info("  → %s", status)
            results.append((p, online, delay))

        online_count = sum(1 for _, ok, _ in results if ok)
        logger.info("测试完成: %d/%d 在线", online_count, len(profiles))
        return results
    finally:
        db.close()


# ================================================================
#  订阅更新
# ================================================================

def parse_vmess_uri(uri: str) -> Optional[dict]:
    """解析 vmess:// 链接为节点字段"""
    if not uri.startswith('vmess://'):
        return None
    try:
        b64 = uri[8:]
        padding = 4 - len(b64) % 4
        if padding != 4:
            b64 += '=' * padding
        data = json.loads(base64.b64decode(b64).decode('utf-8'))
        return {
            'config_type': 1,  # VMess
            'remarks': data.get('ps', ''),
            'address': data.get('add', ''),
            'port': int(data.get('port', 0)),
            'password': data.get('id', ''),
            'network': data.get('net', 'tcp'),
            'path': data.get('path', ''),
            'request_host': data.get('host', ''),
            'stream_security': data.get('tls', 'none'),
            'sni': data.get('sni', ''),
            'fingerprint': data.get('fp', ''),
            'alpn': data.get('alpn', ''),
            'header_type': data.get('type', 'none'),
            'alter_id': data.get('aid', 0),
        }
    except Exception as e:
        logger.warning("  解析失败: %s... (%s)", uri[:60], e)
        return None


def parse_ss_uri(uri: str) -> Optional[dict]:
    """解析 ss:// 链接"""
    if not uri.startswith('ss://'):
        return None
    try:
        # ss://BASE64(method:password)@address:port#remarks
        # 或 ss://BASE64(method:password@address:port)#remarks
        rest = uri[5:]
        if '#' in rest:
            rest, remarks = rest.split('#', 1)
            from urllib.parse import unquote
            remarks = unquote(remarks)
        else:
            remarks = ''

        # 尝试新格式: method:password@address:port (整体 base64)
        try:
            padding = 4 - len(rest.split('@')[0]) % 4
            decoded = base64.b64decode(rest.split('@')[0] + '=' * (padding % 4)).decode()
            method, password = decoded.split(':', 1)
            addr_part = rest.split('@')[1] if '@' in rest else ''
        except:
            # 旧格式: method:password (base64) @ address:port
            parts = rest.split('@', 1)
            user_part = parts[0]
            padding = 4 - len(user_part) % 4
            decoded = base64.b64decode(user_part + '=' * (padding % 4)).decode()
            method, password = decoded.split(':', 1)
            addr_part = parts[1] if len(parts) > 1 else ''

        address, port_str = addr_part.split(':') if ':' in addr_part else ('', '0')
        return {
            'config_type': 3,  # Shadowsocks
            'remarks': remarks,
            'address': address,
            'port': int(port_str),
            'password': password,
            'network': 'tcp',
            'path': '',
            'request_host': '',
            'stream_security': 'none',
            'sni': '',
            'fingerprint': '',
            'alpn': '',
            'header_type': 'none',
            'alter_id': 0,
        }
    except Exception as e:
        logger.warning("  SS 解析失败: %s... (%s)", uri[:60], e)
        return None


def parse_proxy_uri(uri: str) -> Optional[dict]:
    """统一解析入口"""
    uri = uri.strip()
    if not uri:
        return None
    if uri.startswith('vmess://'):
        return parse_vmess_uri(uri)
    elif uri.startswith('ss://'):
        return parse_ss_uri(uri)
    else:
        return None


def update_subscriptions(db: DbManager):
    """从所有启用订阅更新节点列表"""
    import requests
    import urllib3
    urllib3.disable_warnings()

    db.connect()
    try:
        subs = db.get_subscriptions()
        enabled_subs = [s for s in subs if s['enabled']]
        logger.info("共 %d 个订阅（%d 个启用）", len(subs), len(enabled_subs))

        total_added = 0
        total_updated = 0
        existing_nodes = db.get_all_profiles()
        # 现有节点去重 key -> profile
        existing_keys: Dict[Tuple, ProfileItem] = {}
        for p in existing_nodes:
            key = (p.address, p.port, p.network, p.path, p.password)
            existing_keys[key] = p

        for sub in enabled_subs:
            logger.info("获取订阅: %s", sub['remarks'])
            try:
                resp = requests.get(
                    sub['url'],
                    timeout=30,
                    headers={'User-Agent': 'v2rayN/6.0'},
                    verify=False,
                )
                if resp.status_code != 200:
                    logger.warning("  HTTP %d, 跳过", resp.status_code)
                    continue

                raw = resp.text.strip()
                # Base64 解码
                try:
                    decoded = base64.b64decode(raw).decode('utf-8', errors='replace')
                except Exception:
                    decoded = raw

                lines = [l.strip() for l in decoded.split('\n') if l.strip()]
                logger.info("  获取到 %d 条节点", len(lines))

                cur = db._conn
                sub_added = 0
                sub_updated = 0

                # 获取该订阅现有节点 ID 集合（用于后续清理）
                old_nodes = db.get_profiles_by_sub_id(sub['id'])
                old_index_ids = {p.index_id for p in old_nodes}

                new_index_ids = set()

                for line in lines:
                    node_data = parse_proxy_uri(line)
                    if not node_data:
                        continue

                    key = (node_data['address'], node_data['port'],
                           node_data['network'], node_data['path'],
                           node_data['password'])

                    # 生成 IndexId (与 v2rayN 格式一致)
                    import uuid
                    new_index_id = str(uuid.uuid4()).replace('-', '')[:32].upper()

                    if key in existing_keys:
                        existing = existing_keys[key]
                        new_index_ids.add(existing.index_id)
                        cur.execute(
                            "UPDATE ProfileItem SET Subid = ?, Remarks = ? WHERE IndexId = ?",
                            (sub['id'], node_data['remarks'], existing.index_id)
                        )
                        sub_updated += 1
                    else:
                        new_index_ids.add(new_index_id)
                        ct = node_data['config_type']
                        # Build ProtoExtra based on type
                        if ct == 1:  # VMess
                            proto_extra = json.dumps({
                                "AlterId": str(node_data.get('alter_id', 0)),
                                "VmessSecurity": "auto"
                            }, indent=2)
                        elif ct == 3:  # SS
                            proto_extra = json.dumps({
                                "SsMethod": "aes-256-gcm"
                            }, indent=2)
                        else:
                            proto_extra = ''

                        cur.execute("""
                            INSERT INTO ProfileItem
                            (IndexId, ConfigType, ConfigVersion, Address, Port,
                             Ports, Id, AlterId, Security, Network, Remarks,
                             HeaderType, RequestHost, Path, StreamSecurity,
                             AllowInsecure, Subid, IsSub, Flow, Sni, Alpn,
                             CoreType, PreSocksPort, Fingerprint, DisplayLog,
                             PublicKey, ShortId, SpiderX, Mldsa65Verify, Extra,
                             MuxEnabled, Cert, CertSha, EchConfigList,
                             EchForceQuery, Password, Username, Finalmask,
                             ProtoExtra)
                            VALUES (?, ?, 3, ?, ?,
                                    NULL, NULL, ?, NULL, ?, ?,
                                    ?, ?, ?, ?,
                                    'False', ?, 1, NULL, ?, ?,
                                    NULL, NULL, ?, 1,
                                    NULL, NULL, NULL, NULL, NULL,
                                    NULL, NULL, NULL, NULL,
                                    NULL, ?, '', NULL,
                                    ?)
                        """, (
                            new_index_id, ct,
                            node_data['address'], node_data['port'],
                            node_data.get('alter_id', 0),
                            node_data['network'], node_data['remarks'],
                            node_data['header_type'], node_data['request_host'],
                            node_data['path'], node_data['stream_security'],
                            sub['id'],
                            node_data['sni'], node_data['alpn'],
                            node_data['fingerprint'],
                            node_data['password'],
                            proto_extra,
                        ))
                        sub_added += 1

                # 删除该订阅中已被远端移除的节点
                stale = old_index_ids - new_index_ids
                for sid in stale:
                    cur.execute("DELETE FROM ProfileItem WHERE IndexId = ?", (sid,))
                    cur.execute("DELETE FROM ProfileExItem WHERE IndexId = ?", (sid,))

                db._conn.commit()
                logger.info("  %s: 新增 %d, 更新 %d, 移除 %d",
                           sub['remarks'], sub_added, sub_updated, len(stale))
                total_added += sub_added
                total_updated += sub_updated

            except requests.exceptions.RequestException as e:
                logger.warning("  网络错误: %s", e)
            except Exception as e:
                logger.error("  处理失败: %s", e)
                import traceback
                traceback.print_exc()

        logger.info("订阅更新完成: 新增 %d, 更新 %d", total_added, total_updated)
        return total_added + total_updated
    finally:
        db.close()


# ================================================================
#  主入口
# ================================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]
    db = DbManager()

    if cmd == 'dedup':
        dedup_nodes(db)

    elif cmd == 'test':
        # 默认使用 TCP 直连测试（快），加 --full 用代理测试
        use_proxy = '--full' in sys.argv
        test_all_nodes(db, restart_xray=use_proxy)

    elif cmd == 'update':
        update_subscriptions(db)

    elif cmd == 'all':
        logger.info("=" * 50)
        logger.info("  第一步: 去重")
        logger.info("=" * 50)
        dedup_nodes(db)

        logger.info("")
        logger.info("=" * 50)
        logger.info("  第二步: 测速")
        logger.info("=" * 50)
        db2 = DbManager()
        test_all_nodes(db2, restart_xray=False)

        logger.info("")
        logger.info("=" * 50)
        logger.info("  第三步: 更新订阅")
        logger.info("=" * 50)
        db3 = DbManager()
        update_subscriptions(db3)

        logger.info("全部完成!")

    else:
        print(f"未知命令: {cmd}")
        print(__doc__)


if __name__ == '__main__':
    main()
