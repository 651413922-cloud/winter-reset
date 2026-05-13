#!/usr/bin/env python3
"""
完整的 VPN 架构分析：读取 SQLite、对比 config.json、提取所有控制点
"""
import sqlite3, json, os, sys

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'guiConfigs', 'guiNDB.db')
CACHE_PATH = os.path.join(os.path.dirname(__file__), '..', 'bin', 'cache.db')
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'binConfigs', 'config.json')

# =========== 1. 读取 GUI DB 全部 ProfileItem 的 Extra 字段 ===========
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# --- 1a. ProfileItem 完整数据 ---
cur.execute("SELECT * FROM ProfileItem")
profiles = cur.fetchall()
print("=" * 70)
print(f"[ProfileItem] 共 {len(profiles)} 个节点")
print("=" * 70)
for p in profiles:
    print(f"\n  节点: {p['Remarks']} (IndexId: {p['IndexId']})")
    print(f"    ConfigType: {p['ConfigType']}, CoreType: {p['CoreType']}")
    print(f"    Address: {p['Address']}:{p['Port']}")
    print(f"    Network: {p['Network']} | Security: {p['StreamSecurity']}")
    print(f"    Flow: {p['Flow']}")
    print(f"    Sni: {p['Sni']}")
    print(f"    Id/Password: {p['Password']}")
    print(f"    Fingerprint: {p['Fingerprint']}")
    print(f"    Extra 长度: {len(p['Extra'] or '')} chars")
    if p['Extra']:
        try:
            extra = json.loads(p['Extra'])
            print(f"    Extra parsed: {json.dumps(extra, indent=6, ensure_ascii=False)}")
        except:
            print(f"    Extra raw: {p['Extra']}")
    if p['ProtoExtra']:
        try:
            pe = json.loads(p['ProtoExtra'])
            print(f"    ProtoExtra: {json.dumps(pe, indent=6, ensure_ascii=False)}")
        except:
            print(f"    ProtoExtra raw: {p['ProtoExtra']}")
    if p['TransportExtra']:
        try:
            te = json.loads(p['TransportExtra'])
            print(f"    TransportExtra: {json.dumps(te, indent=6, ensure_ascii=False)}")
        except:
            print(f"    TransportExtra raw: {p['TransportExtra']}")
    if p['Subid']:
        print(f"    所属订阅: {p['Subid']}")

# --- 1b. ProfileExItem (延迟/速度) ---
cur.execute("SELECT * FROM ProfileExItem")
print("\n" + "=" * 70)
print("[ProfileExItem] 性能数据")
print("=" * 70)
for ex in cur.fetchall():
    print(f"  {ex['IndexId']} → delay={ex['Delay']}ms, speed={ex['Speed']}MB/s, msg={ex['Message']}")

# --- 1c. SubItem (订阅) ---
cur.execute("SELECT * FROM SubItem")
print("\n" + "=" * 70)
print("[SubItem] 订阅")
print("=" * 70)
for sub in cur.fetchall():
    print(f"  ID: {sub['Id']}")
    print(f"  备注: {sub['Remarks']}")
    print(f"  URL: {sub['Url']}")
    print(f"  启用: {sub['Enabled']}")
    print(f"  自动更新间隔: {sub['AutoUpdateInterval']}")
    print(f"  Filter: {sub['Filter']}")
    print(f"  ConvertTarget: {sub['ConvertTarget']}")

conn.close()

# =========== 2. 读取 cache.db ===========
if os.path.exists(CACHE_PATH):
    try:
        cconn = sqlite3.connect(CACHE_PATH)
        cc = cconn.cursor()
        cc.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cc.fetchall()
        print("\n" + "=" * 70)
        print("[cache.db] 表结构")
        print("=" * 70)
        for t in tables:
            cc.execute(f"PRAGMA table_info({t[0]})")
            cols = cc.fetchall()
            cc.execute(f"SELECT COUNT(*) FROM {t[0]}")
            cnt = cc.fetchone()[0]
            print(f"\n  表: {t[0]} ({cnt} 行)")
            for c in cols[:10]:
                print(f"    {c[1]} ({c[2]})")
            if cnt > 0 and cnt < 50:
                cc.execute(f"SELECT * FROM {t[0]} LIMIT 3")
                for row in cc.fetchall():
                    for i, v in enumerate(row):
                        vstr = str(v)[:150] if v else ''
                        if vstr:
                            print(f"      [{cols[i][1]}]: {vstr}")
                    print("      ---")
        cconn.close()
    except Exception as e:
        print(f"\n[cache.db] 读取失败: {e}")
else:
    print(f"\n[cache.db] 不存在: {CACHE_PATH}")

# =========== 3. 分析当前 config.json 中的活动节点 ===========
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)
    print("\n" + "=" * 70)
    print("[config.json] 当前运行配置分析")
    print("=" * 70)
    outbounds = config.get('outbounds', [])
    inbounds = config.get('inbounds', [])
    for ob in outbounds:
        if ob['tag'] == 'proxy':
            vnext = ob.get('settings', {}).get('vnext', [{}])[0]
            print(f"  当前活动节点: {vnext.get('address')}:{vnext.get('port')}")
            print(f"  协议: {ob['protocol']}")
            print(f"  StreamNetwork: {ob.get('streamSettings', {}).get('network')}")
            print(f"  Security: {ob.get('streamSettings', {}).get('security')}")
            if 'flow' in str(ob):
                for u in vnext.get('users', []):
                    print(f"  Flow: {u.get('flow')}")

    for ib in inbounds:
        print(f"\n  Inbound: {ib['tag']} → {ib['protocol']}://{ib.get('listen')}:{ib.get('port')}")

    routing = config.get('routing', {})
    print(f"\n  DomainStrategy: {routing.get('domainStrategy')}")
    print(f"  DNS: {config.get('dns', {}).get('tag')}")
    print(f"  LogLevel: {config.get('log', {}).get('loglevel')}")

print("\n" + "=" * 70)
print("分析完成")
print("=" * 70)