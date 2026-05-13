#!/usr/bin/env python3
"""调试 sing-box 启动问题"""

import os
import sys
import subprocess
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import SING_BOX_EXE, CONFIG_JSON

print("=== 文件完整性检查 ===")
print(f"sing-box: {SING_BOX_EXE}")
print(f"  存在: {os.path.exists(SING_BOX_EXE)}")
if os.path.exists(SING_BOX_EXE):
    print(f"  大小: {os.path.getsize(SING_BOX_EXE)} bytes")

print(f"config.json: {CONFIG_JSON}")
print(f"  存在: {os.path.exists(CONFIG_JSON)}")
if os.path.exists(CONFIG_JSON):
    print(f"  大小: {os.path.getsize(CONFIG_JSON)} bytes")
    try:
        with open(CONFIG_JSON) as f:
            cfg = json.load(f)
        print(f"  Outbounds: {len(cfg.get('outbounds', []))}")
        print(f"  Inbounds: {len(cfg.get('inbounds', []))}")
        for ob in cfg.get('outbounds', []):
            print(f"    - {ob.get('type')} / {ob.get('tag')}")
    except Exception as e:
        print(f"  JSON 解析失败: {e}")

print("\n=== 尝试直接运行 sing-box ===")
try:
    result = subprocess.run(
        [SING_BOX_EXE, 'version'],
        capture_output=True,
        text=True,
        timeout=5
    )
    print(f"退出码: {result.returncode}")
    if result.stdout:
        print(f"标准输出:\n{result.stdout}")
    if result.stderr:
        print(f"错误输出:\n{result.stderr}")
except FileNotFoundError:
    print("❌ sing-box.exe 未找到!")
except Exception as e:
    print(f"❌ 异常: {e}")

print("\n=== 尝试启动 sing-box (后台) ===")
try:
    proc = subprocess.Popen(
        [SING_BOX_EXE, 'run', '-c', CONFIG_JSON],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    import time
    time.sleep(2)
    
    # 检查进程状态
    poll = proc.poll()
    if poll is not None:
        print(f"进程已退出，退出码: {poll}")
        stdout, stderr = proc.communicate(timeout=3)
        if stderr:
            print(f"错误输出:\n{stderr.decode('utf-8', errors='replace')[:2000]}")
    else:
        print(f"进程运行中 (PID: {proc.pid})")
        proc.terminate()
        proc.wait()
        print("进程已终止")
except Exception as e:
    print(f"❌ 异常: {e}")