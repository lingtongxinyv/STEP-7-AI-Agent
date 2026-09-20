# -*- coding: utf-8 -*-
"""后台线程对象：避免 LLM 调用、工具执行与连通性测试阻塞 Qt 界面。"""
from PySide6.QtCore import QObject, Slot, Signal

from app.agent.connectivity import test_connection


class ChatWorker(QObject):
    delta = Signal(str)
    status = Signal(str)
    tool = Signal(str, str)
    error = Signal(str)
    program = Signal(dict)
    scada = Signal(dict)
    finished = Signal()

    def __init__(self, assistant, text: str):
        super().__init__()
        self._assistant = assistant
        self._text = text

    @Slot()
    def run(self):
        def event(kind, *args):
            if kind == "delta":
                self.delta.emit(args[0])
            elif kind == "status":
                self.status.emit(args[0])
            elif kind == "tool":
                self.tool.emit(args[0], args[1])
            elif kind == "error":
                self.error.emit(args[0])
            elif kind == "program":
                self.program.emit(args[0])
            elif kind == "scada":
                self.scada.emit(args[0])

        try:
            self._assistant.chat(self._text, event)
        except Exception as e:  # 兜底，避免线程静默崩溃
            self.error.emit(f"对话处理异常：{e}")
        finally:
            self.finished.emit()


class ConnTestWorker(QObject):
    """模型连通性测试 worker：done 携带结构化结果 dict。"""

    done = Signal(dict)

    def __init__(self, llm_config: dict):
        super().__init__()
        self._llm = llm_config

    @Slot()
    def run(self):
        try:
            result = test_connection(self._llm)
        except Exception as e:
            result = {"ok": False, "stage": "service", "latency_ms": 0,
                      "message": f"测试异常：{e}"}
        self.done.emit(result)
