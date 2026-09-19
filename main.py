# -*- coding: utf-8 -*-
"""STEP 7 AI Agent 程序入口"""
import faulthandler
import os
import sys
import threading
import traceback
from datetime import datetime


def _base_dir() -> str:
    return (
        os.path.dirname(sys.executable)
        if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__))
    )


def _log(msg: str) -> None:
    """向 exe 同目录写入启动日志，便于排查打包后问题。"""
    try:
        with open(os.path.join(_base_dir(), "startup.log"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S.%f}] {msg}\n")
    except Exception:
        pass


def _report(title: str) -> None:
    """把未捕获异常写入日志并尽量弹出提示框（windowed exe 的 stderr 是黑洞）。"""
    tb = traceback.format_exc()
    _log(f"{title}:\n{tb}")
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is not None:
            box = QMessageBox(QMessageBox.Icon.Critical, "程序错误",
                              f"{title}，详情见 startup.log：\n\n{tb[-1200:]}")
            box.exec()
    except Exception:
        pass


def _install_hooks() -> None:
    def sys_hook(tp, val, tb):
        if issubclass(tp, KeyboardInterrupt):
            sys.__excepthook__(tp, val, tb)
            return
        _report("未捕获的异常")

    def thread_hook(args):
        if issubclass(args.exc_type, SystemExit):
            return
        _log(f"线程 {args.thread.name if args.thread else '?'} 未捕获异常：\n"
             + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))

    sys.excepthook = sys_hook
    threading.excepthook = thread_hook
    # 捕获原生层崩溃（访问冲突等），直接写入 fault.log
    try:
        fault_path = os.path.join(_base_dir(), "fault.log")
        fault_file = open(fault_path, "a", encoding="utf-8", errors="replace")
        fault_file.write(f"\n===== session {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
        fault_file.flush()
        faulthandler.enable(fault_file)
    except Exception:
        pass


def main():
    _log("=== launch start ===")
    _install_hooks()
    try:
        # 在导入 PySide6 之前强制软件渲染，避免在受限/无独显环境下探测显卡驱动
        os.environ.setdefault("QT_OPENGL", "software")
        os.environ.setdefault("QSG_RHI_BACKEND", "software")
        os.environ.setdefault("QT_QUICK_BACKEND", "software")

        _log("importing PySide6...")
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL, True)

        _log("importing MainWindow...")
        from app.ui.main_window import MainWindow

        _log("creating QApplication...")
        app = QApplication(sys.argv)
        app.setApplicationName("STEP 7 AI Agent")
        app.setOrganizationName("Step7AIAgent")

        _log("creating MainWindow...")
        window = MainWindow()
        _log("showing window...")
        window.show()
        _log("entering event loop...")
        sys.exit(app.exec())
    except Exception:
        _log("EXCEPTION:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
