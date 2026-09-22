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
import tempfile
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


def log_dir() -> str:
    """当前日志目录（main.py 的 fault.log 可与之放一起）。"""
    return _log_dir


def _dir_writable(path: str) -> bool:
    """探测目录是否可创建并可写文件。"""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_probe")
        with open(probe, "w") as f:
            f.write("1")
        os.remove(probe)
        return True
    except OSError:
        return False


def _resolve_log_dir(preferred: str = None) -> str:
    """优先用指定目录；不可写时依次回退：%LOCALAPPDATA%\\Step7AIAgent、临时目录。"""
    candidates = [preferred]
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        candidates.append(os.path.join(local_app, "Step7AIAgent", "logs"))
    candidates.append(os.path.join(tempfile.gettempdir(), "Step7AIAgent", "logs"))
    seen = set()
    for d in candidates:
        if not d or d in seen:
            continue
        seen.add(d)
        if _dir_writable(d):
            return d
    # 理论上 temp 一定可写；再兜底一个
    return os.path.join(tempfile.gettempdir(), "Step7AIAgent", "logs")


def setup_logging(log_dir: str = None, level: int = logging.INFO) -> str:
    """初始化根日志器，返回日志文件路径。

    必须在 QApplication 创建之前调用（避免 Qt 内部 log 被吞）。
    """
    global _initialized, _log_dir, _emitter
    if _initialized:
        return _log_file()

    preferred = log_dir or (
        os.path.dirname(sys.executable)
        if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(sys.argv[0] or __file__))
    )
    _log_dir = _resolve_log_dir(preferred)

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

    # 2. 控制台 handler（windowed exe / pythonw 下 stdout 为 None，跳过即可）
    stream = sys.stdout
    if stream is not None and hasattr(stream, "write"):
        console_handler = logging.StreamHandler(stream)
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
