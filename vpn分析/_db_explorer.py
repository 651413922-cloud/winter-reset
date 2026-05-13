import sqlite3
import json

conn = sqlite3.connect('guiConfigs/guiNDB.db')
cursor = conn.cursor()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print("=== TABLES ===")
for t in tables:
    cursor.execute(f"PRAGMA table_info({t[0]})")
    cols = cursor.fetchall()
    print(f"\nTable: {t[0]}")
    print("  Columns:")
    for c in cols:
        print(f"    {c[1]} ({c[2]})")
    cursor.execute(f"SELECT COUNT(*) FROM {t[0]}")
    rowcount = cursor.fetchone()[0]
    print(f"  Row count: {rowcount}")

# 列出所有节点的关键信息
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
for t in cursor.fetchall():
    tname = t[0]
    print(f"\n\n=== DATA FROM [{tname}] ===")
    cursor.execute(f"SELECT * FROM {tname} LIMIT 5")
    rows = cursor.fetchall()
    cursor.execute(f"PRAGMA table_info({tname})")
    colnames = [c[1] for c in cursor.fetchall()]
    for row in rows:
        for i, val in enumerate(row):
            if val is not None:
                val_str = str(val)
                if len(val_str) > 200:
                    val_str = val_str[:200] + "..."
                print(f"  {colnames[i]}: {val_str}")
        print("  ---")

conn.close()