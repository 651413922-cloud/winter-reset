#!/usr/bin/env python3
"""
VPN Orchestrator v0.1.0
基于 V2Ray/Sing-Box 协议级 VPN 自动化控制

用法:
    python main.py                   → 交互菜单
    python main.py auto              → 全自动连接 + 打开浏览器
    python main.py daemon            → 守护模式（持续监控+自动恢复）
    python main.py list              → 列出所有节点
    python main.py switch <名称/编号> → 切换到指定节点
    python main.py best              → 切换到最优节点
    python main.py start             → 启动 sing-box
    python main.py stop              → 停止 sing-box
    python main.py restart           → 重启 sing-box
    python main.py status            → 查看状态
    python main.py check             → 检测代理连通性
    python main.py browser           → 打开 ChatGPT/Gemini
"""

import sys
import os

# 确保能找到同级包
_orch_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _orch_root)

from core.logging_config import setup_logging

# 初始化日志（daemon 模式传入 debug=True 可开启 DEBUG 级别）
_debug = '--debug' in sys.argv
setup_logging(debug=_debug)

from orchestrator import VpnOrchestrator


def print_banner():
    print("""
╔══════════════════════════════════════════╗
║        VPN Orchestrator v0.1.0           ║
║     V2Ray/Sing-Box 协议级控制            ║
╚══════════════════════════════════════════╝
""")


def show_menu():
    print("""
可执行操作:
──────────────────────
  [0] 退出
  [1] 自动连接 (启动+检测+切换+浏览器)
  [2] 列出所有节点
  [3] 切换到指定节点 (输入名称或编号)
  [4] 切换到最优节点
  [5] 切换到可用节点 (遍历直到可用)
  [6] 查看状态
  [7] 检测代理连通性
  [8] 启动 VPN (sing-box)
  [9] 停止 VPN (sing-box)
  [10] 重启 VPN (sing-box)
  [11] 打开 ChatGPT + Gemini
  [12] 列出订阅
──────────────────────
""")


def run_interactive():
    """交互式菜单"""
    orch = VpnOrchestrator()
    print_banner()

    while True:
        show_menu()
        choice = input("请输入操作编号: ").strip()

        if choice == '0':
            print("再见!")
            break

        elif choice == '1':
            orch.auto_connect(open_browser=True)

        elif choice == '2':
            orch.list_nodes()

        elif choice == '3':
            name = input("输入节点名称或编号: ").strip()
            if name:
                orch.switch_node(name)

        elif choice == '4':
            orch.switch_best()

        elif choice == '5':
            orch.switch_working()

        elif choice == '6':
            orch.print_status_report()

        elif choice == '7':
            orch.check_proxy()

        elif choice == '8':
            orch.start()

        elif choice == '9':
            orch.stop()

        elif choice == '10':
            orch.restart()

        elif choice == '11':
            orch.open_browsers()

        elif choice == '12':
            orch.list_subscriptions()

        else:
            print("无效输入，请重新选择")

        input("\n按回车继续...")


def run_cli():
    """命令行参数模式"""
    orch = VpnOrchestrator()
    args = sys.argv[1:]

    if not args:
        run_interactive()
        return

    cmd = args[0]

    if cmd == 'auto':
        orch.auto_connect(open_browser=True)

    elif cmd == 'list':
        orch.list_nodes()

    elif cmd == 'switch':
        if len(args) < 2:
            print("用法: python main.py switch <节点名称或编号>")
            return
        orch.switch_node(args[1])

    elif cmd == 'best':
        orch.switch_best()

    elif cmd == 'working':
        orch.switch_working()

    elif cmd == 'start':
        orch.start()

    elif cmd == 'stop':
        orch.stop()

    elif cmd == 'restart':
        orch.restart()

    elif cmd == 'status':
        orch.print_status_report()

    elif cmd == 'check':
        orch.check_proxy()

    elif cmd == 'daemon':
        from daemon import VpnDaemon
        interval = float(args[1]) if len(args) > 1 else 30.0
        daemon = VpnDaemon(orch, interval=interval)
        daemon.run()

    elif cmd == 'browser':
        orch.open_browsers()

    elif cmd == 'subs':
        orch.list_subscriptions()

    else:
        print(f"未知命令: {cmd}")
        print("用法见文件开头注释")


if __name__ == '__main__':
    try:
        run_cli()
    except KeyboardInterrupt:
        print("\n\n已取消")
        sys.exit(0)
    except Exception as e:
        print(f"\n[错误] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)