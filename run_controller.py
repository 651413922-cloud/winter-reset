#!/usr/bin/env python3
"""项目根启动脚本 — 方便从任意位置运行控制器

用法:
  python run_controller.py [--debug]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# 确保项目根在 sys.path 中，这样可以 `import apivpn` 即可
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', action='store_true', help='enable debug logging')
    args = parser.parse_args()

    import logging
    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=level, format='%(asctime)s %(levelname)s %(message)s')

    # 延迟导入包内模块，确保 sys.path 已设置
    try:
        from apivpn.controller import main as controller_main
    except Exception as e:
        logging.exception('无法导入 apivpn.controller: %s', e)
        raise

    controller_main()

if __name__ == '__main__':
    main()
