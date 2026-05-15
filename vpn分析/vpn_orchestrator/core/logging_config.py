"""统一日志配置。其他模块通过 logging.getLogger(__name__) 获取 logger。"""

import logging
import os
import sys


def setup_logging(level: int = logging.INFO,
                  log_file: str | None = None,
                  debug: bool = False) -> None:
    """配置根 logger，所有子 logger 自动继承。

    Args:
        level: 控制台输出级别
        log_file: 文件路径（None 则不写文件）
        debug: 是否开启 DEBUG 级别
    """
    if debug:
        level = logging.DEBUG

    _fmt_str = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
    _datefmt = "%H:%M:%S"
    fmt = logging.Formatter(_fmt_str, datefmt=_datefmt)

    # 控制台 handler (兼容 Windows GBK，自动过滤 emoji)
    class _SafeFormatter(logging.Formatter):
        def format(self, record):
            msg = super().format(record)
            enc = sys.stdout.encoding or 'utf-8'
            try:
                msg.encode(enc)
            except UnicodeEncodeError:
                msg = msg.encode(enc, errors='replace').decode(enc)
            return msg

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(_SafeFormatter(_fmt_str, datefmt=_datefmt))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # root 设最低，由各 handler 控制
    # 清除已有的 handler（避免重复配置）
    root.handlers.clear()
    root.addHandler(console)

    # 文件 handler（DEBUG 级别）
    if log_file is None:
        log_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "vpn_orchestrator.log",
        )
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
