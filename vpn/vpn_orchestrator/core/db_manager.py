"""SQLite 数据库管理器 - 直接读取 v2rayN 的 guiNDB.db"""

import logging
import sqlite3
from typing import List, Optional

from config import GUI_DB
from models.profile import ProfileItem, profile_from_db_row

logger = logging.getLogger(__name__)


class DbManager:
    """操作 v2rayN 的 SQLite 数据库"""

    def __init__(self, db_path: str = GUI_DB):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self):
        """打开数据库连接（使用 Row 模式方便按列名访问）"""
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        return self

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _ensure_connected(self):
        if not self._conn:
            raise RuntimeError("数据库未连接，请先调用 .connect()")

    # ========== 节点操作 ==========

    def get_all_profiles(self) -> List[ProfileItem]:
        """获取所有节点"""
        self._ensure_connected()
        cur = self._conn.execute("SELECT * FROM ProfileItem ORDER BY Remarks")
        return [profile_from_db_row(row) for row in cur.fetchall()]

    def get_profile_by_index_id(self, index_id: str) -> Optional[ProfileItem]:
        """按 IndexId 查找节点"""
        self._ensure_connected()
        cur = self._conn.execute(
            "SELECT * FROM ProfileItem WHERE IndexId = ?", (index_id,)
        )
        row = cur.fetchone()
        return profile_from_db_row(row) if row else None

    def get_profile_by_name(self, name: str) -> Optional[ProfileItem]:
        """按名称（模糊匹配）查找节点"""
        self._ensure_connected()
        cur = self._conn.execute(
            "SELECT * FROM ProfileItem WHERE Remarks LIKE ?",
            (f'%{name}%',)
        )
        row = cur.fetchone()
        return profile_from_db_row(row) if row else None

    def get_profiles_by_sub_id(self, sub_id: str) -> List[ProfileItem]:
        """获取某个订阅下的所有节点"""
        self._ensure_connected()
        cur = self._conn.execute(
            "SELECT * FROM ProfileItem WHERE Subid = ?", (sub_id,)
        )
        return [profile_from_db_row(row) for row in cur.fetchall()]

    # ========== 活动节点管理 ==========

    def get_active_profile(self) -> Optional[ProfileItem]:
        """
        获取当前活动节点。
        v2rayN 中活动节点由 guiNConfig.json 的 IndexId 标识。
        我们通过直接读取 config.json（运行时实际使用的节点）来定位。
        """
        # 该功能在 config_builder 中结合 config.json 实现更准确
        # 这里仅返回第一个节点作为备用
        profiles = self.get_all_profiles()
        return profiles[0] if profiles else None

    # ========== 性能数据 ==========

    def get_profile_stats(self, index_id: str) -> dict:
        """获取节点的性能数据（延迟/速度）"""
        self._ensure_connected()
        cur = self._conn.execute(
            "SELECT * FROM ProfileExItem WHERE IndexId = ?", (index_id,)
        )
        row = cur.fetchone()
        if row:
            return {
                'delay': row['Delay'],
                'speed': row['Speed'],
                'message': row['Message'],
                'sort': row['Sort'],
            }
        return {'delay': -1, 'speed': 0.0, 'message': '无数据'}

    # ========== 订阅操作 ==========

    def get_subscriptions(self) -> List[dict]:
        """获取所有订阅源"""
        self._ensure_connected()
        cur = self._conn.execute("SELECT * FROM SubItem")
        rows = cur.fetchall()
        return [
            {
                'id': r['Id'],
                'remarks': r['Remarks'],
                'url': r['Url'],
                'enabled': bool(r['Enabled']),
                'auto_update_interval': r['AutoUpdateInterval'],
                'filter': r['Filter'],
            }
            for r in rows
        ]

    def get_subscription_by_id(self, sub_id: str) -> Optional[dict]:
        """按 ID 查找订阅"""
        self._ensure_connected()
        cur = self._conn.execute(
            "SELECT * FROM SubItem WHERE Id = ?", (sub_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            'id': row['Id'],
            'remarks': row['Remarks'],
            'url': row['Url'],
            'enabled': bool(row['Enabled']),
            'auto_update_interval': row['AutoUpdateInterval'],
            'filter': row['Filter'],
        }

    # ========== 写操作 ==========

    def update_profile_extra(self, index_id: str, column: str, value):
        """更新节点的某个字段（如 Extra, ProtoExtra 等）"""
        self._ensure_connected()
        safe_columns = {'Extra', 'ProtoExtra', 'TransportExtra',
                        'Remarks', 'Sni', 'Fingerprint', 'AllowInsecure'}
        if column not in safe_columns:
            raise ValueError(f"不允许修改字段: {column}")
        self._conn.execute(
            f"UPDATE ProfileItem SET {column} = ? WHERE IndexId = ?",
            (value, index_id)
        )
        self._conn.commit()

    def update_profile_stats(self, index_id: str, delay: int, speed: float, message: str = ''):
        """更新节点的性能数据"""
        self._ensure_connected()
        self._conn.execute(
            """INSERT OR REPLACE INTO ProfileExItem
               (IndexId, Delay, Speed, Sort, Message)
               VALUES (?, ?, ?, 0, ?)""",
            (index_id, delay, speed, message)
        )
        self._conn.commit()

    # ========== 工具方法 ==========

    @staticmethod
    def _safe_print(msg):
        try:
            print(msg)
        except UnicodeEncodeError:
            import sys
            print(msg.encode(sys.stdout.encoding or 'utf-8', errors='replace')
                      .decode(sys.stdout.encoding or 'utf-8'))

    def print_all_profiles(self):
        """打印所有节点信息"""
        profiles = self.get_all_profiles()
        self._safe_print(f"\n共 {len(profiles)} 个节点:")
        self._safe_print("-" * 70)
        for i, p in enumerate(profiles, 1):
            stats = self.get_profile_stats(p.index_id)
            delay_str = f"{stats['delay']}ms" if stats['delay'] >= 0 else "未测"
            speed_str = f"{stats['speed']}MB/s" if stats['speed'] > 0 else ""
            self._safe_print(f"  {i}. {p.display()}")
            self._safe_print(f"     UUID: {p.password[:8]}... | Flow: {p.effective_flow}")
            self._safe_print(f"     Path: {p.effective_path} | SNI: {p.sni or '(同地址)'}")
            self._safe_print(f"     延迟: {delay_str} | 速度: {speed_str}")
            self._safe_print("")

    def print_subscriptions(self):
        """打印所有订阅"""
        subs = self.get_subscriptions()
        print(f"\n共 {len(subs)} 个订阅:")
        print("-" * 70)
        for s in subs:
            status = "✅ 启用" if s['enabled'] else "⛔ 禁用"
            print(f"  {s['remarks']}: {s['url']} [{status}]")
            profiles = self.get_profiles_by_sub_id(s['id'])
            print(f"    节点数: {len(profiles)}")