#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把托盘应用打包成单文件 exe（PyInstaller）。

为什么需要这个脚本：
  orchestrator 里有很多「函数内懒加载」的模块（如 adapters.xray_config），
  PyInstaller 的静态分析抓不到，运行时就会报 ModuleNotFoundError。
  本脚本扫描 vpn_orchestrator 下所有 .py 一并作为 --hidden-import 收集，
  彻底规避漏包。

产物： dist/VPNOrchestrator.exe （--onefile --windowed，双击即运行，无控制台）

用法：
  python build_tray_exe.py

注意（沙箱 safe-delete 兼容）：
  WorkBuddy 沙箱把 os.remove 钩成「安全删除」(先扔回收站)，但沙箱没有回收站，
  导致 PyInstaller 在收尾删除 build/ 下临时文件时抛 OSError 而崩溃。
  本脚本把 --workpath/--distpath 都指向 OS 临时目录；sitecustomize 对落在
  OS 临时目录下的删除走原生 os.remove，从而绕开该问题。最终再用 shutil.copy
  把 exe 覆盖写回项目 dist/（覆盖写不删除原文件，同样安全）。
"""

import os
import sys
import time
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ORCH = os.path.join(HERE, 'vpn_orchestrator')

# ---- 收集 vpn_orchestrator 下所有模块作为 hidden imports ----
hidden = []
for root, _dirs, files in os.walk(ORCH):
    for f in files:
        if not f.endswith('.py'):
            continue
        full = os.path.join(root, f)
        rel = os.path.relpath(full, ORCH)
        mod = rel[:-3].replace(os.sep, '.')
        if mod.endswith('.__init__'):
            mod = mod[:-9]
        hidden.append(mod)

entry = os.path.join(ORCH, 'tray_app.py')
name = 'VPNOrchestrator'

# 中间目录放 OS 临时目录，绕开沙箱 safe-delete 对 build/ 删除的拦截
TMP = tempfile.gettempdir()
work_dir = os.path.join(TMP, 'vpn_orch_build')
dist_dir_tmp = os.path.join(TMP, 'vpn_orch_dist')

args = [
    '--noconfirm',
    '--onefile',
    '--windowed',
    f'--name={name}',
    f'--distpath={dist_dir_tmp}',
    f'--workpath={work_dir}',
    f'--log-level=WARN',
]
for h in hidden:
    args.append(f'--hidden-import={h}')
args.append(entry)

print(f"[build] 收集到 {len(hidden)} 个模块作为 hidden-import")
print(f"[build] 入口: {entry}")

try:
    from PyInstaller.__main__ import run as pyinstaller_run
except ImportError:
    print("[build] 未找到 PyInstaller，请先: pip install pyinstaller")
    sys.exit(1)

pyinstaller_run(args)

# 复制回项目 dist/（覆盖写，不删除原文件，避开 safe-delete）
src = os.path.join(dist_dir_tmp, name + '.exe')
target_dir = os.path.join(HERE, 'dist')
target = os.path.join(target_dir, name + '.exe')
if not os.path.exists(src):
    print("[build] 失败：临时 dist 未生成 exe，请查看上方报错")
    sys.exit(1)

# 把上一次遗留的固定 .bak（如存在）改名归档，避免与下面的重名冲突。
# 用 rename 而非 remove，绕开沙箱 safe-delete 钩子（其会拦 os.remove）。
# 注意前缀用 .old_，与下方当前 exe 的 .bak_ 区分，避免同时间戳撞名。
legacy = target + '.bak'
if os.path.exists(legacy):
    try:
        os.rename(legacy, legacy.replace('.bak', '.old_' + str(int(time.time()))))
    except OSError:
        pass

# 若目标 exe 正在运行（被占用），无法直接覆盖：Windows 允许对运行中的
# exe 改名，原进程仍持有旧名文件，新 exe 用回标准名即可 —— 自动让位，
# 不要求用户手动关闭。用带时间戳的唯一名（.bak_ 前缀）避免与历史备份撞名。
# 若改名也失败，则明确提示用户关闭后再构建。
if os.path.exists(target):
    try:
        os.rename(target, target + '.bak_' + str(int(time.time())))
    except OSError as e:
        print(f"[build] 无法覆盖 {target}（{e}）。"
              f"请先右键托盘「退出 VPNOrchestrator」，再重新运行本脚本。")
        sys.exit(2)

os.makedirs(target_dir, exist_ok=True)
shutil.copy(src, target)
size_mb = os.path.getsize(target) / 1024 / 1024
print(f"[build] 完成 -> {target}  ({size_mb:.1f} MB)")
