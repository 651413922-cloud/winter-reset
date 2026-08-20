#!/usr/bin/env python3
"""
VPN Orchestrator v0.1.0
基于 V2Ray/Sing-Box 协议级 VPN 自动化控制

用法:
    python main.py                   → 交互菜单
    python main.py auto              → 全自动连接 + 打开浏览器
    python main.py daemon            → 守护模式（持续监控+自动恢复）
    python main.py watch             → 守护+质量监控（延迟持续超标自动切换更优节点）
                                    用法: watch [间隔秒=30] [延迟阈值ms=600] [连续次数=3] [跨地区0/1]
                                    默认「同地区交换」：自动切换只在与当前节点相同
                                    地区的节点里选，防出口 IP 地区跳变触发风控。
    python main.py list              → 列出所有节点
    python main.py switch <名称/编号> → 切换到指定节点
    python main.py best              → 切换到最优节点
    python main.py start             → 启动 sing-box
    python main.py stop              → 停止 sing-box
    python main.py restart           → 重启 sing-box
    python main.py status            → 查看状态
    python main.py check             → 检测代理连通性
    python main.py speedtest [N]      → 实时测速前 N 个节点并写回数据库
    python main.py connect            → 并发测速全部节点→选最优→连接（自动化入口）
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
        orch.disable_system_proxy()

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

    elif cmd == 'watch':
        # 守护 + 质量监控：当前节点延迟持续超标自动切换更优节点。
        # 用法: watch [间隔秒] [延迟阈值ms] [连续次数] [跨地区0/1]
        #   python main.py watch                # 30s/600ms/连续3次/同地区交换
        #   python main.py watch 15 800 2       # 15s 间隔、800ms 阈值、连续2次
        #   python main.py watch 30 600 3 1     # 允许跨地区兜底（默认同地区）
        from daemon import VpnDaemon
        interval = float(args[1]) if len(args) > 1 else 30.0
        threshold = float(args[2]) if len(args) > 2 else 600.0
        consecutive = int(args[3]) if len(args) > 3 else 3
        cross = bool(int(args[4])) if len(args) > 4 else False
        daemon = VpnDaemon(orch, interval=interval,
                           latency_threshold_ms=threshold,
                           min_consecutive=consecutive,
                           allow_cross_region=cross)
        daemon.run()

    elif cmd == 'browser':
        orch.open_browsers()

    elif cmd == 'subs':
        orch.list_subscriptions()

    elif cmd == 'speedtest':
        # 实时测速全部/前 N 个节点并写回数据库（等价 v2rayN 的「测试」）
        limit = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
        orch.speedtest_nodes(limit=limit, write_back=True)

    elif cmd == 'connect':
        # 并发测速全部节点 → 选最优 → 连接（自动化入口）
        orch.connect_best(open_browser=('--browser' in args))

    elif cmd == 'proxy-on':
        # 仅把 Windows 系统代理设为全局（不动 xray；用于代理已起时）
        if orch.enable_system_proxy():
            print("系统代理已设为全局 127.0.0.1:10826（所有浏览器/应用自动走代理）")
        else:
            print("[失败] 设置系统代理失败（见上方日志）")

    elif cmd == 'proxy-off':
        # 关闭系统代理（恢复直连）
        if orch.disable_system_proxy():
            print("系统代理已关闭（恢复直连）")
        else:
            print("[失败] 关闭系统代理失败（见上方日志）")

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