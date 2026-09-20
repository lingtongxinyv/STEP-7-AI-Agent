# -*- coding: utf-8 -*-
"""统一日志模块。

使用标准库 logging，同时输出到：
1. 文件 app.log（UTF-8，带 rotation，自动保留最近 5 个备份）
2. Qt 信号（供 UI 实时显示）
3. 控制台（开发时）

用法：
    from app.core.logger import get_logger
    log = get_logger(__name__)
    log.info("连接 PLC 成功")
    log.warning("模型响应超时")
    log.error("MCGS 导入 CSV 失败", exc_info=True)

UI 集成：
    from app.core.logger import QtLogEmitter, set_log_emitter
    emitter = QtLogEmitter()
    set_log_emitter(emitter)
    emitter.log_record.connect(self._on_log_record)
"""
import logging
import logging.handlers
import os
import sys
from datetime import datetime
from typing import Optional, Callable

try:
    from PySide6.QtCore import QObject, Signal
    HAS_QT = True
except ImportError:
    HAS_QT = False


# ---------------- Qt 信号桥 ----------------

if HAS_QT:
    class QtLogEmitter(QObject):
        """把 logging.LogRecord 转为 Qt Signal，供 UI 实时显示。"""
        log_record = Signal(int, str, str, str)  # (level, time, logger, message)

    _emitter: Optional[QtLogEmitter] = None
else:
    _emitter = None


def set_log_emitter(emitter) -> None:
    """设置全局 Qt 日志发射器（MainWindow 启动时调用一次）。"""
    global _emitter
    _emitter = emitter


class _QtBridgeHandler(logging.Handler):
    """把 logging 记录转发到 Qt Signal。"""

    def emit(self, record: logging.LogRecord) -> None:
        if _emitter is None:
            return
        try:
            msg = self.format(record)
            time_str = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
            _emitter.log_record.emit(
                record.levelno, time_str, record.name, record.getMessage()
            )
        except Exception:
            pass


# ---------------- 初始化 ----------------

_initialized = False
_log_dir = ""


def _log_file() -> str:
    return os.path.join(_log_dir, "app.log")


def setup_logging(log_dir: str = None, level: int = logging.INFO) -> str:
    """初始化根日志器，返回日志文件路径。

    必须在 QApplication 创建之前调用（避免 Qt 内部 log 被吞）。
    """
    global _initialized, _log_dir, _emitter
    if _initialized:
        return _log_file()

    _log_dir = log_dir or (
        os.path.dirname(sys.executable)
        if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(sys.argv[0] or __file__))
    )
    os.makedirs(_log_dir, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    # 清空默认 handler（避免重复）
    root.handlers.clear()

    # 1. 文件 handler（带 rotation，每个 5MB，保留 5 个）
    file_handler = logging.handlers.RotatingFileHandler(
        _log_file(), maxBytes=5 * 1024 * 1024, backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(file_handler)

    # 2. 控制台 handler（开发时看 print）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(
        "[%(levelname)-7s] %(name)s: %(message)s",
    ))
    root.addHandler(console_handler)

    # 3. Qt 信号桥（等 MainWindow 创建后 setup_log_emitter 再转发）
    qt_handler = _QtBridgeHandler()
    qt_handler.setLevel(level)
    root.addHandler(qt_handler)
    _emitter = None  # 等 UI 设置

    _initialized = True

    # 记录启动信息
    root.info("=" * 60)
    root.info(f"日志系统初始化完成: {_log_file()}")
    root.info(f"Python {sys.version}")
    root.info(f"Platform: {sys.platform}")
    root.info("=" * 60)

    return _log_file()


def get_logger(name: str) -> logging.Logger:
    """获取模块级日志器。"""
    return logging.getLogger(name)


def tail_log(n: int = 50) -> list:
    """读取日志文件最后 n 行（供 UI 加载历史）。"""
    path = _log_file()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()[-n:]
    except Exception:
        return []
