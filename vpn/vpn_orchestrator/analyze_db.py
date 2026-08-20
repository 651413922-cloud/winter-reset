#!/usr/bin/env python3
"""分析 guiNDB.db 完整表结构 + v2rayN 节点切换机制"""

import sqlite3
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import GUI_DB, BASE_DIR, GUI_NCONFIG_PATH

print("=" * 70)
print("  Phase 1: guiNDB.db 完整分析")
print("=" * 70)

conn = sqlite3.connect(GUI_DB)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# 1. 所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [row['name'] for row in cursor.fetchall()]
print(f"\n📊 数据库表 ({len(tables)}):")
for t in tables:
    cursor.execute(f"SELECT COUNT(*) FROM [{t}]")
    count = cursor.fetchone()[0]
    print(f"  [{t}] = {count} 行")

# 2. ProfileItem 完整字段
print(f"\n{'='*70}")
print("  ProfileItem 节点表 - 完整字段")
print(f"{'='*70}")
cursor.execute("PRAGMA table_info(ProfileItem)")
cols = cursor.fetchall()
for c in cols:
    print(f"  {c['name']:30s} {c['type']:15s}")

# 3. 所有节点 + 全部字段值
print(f"\n{'='*70}")
print("  所有节点完整数据")
print(f"{'='*70}")
cursor.execute("SELECT * FROM ProfileItem ORDER BY Remarks")
rows = cursor.fetchall()
for r in rows:
    d = dict(r)
    print(f"\n  [{d['Remarks']}]")
    for k, v in d.items():
        if v is not None and str(v).strip():
            print(f"    {k:25s} = {v}")

# 4. ProfileExItem 节点性能
print(f"\n{'='*70}")
print("  ProfileExItem 节点性能数据")
print(f"{'='*70}")
cursor.execute("SELECT * FROM ProfileExItem")
for r in cursor.fetchall():
    d = dict(r)
    print(f"  IndexId={d['IndexId'][:30]:30s} | Delay={d['Delay']:5d}ms | Speed={d['Speed']:6.2f}MB/s | Sort={d['Sort']} | Msg={d['Message']}")

# 5. SubItem 订阅源
print(f"\n{'='*70}")
print("  SubItem 订阅源")
print(f"{'='*70}")
cursor.execute("SELECT Id, Remarks, Url, Enabled, AutoUpdateInterval FROM SubItem")
for r in cursor.fetchall():
    print(f"  Id={r['Id']:30s} | {r['Remarks']:25s} | Enabled={r['Enabled']} | AutoUpdate={r['AutoUpdateInterval']} | {r['Url'][:60]}")

# 6. 搜索所有含 index/select/active 的表
print(f"\n{'='*70}")
print("  v2rayN 节点切换关键字段搜索")
print(f"{'='*70}")
for t in tables:
    cursor.execute(f"PRAGMA table_info([{t}])")
    for col in cursor.fetchall():
        name = col['name'].lower()
        if any(kw in name for kw in ['index', 'select', 'sort', 'order', 'active', 'current']):
            print(f"  [{t}]::{col['name']} ({col['type']})")

conn.close()

# ======= Phase 2: guiNConfig.json =======
print(f"\n{'='*70}")
print("  Phase 2: guiNConfig.json 分析（v2rayN 配置状态）")
print(f"{'='*70}")

# 查找 guiNConfig.json
gui_config_path = None
for root, dirs, files in os.walk(BASE_DIR):
    for f in files:
        if f == 'guiNConfig.json':
            gui_config_path = os.path.join(root, f)
            break
    if gui_config_path:
        break

if gui_config_path:
    print(f"\n文件: {gui_config_path}")
    with open(gui_config_path) as f:
        cfg = json.load(f)
    
    print(f"顶层 keys: {json.dumps(list(cfg.keys()), indent=2)}")
    
    # 关键切换字段
    key_fields = ['indexId', 'selectedIndex', 'selectedServer', 'systemProxyItems',
                  'enableProxy', 'listenerType', 'localPort', 'enableTun',
                  'enableRouting', 'enableStatistics', 'enableWebView',
                  'showInTaskbar', 'startOnBoot']
    for k in key_fields:
        if k in cfg:
            print(f"  {k:30s} = {json.dumps(cfg[k], ensure_ascii=False)}")
    
    # 索引相关
    for k in cfg:
        if 'index' in k.lower() or 'select' in k.lower() or 'group' in k.lower():
            v = cfg[k]
            if isinstance(v, list):
                print(f"\n  {k} (list[{len(v)}]):")
                for item in v[:5]:
                    print(f"    {json.dumps(item, ensure_ascii=False)[:200]}")
            elif isinstance(v, dict):
                print(f"\n  {k}:")
                print(f"    {json.dumps(v, ensure_ascii=False)[:500]}")
            else:
                print(f"  {k:30s} = {v}")
else:
    print("  ⚠️ 未找到 guiNConfig.json")

print(f"\n{'='*70}")
print("  分析完成")
print(f"{'='*70}")