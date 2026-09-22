# -*- coding: utf-8 -*-
"""STEP 7 AI Agent 程序入口"""
import faulthandler
import logging
import os
import sys
import tempfile
import threading
import traceback
from datetime import datetime


def _base_dir() -> str:
    return (
        os.path.dirname(sys.executable)
        if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__))
    )


def _report(title: str, tp=None, val=None, tb=None) -> None:
    """把未捕获异常写入日志并尽量弹出提示框。

    优先使用调用方显式传入的异常三元组：sys.excepthook 被 PySide6 在 Qt 槽
    异常中回调时，当前线程的 sys.exc_info() 已被清空，traceback.format_exc()
    只会得到 "NoneType: None"，真实堆栈必须从参数取。
    """
    if tp is not None:
        detail = "".join(traceback.format_exception(tp, val, tb))
    else:
        detail = traceback.format_exc()
    try:
        log = logging.getLogger("main")
        log.error("%s:\n%s", title, detail)
    except Exception:
        # 日志系统可能还没初始化，兜底写文件
        for d in (_base_dir(), tempfile.gettempdir()):
            try:
                with open(os.path.join(d, "startup.log"), "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.now():%H:%M:%S.%f}] {title}:\n{detail}\n")
                break
            except OSError:
                continue
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is not None:
            box = QMessageBox(QMessageBox.Icon.Critical, "程序错误",
                              f"{title}，详情见 app.log：\n\n{detail[-1200:]}")
            box.exec()
    except Exception:
        pass


def _install_hooks() -> None:
    def sys_hook(tp, val, tb):
        if issubclass(tp, KeyboardInterrupt):
            sys.__excepthook__(tp, val, tb)
            return
        _report("未捕获的异常", tp, val, tb)

    def thread_hook(args):
        if issubclass(args.exc_type, SystemExit):
            return
        try:
            log = logging.getLogger("main")
            log.error("线程 %s 未捕获异常:\n%s",
                      args.thread.name if args.thread else "?",
                      "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
        except Exception:
            pass

    sys.excepthook = sys_hook
    threading.excepthook = thread_hook
    # 捕获原生层崩溃（访问冲突等），写入 fault.log；首选日志目录，逐级兜底
    fault_dirs = []
    try:
        from app.core.logger import log_dir
        if log_dir():
            fault_dirs.append(log_dir())
    except Exception:
        pass
    fault_dirs.extend([_base_dir(), tempfile.gettempdir()])
    for d in fault_dirs:
        try:
            fault_path = os.path.join(d, "fault.log")
            fault_file = open(fault_path, "a", encoding="utf-8", errors="replace")
            fault_file.write(f"\n===== session {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
            fault_file.flush()
            faulthandler.enable(fault_file)
            break
        except OSError:
            continue


def main():
    # 在导入 PySide6 之前：强制软件渲染 + 初始化日志
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("QSG_RHI_BACKEND", "software")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")

    # 初始化统一日志（文件 + 控制台 + Qt信号桥 已就绪，等 MainWindow 设置 emitter）
    log_path = ""
    try:
        from app.core.logger import setup_logging
        log_path = setup_logging(_base_dir())
    except Exception:
        # 日志模块自身 import 失败时兜底
        pass

    _install_hooks()

    log = logging.getLogger("main")
    log.info("=== launch start ===")

    try:
        log.info("importing PySide6...")
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL, True)

        log.info("importing MainWindow...")
        from app.ui.main_window import MainWindow

        log.info("creating QApplication...")
        app = QApplication(sys.argv)
        app.setApplicationName("STEP 7 AI Agent")
        app.setOrganizationName("Step7AIAgent")

        from app.ui.theme import apply_theme
        apply_theme(app)

        log.info("creating MainWindow...")
        window = MainWindow()
        log.info("showing window...")
        window.show()
        log.info("entering event loop...")
        sys.exit(app.exec())
    except Exception:
        log.exception("EXCEPTION during startup")
        raise


if __name__ == "__main__":
    main()
