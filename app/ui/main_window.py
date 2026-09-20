# -*- coding: utf-8 -*-
"""
STEP 7 AI Agent 主窗口。

左侧：对话区（Markdown 渲染，支持流式输出）
右侧：PLC 面板（模拟/真机连接、变量监控、安全门禁）+ 程序面板（代码/IO表/导出）
"""
import threading

from PySide6.QtCore import (
    QEvent,
    Qt,
    QThread,
    QTimer,
    QObject,
    Signal,
    Slot,
)
from PySide6.QtGui import QGuiApplication, QTextCursor, QTextCharFormat, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.agent.assistant import Assistant
from app.agent.tools import ToolExecutor
from app.core.config import base_dir, cloud_presets, load_config, save_config
from app.programs.ladder import LadderWidget, build_ladder, export_awl_text
from app.plc.profiles import get_profile, profile_names
from app.ui.workers import ChatWorker, ConnTestWorker


# ---------------- 写操作跨线程确认 ----------------

class ConfirmBridge(QObject):
    """工作线程发起写请求，GUI 线程弹窗确认，工作线程阻塞等待结果。"""

    _request = Signal(str, str)

    def __init__(self):
        super().__init__()
        self._event = threading.Event()
        self._result = False
        # 跨线程自动使用队列连接，保证槽在 GUI 线程执行
        self._request.connect(self._on_request, Qt.ConnectionType.QueuedConnection)

    def ask(self, address: str, value: str) -> bool:
        self._event.clear()
        self._request.emit(address, value)
        self._event.wait(timeout=300)
        return self._result

    @Slot(str, str)
    def _on_request(self, address: str, value: str):
        btn = QMessageBox.warning(
            None,
            "PLC 写入确认",
            f"工具请求向 PLC 写入：\n\n    {address}  ←  {value}\n\n"
            "请核对地址与数值，确认执行？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        self._result = btn == QMessageBox.StandardButton.Yes
        self._event.set()


# ---------------- 对话面板 ----------------

class ChatPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._messages = []   # (role, markdown)
        self._stream_buf = None

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)

        self.input_box = QTextEdit()
        self.input_box.setPlaceholderText("输入你的问题或控制需求……（Enter 发送，Shift+Enter 换行）")
        self.input_box.setFixedHeight(72)
        self.input_box.installEventFilter(self)

        self.btn_send = QPushButton("发送")

        bottom = QHBoxLayout()
        bottom.addWidget(self.input_box, 1)
        bottom.addWidget(self.btn_send, 0, Qt.AlignmentFlag.AlignBottom)

        layout = QVBoxLayout(self)
        layout.addWidget(self.view, 1)
        layout.addLayout(bottom)

    def eventFilter(self, obj, event):
        if obj is self.input_box and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                self.btn_send.click()
                return True
        return super().eventFilter(obj, event)

    def add_message(self, role: str, text: str):
        self._messages.append((role, text))
        self._rebuild()

    def begin_stream(self):
        self._stream_buf = ""
        self._messages.append(("assistant", ""))
        self._rebuild()

    def append_stream(self, text: str):
        if self._stream_buf is None:
            self.begin_stream()
        self._stream_buf += text
        self._messages[-1] = ("assistant", self._stream_buf)
        self._rebuild()

    def end_stream(self):
        self._stream_buf = None

    def clear_all(self):
        self._messages = []
        self._stream_buf = None
        self._rebuild()

    def set_busy(self, busy: bool):
        self.btn_send.setEnabled(not busy)
        self.input_box.setEnabled(not busy)

    def current_input(self) -> str:
        return self.input_box.toPlainText().strip()

    def clear_input(self):
        self.input_box.clear()

    def _rebuild(self):
        parts = []
        for role, text in self._messages:
            title = "**🧑 我：**" if role == "user" else "**🤖 STEP 7 AI 助手：**"
            parts.append(f"{title}\n\n{text if text else '……'}")
        self.view.setMarkdown("\n\n---\n\n".join(parts))
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())


# ---------------- PLC 面板 ----------------

class PlcPanel(QWidget):
    def __init__(self, executor: ToolExecutor):
        super().__init__()
        self.executor = executor

        # ---- 模拟 PLC ----
        mock_box = QGroupBox("模拟 PLC（无硬件即可练习）")
        self.btn_mock = QPushButton("启动模拟PLC")
        self.lbl_mock = QLabel("模拟PLC：未启动")
        mlay = QVBoxLayout(mock_box)
        mlay.addWidget(self.btn_mock)
        mlay.addWidget(self.lbl_mock)

        # ---- 真机连接 ----
        real_box = QGroupBox("真机连接")
        self.cmb_profile = QComboBox()
        self.cmb_profile.addItems(profile_names())
        self.edt_host = QLineEdit()
        self.spn_rack = QSpinBox()
        self.spn_rack.setRange(0, 10)
        self.spn_slot = QSpinBox()
        self.spn_slot.setRange(0, 10)
        self.btn_connect = QPushButton("连接")
        self.lbl_conn = QLabel("PLC：未连接")

        form = QFormLayout()
        form.addRow("设备型号：", self.cmb_profile)
        form.addRow("IP 地址：", self.edt_host)
        form.addRow("Rack：", self.spn_rack)
        form.addRow("Slot：", self.spn_slot)
        rlay = QVBoxLayout(real_box)
        rlay.addLayout(form)
        rlay.addWidget(self.btn_connect)
        rlay.addWidget(self.lbl_conn)

        # ---- 安全门禁 ----
        safe_box = QGroupBox("安全")
        self.chk_write = QCheckBox("允许写入（默认只读；开启后每次写入仍会弹窗确认）")
        slay = QVBoxLayout(safe_box)
        slay.addWidget(self.chk_write)

        # ---- 变量监控 ----
        watch_box = QGroupBox("变量监控")
        self.tbl_tags = QTableWidget(0, 2)
        self.tbl_tags.setHorizontalHeaderLabels(["地址", "当前值"])
        self.tbl_tags.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.edt_new_tag = QLineEdit()
        self.edt_new_tag.setPlaceholderText("如 VW100 / Q0.0 / VD120")
        self.btn_add = QPushButton("添加")
        self.btn_remove = QPushButton("删除选中")
        self.chk_auto = QCheckBox("自动刷新(1秒)")
        add_row = QHBoxLayout()
        add_row.addWidget(self.edt_new_tag, 1)
        add_row.addWidget(self.btn_add)
        add_row.addWidget(self.btn_remove)

        self.edt_write_value = QLineEdit()
        self.edt_write_value.setPlaceholderText("写入值（布尔写 true/false）")
        self.btn_write = QPushButton("写入选中行")
        write_row = QHBoxLayout()
        write_row.addWidget(self.edt_write_value, 1)
        write_row.addWidget(self.btn_write)

        wlay = QVBoxLayout(watch_box)
        wlay.addWidget(self.tbl_tags, 1)
        wlay.addLayout(add_row)
        wlay.addWidget(self.chk_auto)
        wlay.addLayout(write_row)

        root = QVBoxLayout(self)
        root.addWidget(mock_box)
        root.addWidget(real_box)
        root.addWidget(safe_box)
        root.addWidget(watch_box, 1)

        # 定时器自动刷新
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(1000)

        self._fill_profile_defaults()

    # ---- 默认值 ----
    def _fill_profile_defaults(self):
        name = self.cmb_profile.currentText()
        pf = get_profile(name)
        self.edt_host.setText(pf["host"])
        self.spn_rack.setValue(pf["rack"])
        self.spn_slot.setValue(pf["slot"])

    def sync_from_config(self, cfg: dict):
        plc = cfg["plc"]
        idx = self.cmb_profile.findText(plc.get("profile", "S7-200 SMART"))
        if idx >= 0:
            self.cmb_profile.setCurrentIndex(idx)
        self.edt_host.setText(plc.get("host", self.edt_host.text()))
        self.spn_rack.setValue(int(plc.get("rack", 0)))
        self.spn_slot.setValue(int(plc.get("slot", 1)))
        self.chk_write.setChecked(bool(plc.get("allow_write", False)))

    # ---- 状态刷新 ----
    def refresh_status(self):
        self.lbl_mock.setText(
            f"模拟PLC：{'运行中' if self.executor.mock.running else '未启动'}"
        )
        if self.executor.connected:
            kind = "模拟PLC" if self.executor.is_mock_connection else "真机"
            self.lbl_conn.setText(f"PLC：已连接（{kind}）")
            self.btn_connect.setText("断开")
        else:
            self.lbl_conn.setText("PLC：未连接")
            self.btn_connect.setText("连接")
        self.btn_mock.setText(
            "停止模拟PLC" if self.executor.mock.running else "启动模拟PLC"
        )

    def refresh_values(self):
        if not self.executor.connected:
            for row in range(self.tbl_tags.rowCount()):
                self.tbl_tags.item(row, 1).setText("—")
            return
        for row in range(self.tbl_tags.rowCount()):
            addr = self.tbl_tags.item(row, 0).text()
            try:
                value = self.executor.driver.read(addr)
                self.tbl_tags.item(row, 1).setText(str(value))
            except Exception as e:
                self.tbl_tags.item(row, 1).setText(f"错误")

    # ---- 监控表操作 ----
    def add_tag(self, address: str = ""):
        address = address or self.edt_new_tag.text().strip()
        if not address:
            return
        row = self.tbl_tags.rowCount()
        self.tbl_tags.insertRow(row)
        self.tbl_tags.setItem(row, 0, QTableWidgetItem(address))
        self.tbl_tags.setItem(row, 1, QTableWidgetItem("—"))
        self.edt_new_tag.clear()
        self.refresh_values()

    def remove_selected(self):
        rows = sorted({i.row() for i in self.tbl_tags.selectedIndexes()}, reverse=True)
        for row in rows:
            self.tbl_tags.removeRow(row)

    def selected_address(self):
        rows = {i.row() for i in self.tbl_tags.selectedIndexes()}
        if len(rows) == 1:
            row = rows.pop()
            return self.tbl_tags.item(row, 0).text()
        return None


# ---------------- 程序面板 ----------------

class CodePanel(QWidget):
    def __init__(self):
        super().__init__()
        self._program = None

        self.lbl_title = QLabel("尚未生成程序。可在对话中描述需求，或要求“用模板生成”。")

        # 代码页
        self.code_view = QPlainTextEdit()
        self.code_view.setReadOnly(True)
        font = self.code_view.font()
        font.setFamily("Consolas, Courier New")
        self.code_view.setFont(font)

        # 梯形图页
        self.ladder = LadderWidget()
        ladder_scroll = QScrollArea()
        ladder_scroll.setWidgetResizable(True)
        ladder_scroll.setWidget(self.ladder)

        # IO 表页
        self.io_table = QTableWidget(0, 2)
        self.io_table.setHorizontalHeaderLabels(["地址", "说明"])
        self.io_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        # 说明页
        self.doc_view = QTextBrowser()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.code_view, "程序代码")
        self.tabs.addTab(ladder_scroll, "梯形图")
        self.tabs.addTab(self.io_table, "I/O 分配表")
        self.tabs.addTab(self.doc_view, "原理与导入")

        self.btn_copy = QPushButton("复制代码")
        self.btn_export = QPushButton("导出文件")
        self.btn_awl = QPushButton("导出AWL")
        self.btn_awl.setToolTip("导出 Micro/WIN SMART 可直接导入的 .awl 程序文件")
        self.btn_png = QPushButton("梯形图存PNG")
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_copy)
        btn_row.addWidget(self.btn_export)
        btn_row.addWidget(self.btn_awl)
        btn_row.addWidget(self.btn_png)
        btn_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.lbl_title)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(btn_row)

    def show_program(self, program: dict):
        self._program = program
        self.lbl_title.setText(
            f"{program['name']}（目标：{program['target']} · 语言：{program['language']}）"
        )
        self.code_view.setPlainText(program["code"])
        self.io_table.setRowCount(0)
        for addr, desc in program["io_table"]:
            row = self.io_table.rowCount()
            self.io_table.insertRow(row)
            self.io_table.setItem(row, 0, QTableWidgetItem(addr))
            self.io_table.setItem(row, 1, QTableWidgetItem(desc))
        self.doc_view.setMarkdown(
            f"**工作原理：**\n\n{program['explanation']}\n\n"
            f"**导入步骤：**\n\n{program['import_guide']}"
        )
        rungs = build_ladder(program)
        self.ladder.set_program(program["name"], rungs)
        is_stl = program["language"] == "STL"
        self.btn_awl.setEnabled(is_stl)
        self.btn_png.setEnabled(rungs is not None)

    def copy_code(self):
        if self._program:
            QGuiApplication.clipboard().setText(self._program["code"])

    def export_file(self):
        if not self._program:
            return
        ext = ".scl" if self._program["language"] == "SCL" else ".stl"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出程序", f"{self._program['key']}{ext}",
            f"程序文件 (*{ext});;所有文件 (*.*)",
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._program["code"])

    def export_awl(self):
        if not self._program or self._program["language"] != "STL":
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 AWL（Micro/WIN SMART 可导入）",
            f"{self._program['key']}.awl",
            "AWL 程序文件 (*.awl);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            # Micro/WIN SMART 读取 ANSI 编码，中文注释用 GBK 保存
            with open(path, "w", encoding="gbk", errors="replace") as f:
                f.write(export_awl_text(self._program))
            QMessageBox.information(
                self, "导出成功",
                f"已导出：{path}\n\n导入方法：Micro/WIN SMART 菜单"
                "“文件 > 导入”，选择该 .awl 文件即可。",
            )
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def export_ladder_png(self):
        if not self._program or not self.ladder.has_content():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出梯形图", f"{self._program['key']}_梯形图.png",
            "PNG 图片 (*.png);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            if self.ladder.grab().save(path, "PNG"):
                QMessageBox.information(self, "导出成功", f"已导出：{path}")
            else:
                QMessageBox.warning(self, "导出失败", "图片保存失败，请检查路径权限。")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))


# ---------------- MCGS 组态面板（独立同级面板） ----------------

class ScadaPanel(QWidget):
    """MCGS 组态设计助手独立面板。

    功能：
    1. MCGS 连接按钮：检测本机是否安装 MCGS（McgsPro/嵌入版/通用版），
       已安装则一键启动；未安装显示提示。
    2. 版本/协议下拉：McgsPro / 嵌入版 / 通用版 × PPI / Modbus / OPC
    3. 4 个素材 Tab（占满面板）：变量字典 / 设备通道 / 画面设计书 / 脚本
    4. 导出包：一键导出 7 个文件到目录
    """

    def __init__(self, tool_executor: ToolExecutor, config: dict):
        super().__init__()
        self._scada = None
        self.executor = tool_executor
        self.config = config

        # ========== 顶部：MCGS 连接区 ==========
        self.btn_connect_mcgs = QPushButton("🔌 连接 MCGS")
        self.btn_connect_mcgs.setToolTip("自动检测本机 MCGS 安装位置（注册表→快捷方式→全盘搜索）")
        self.lbl_mcgs_status = QLabel("未检测到 MCGS")
        self.lbl_mcgs_status.setStyleSheet("color: #999;")
        self.btn_start_mcgs = QPushButton("▶ 启动 MCGS")
        self.btn_start_mcgs.setEnabled(False)
        self.btn_start_mcgs.setToolTip("启动已安装的 MCGS 组态软件")
        self.lbl_mcgs_path = QLabel("")
        self.lbl_mcgs_path.setStyleSheet("color: #1a7f37;")
        self.mcgs_exe_path = None

        conn_row = QHBoxLayout()
        conn_row.addWidget(self.btn_connect_mcgs)
        conn_row.addWidget(self.lbl_mcgs_status)
        conn_row.addWidget(self.btn_start_mcgs)
        conn_row.addWidget(self.lbl_mcgs_path, 1)

        # ========== 中部：生成控制条 ==========
        self.cmb_version = QComboBox()
        self.cmb_version.addItems(["McgsPro", "嵌入版", "通用版"])
        self.cmb_protocol = QComboBox()
        self.cmb_protocol.addItems(["PPI", "Modbus", "OPC"])
        self.btn_generate = QPushButton("⚡ 生成组态素材")
        self.btn_generate.setToolTip("按当前版本/协议，用默认工艺描述生成组态素材")
        self.btn_generate.setStyleSheet(
            "QPushButton{background:#1a7f37;color:white;padding:6px 16px;font-weight:bold;}"
            "QPushButton:hover{background:#15662b;}"
        )
        self.btn_export = QPushButton("📦 导出包")
        self.btn_export.setToolTip("将当前素材导出为 7 个文件到指定目录")
        self.btn_auto_write = QPushButton("🔄 写入 MCGS")
        self.btn_auto_write.setToolTip("自动写入 MCGS（需先启动 MCGS，UI 自动化）")
        self.btn_auto_write.setStyleSheet(
            "QPushButton{background:#0969da;color:white;padding:6px 16px;font-weight:bold;}"
            "QPushButton:hover{background:#0550ae;}"
        )

        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(QLabel("版本"))
        ctrl_row.addWidget(self.cmb_version)
        ctrl_row.addWidget(QLabel("协议"))
        ctrl_row.addWidget(self.cmb_protocol)
        ctrl_row.addStretch(1)
        ctrl_row.addWidget(self.btn_generate)
        ctrl_row.addWidget(self.btn_export)
        ctrl_row.addWidget(self.btn_auto_write)

        # ========== 自动化进度条（默认隐藏） ==========
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 3)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v/3  %p%")
        self.progress_bar.setVisible(False)
        self.lbl_progress = QLabel("")
        self.lbl_progress.setStyleSheet("color: #0969da; font-weight: bold;")

        progress_row = QHBoxLayout()
        progress_row.addWidget(QLabel("自动化进度："))
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.lbl_progress)
        progress_container = QWidget()
        progress_container.setLayout(progress_row)
        progress_container.setVisible(False)
        self._progress_container = progress_container

        # ========== 4 个素材 Tab（占满剩余空间） ==========
        self.material_tabs = QTabWidget()

        # --- Tab 1：变量字典 ---
        var_tab = QWidget()
        self.tbl_vars = QTableWidget(0, 6)
        self.tbl_vars.setHorizontalHeaderLabels(
            ["变量名", "类型", "地址", "数据类型", "读写", "说明"]
        )
        self.tbl_vars.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.tbl_vars.verticalHeader().setDefaultSectionSize(32)
        btn_copy_vars = QPushButton("📋 复制 CSV")
        btn_copy_vars.clicked.connect(self._copy_vars_csv)
        var_lay = QVBoxLayout(var_tab)
        var_lay.addWidget(self.tbl_vars, 1)
        var_btn_row = QHBoxLayout()
        var_btn_row.addStretch(1)
        var_btn_row.addWidget(btn_copy_vars)
        var_lay.addLayout(var_btn_row)
        self.material_tabs.addTab(var_tab, "📋 变量字典")

        # --- Tab 2：设备通道 CSV ---
        csv_tab = QWidget()
        self.txt_csv = QPlainTextEdit()
        self.txt_csv.setReadOnly(True)
        font = self.txt_csv.font()
        font.setFamily("Consolas, Courier New")
        font.setPointSize(font.pointSize() + 1)
        self.txt_csv.setFont(font)
        btn_copy_csv = QPushButton("📋 复制 CSV")
        btn_copy_csv.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.txt_csv.toPlainText())
        )
        csv_lay = QVBoxLayout(csv_tab)
        csv_lay.addWidget(self.txt_csv, 1)
        csv_btn_row = QHBoxLayout()
        csv_btn_row.addStretch(1)
        csv_btn_row.addWidget(btn_copy_csv)
        csv_lay.addLayout(csv_btn_row)
        self.material_tabs.addTab(csv_tab, "🔌 设备通道 CSV")

        # --- Tab 3：画面设计书 ---
        screen_tab = QWidget()
        self.txt_screen = QTextBrowser()
        self.txt_screen.setOpenExternalLinks(False)
        btn_copy_screen = QPushButton("📋 复制设计书")
        btn_copy_screen.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.txt_screen.toPlainText())
        )
        screen_lay = QVBoxLayout(screen_tab)
        screen_lay.addWidget(self.txt_screen, 1)
        screen_btn_row = QHBoxLayout()
        screen_btn_row.addStretch(1)
        screen_btn_row.addWidget(btn_copy_screen)
        screen_lay.addLayout(screen_btn_row)
        self.material_tabs.addTab(screen_tab, "🖼 画面设计书")

        # --- Tab 4：McgsScript 脚本 ---
        script_tab = QWidget()
        self.txt_script = QPlainTextEdit()
        self.txt_script.setReadOnly(True)
        sc_font = self.txt_script.font()
        sc_font.setFamily("Consolas, Courier New")
        sc_font.setPointSize(sc_font.pointSize() + 1)
        self.txt_script.setFont(sc_font)
        btn_copy_script = QPushButton("📋 复制脚本")
        btn_copy_script.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.txt_script.toPlainText())
        )
        script_lay = QVBoxLayout(script_tab)
        script_lay.addWidget(self.txt_script, 1)
        script_btn_row = QHBoxLayout()
        script_btn_row.addStretch(1)
        script_btn_row.addWidget(btn_copy_script)
        script_lay.addLayout(script_btn_row)
        self.material_tabs.addTab(script_tab, "📝 McgsScript 脚本")

        # ========== 全局布局 ==========
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addLayout(conn_row)
        layout.addLayout(ctrl_row)
        layout.addWidget(self._progress_container)
        layout.addWidget(self.material_tabs, 1)

        # ========== 信号 ==========
        self.btn_connect_mcgs.clicked.connect(self._connect_mcgs)
        self.btn_start_mcgs.clicked.connect(self._start_mcgs)
        self.btn_generate.clicked.connect(self._generate_now)
        self.btn_export.clicked.connect(self.export_package)
        self.btn_auto_write.clicked.connect(self._auto_write_to_mcgs)

        # ========== 初始化版本/协议下拉 ==========
        mcgs_cfg = config.get("mcgs", {})
        vi = self.cmb_version.findText(mcgs_cfg.get("version", "McgsPro"))
        if vi >= 0:
            self.cmb_version.setCurrentIndex(vi)
        pi = self.cmb_protocol.findText(mcgs_cfg.get("protocol", "PPI"))
        if pi >= 0:
            self.cmb_protocol.setCurrentIndex(pi)

        # ========== 首次自动检测 MCGS ==========
        self._connect_mcgs()

    # ---------- MCGS 连接按钮 ----------
    def _connect_mcgs(self):
        """分层检测本机 MCGS 安装路径（注册表 > 快捷方式 > 全盘搜索）。"""
        from app.scada import find_mcgs_installed
        self.lbl_mcgs_status.setText("检测中……")
        self.lbl_mcgs_status.setStyleSheet("color: #999;")
        self.lbl_mcgs_path.setText("")
        QGuiApplication.processEvents()

        ver, path = find_mcgs_installed()

        if ver and path:
            self.mcgs_exe_path = path
            self.lbl_mcgs_status.setText(f"✓ {ver}")
            self.lbl_mcgs_status.setStyleSheet("color: #1a7f37; font-weight: bold;")
            self.lbl_mcgs_path.setText(f"📁 {path}")
            self.btn_start_mcgs.setEnabled(True)
            idx = self.cmb_version.findText(ver)
            if idx >= 0:
                self.cmb_version.setCurrentIndex(idx)
        else:
            self.mcgs_exe_path = None
            self.lbl_mcgs_status.setText("✗ 未检测到")
            self.lbl_mcgs_status.setStyleSheet("color: #c62828;")
            self.lbl_mcgs_path.setText(
                "已扫描注册表/快捷方式/全盘，未找到 MCGS。"
                "请确认已安装，或手动选择版本后点生成。"
            )
            self.btn_start_mcgs.setEnabled(False)

    def _manual_locate_mcgs(self):
        """用户通过文件对话框手动选择 MCGS exe 路径。"""
        import os
        from app.scada.mcgs_knowledge import _detect_version_from_exe_path
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 MCGS 组态软件", "",
            "可执行文件 (*.exe);;所有文件 (*.*)",
        )
        if not path:
            return
        if not os.path.isfile(path):
            QMessageBox.warning(self, "路径无效", f"文件不存在：\n{path}")
            return
        ver = _detect_version_from_exe_path(path)
        self.mcgs_exe_path = path
        self.lbl_mcgs_status.setText(f"✓ {ver}")
        self.lbl_mcgs_status.setStyleSheet("color: #1a7f37; font-weight: bold;")
        self.lbl_mcgs_path.setText(f"📁 {path}（手动定位）")
        self.btn_start_mcgs.setEnabled(True)
        idx = self.cmb_version.findText(ver)
        if idx >= 0:
            self.cmb_version.setCurrentIndex(idx)

    def _start_mcgs(self):
        """启动 MCGS 组态软件（独立进程）。"""
        if not self.mcgs_exe_path:
            return
        import subprocess
        try:
            subprocess.Popen(
                [self.mcgs_exe_path],
                cwd=self.mcgs_exe_path.rsplit("\\", 1)[0],
            )
            self.lbl_mcgs_version.setText(
                f"已启动 {self.lbl_mcgs_status.text().replace('已检测到 ', '')}，"
                f"请在 MCGS 组态环境中打开/新建工程。"
            )
        except Exception as e:
            QMessageBox.warning(self, "启动失败", str(e))

    # ---------- 生成组态 ----------
    def _generate_now(self):
        """按当前版本/协议生成组态素材，自动刷新 4 个 Tab。"""
        version = self.cmb_version.currentText()
        protocol = self.cmb_protocol.currentText()
        self.btn_generate.setEnabled(False)
        self.btn_generate.setText("生成中……")
        QGuiApplication.processEvents()
        try:
            self.executor.generate_scada(
                craft_desc="电机启停控制，带运行指示与故障报警",
                mcgs_version=version,
                protocol=protocol,
            )
        except Exception as e:
            QMessageBox.warning(self, "生成失败", str(e))
        finally:
            self.btn_generate.setEnabled(True)
            self.btn_generate.setText("⚡ 生成组态素材")

    # ---------- 渲染 ----------
    def show_scada(self, scada: dict):
        """渲染 scada dict 到 4 个素材 Tab。"""
        self._scada = scada
        name = scada.get("name", "MCGS组态")
        version = scada.get("mcgs_version", "McgsPro")
        protocol = scada.get("protocol", "PPI")
        vi = self.cmb_version.findText(version)
        if vi >= 0:
            self.cmb_version.setCurrentIndex(vi)
        pi = self.cmb_protocol.findText(protocol)
        if pi >= 0:
            self.cmb_protocol.setCurrentIndex(pi)

        # 变量字典表
        self.tbl_vars.setRowCount(0)
        for v in scada["variables"]:
            row = self.tbl_vars.rowCount()
            self.tbl_vars.insertRow(row)
            rw = "只读" if v.get("read_only") else "读写"
            cells = [v["name"], v.get("var_type", ""), v["address"],
                     v.get("dtype", ""), rw, v.get("comment", "")]
            for col, text in enumerate(cells):
                self.tbl_vars.setItem(row, col, QTableWidgetItem(str(text)))

        # 通道 CSV
        self.txt_csv.setPlainText(scada["device_channels_csv"])

        # 画面设计书 + SVG 源码（QTextBrowser 不直接渲染 SVG，降级为代码块）
        design_md = scada["screen_design"]["design_text"]
        svg = scada["screen_design"]["svg_preview"]
        self.txt_screen.setMarkdown(design_md)
        self.txt_screen.append(
            "\n\n---\n\n**SVG 布局示意（源码，可另存为 .svg 浏览）：**\n\n```svg\n"
            + svg + "\n```"
        )

        # 脚本
        self.txt_script.setPlainText(scada["script"])

        # 自动切到变量字典 Tab
        self.material_tabs.setCurrentIndex(0)

        # 弹窗提示（ScadaPanel 没有状态栏，用消息框通知）
        QMessageBox.information(
            self, "✓ 组态素材已生成",
            f"{name}\n版本：{version} · 协议：{protocol}\n"
            f"变量数：{len(scada['variables'])}\n\n"
            f"请按顺序操作：\n"
            f"  ① 切到「设备通道 CSV」Tab，复制后到 MCGS 设备窗口右键「设备信息导入」\n"
            f"  ② 切到「变量字典」Tab，对照在 MCGS 实时数据库逐条新建数据对象\n"
            f"  ③ 切到「McgsScript 脚本」Tab，复制粘贴到 MCGS 脚本编辑器\n"
            f"  ④ 或点右上角「📦 导出包」一键导出 7 个文件到目录",
        )

    # ---------- 导出 ----------
    def export_package(self):
        if not self._scada:
            QMessageBox.information(self, "提示", "尚未生成 MCGS 组态，无内容可导出。")
            return
        target = QFileDialog.getExistingDirectory(
            self, "选择导出目录", f"{self._scada['name']}_导出包"
        )
        if not target:
            return
        try:
            from app.scada import build_export_package
            files = build_export_package(self._scada, target)
            names = "\n".join(f"- {n}" for n in files)
            QMessageBox.information(
                self, "导出成功",
                f"已导出 {len(files)} 个文件到：\n{target}\n\n{names}\n\n"
                "导入顺序请查阅目录中的 README.txt。",
            )
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _copy_vars_csv(self):
        if not self._scada:
            return
        import csv, io
        out = io.StringIO()
        out.write("\ufeff")
        writer = csv.writer(out)
        writer.writerow(["变量名", "类型", "地址", "数据类型", "初值", "读写", "说明"])
        for v in self._scada["variables"]:
            rw = "只读" if v.get("read_only") else "读写"
            writer.writerow([v["name"], v.get("var_type", ""), v["address"],
                             v.get("dtype", ""), v.get("init", "0"), rw, v.get("comment", "")])
        QGuiApplication.clipboard().setText(out.getvalue())

    # ---------- 自动写入 MCGS ----------
    def _auto_write_to_mcgs(self):
        """用 UI 自动化把当前 scada 写入 MCGS 工程。

        在后台线程执行，通过信号更新进度。
        """
        if not self._scada:
            QMessageBox.information(self, "提示", "尚未生成 MCGS 组态素材，先点「⚡ 生成组态素材」。")
            return

        from PySide6.QtCore import QThread, Signal

        # 确认对话框
        btn = QMessageBox.question(
            self, "🔄 自动写入 MCGS",
            "将通过 UI 自动化把组态素材写入 MCGS 工程，包含 3 个步骤：\n\n"
            "  ① 启动/激活 MCGS 组态环境\n"
            "  ② 自动导入设备通道 CSV\n"
            "  ③ 自动粘贴 McgsScript 脚本\n\n"
            "⚠ 数据对象（变量）创建无法自动化，需手动在实时数据库新建。\n\n"
            "请确保 MCGS 组态环境已打开（或允许自动启动），然后点「是」继续。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if btn != QMessageBox.StandardButton.Yes:
            return

        # 创建后台线程执行
        class WriteWorker(QThread):
            progress = Signal(int, str)
            finished_all = Signal(list)  # List[StepResult]

            def __init__(self, scada, mcgs_path):
                super().__init__()
                self.scada = scada
                self.mcgs_path = mcgs_path

            def run(self):
                try:
                    from app.scada import MCGSAutoWriter
                    writer = MCGSAutoWriter(self.scada, self.mcgs_path)
                    results = writer.run(
                        on_progress=lambda s, m: self.progress.emit(s, m)
                    )
                    self.finished_all.emit(results)
                except Exception as e:
                    # 构造一个失败的结果
                    from app.scada.mcgs_auto_writer import StepResult
                    self.finished_all.emit([StepResult(0, "执行异常", False, message=str(e))])

        self._progress_container.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_progress.setText("准备中……")
        self.btn_auto_write.setEnabled(False)

        self._write_worker = WriteWorker(self._scada, self.mcgs_exe_path)
        self._write_worker.progress.connect(self._on_write_progress)
        self._write_worker.finished_all.connect(self._on_write_finished)
        self._write_worker.start()

    def _on_write_progress(self, step: int, message: str):
        self.progress_bar.setValue(step)
        self.lbl_progress.setText(f"步骤 {step}/3：{message}")

    def _on_write_finished(self, results: list):
        self.btn_auto_write.setEnabled(True)
        self.progress_bar.setValue(3)
        self.lbl_progress.setText("自动化完成")

        # 汇总结果
        success_count = sum(1 for r in results if r.success)
        manual_count = sum(1 for r in results if r.manual)
        fail_count = sum(1 for r in results if not r.success and not r.manual)

        lines = ["📋 自动化执行结果：\n"]
        for r in results:
            icon = "✅" if r.success else ("✍️" if r.manual else "❌")
            status = "成功" if r.success else ("需手动" if r.manual else "失败")
            lines.append(f"  {icon} Step {r.step}: {r.name} — {status}")
            if r.message:
                lines.append(f"     {r.message}")

        summary = f"\n成功 {success_count} / 需手动 {manual_count} / 失败 {fail_count}"
        lines.append(summary)

        if fail_count > 0:
            QMessageBox.warning(self, "🔄 自动写入完成（部分失败）", "\n".join(lines))
        elif manual_count > 0:
            QMessageBox.information(self, "🔄 自动写入完成", "\n".join(lines))
        else:
            QMessageBox.information(self, "🔄 自动写入成功", "\n".join(lines))

        # 3 秒后隐藏进度条
        from PySide6.QtCore import QTimer
        QTimer.singleShot(3000, lambda: self._progress_container.setVisible(False))


# ---------------- 设置对话框 ----------------

class SettingsDialog(QWidget):
    def __init__(self, config: dict):
        super().__init__()
        self.setWindowTitle("模型设置")
        self.config = config
        llm = config["llm"]

        self.rd_ollama = QRadioButton("本地 Ollama")
        self.rd_cloud = QRadioButton("云端 OpenAI 兼容接口")
        if llm["provider"] == "cloud":
            self.rd_cloud.setChecked(True)
        else:
            self.rd_ollama.setChecked(True)

        # Ollama
        ollama_box = QGroupBox("Ollama 设置")
        self.ollama_url = QLineEdit(llm["ollama"]["base_url"])
        self.ollama_model = QLineEdit(llm["ollama"]["model"])
        oform = QFormLayout(ollama_box)
        oform.addRow("接口地址：", self.ollama_url)
        oform.addRow("模型名称：", self.ollama_model)

        # 云端
        cloud_box = QGroupBox("云端设置")
        self.cmb_preset = QComboBox()
        self.cmb_preset.addItem("自定义")
        self.cmb_preset.addItems(list(cloud_presets().keys()))
        self.cloud_url = QLineEdit(llm["cloud"]["base_url"])
        self.cloud_model = QLineEdit(llm["cloud"]["model"])
        self.cloud_key = QLineEdit(llm["cloud"].get("api_key", ""))
        self.cloud_key.setEchoMode(QLineEdit.EchoMode.Password)
        cform = QFormLayout(cloud_box)
        cform.addRow("快捷预设：", self.cmb_preset)
        cform.addRow("接口地址：", self.cloud_url)
        cform.addRow("模型名称：", self.cloud_model)
        cform.addRow("API Key：", self.cloud_key)

        # 其他
        other_box = QGroupBox("生成参数")
        self.spn_temp = QDoubleSpinBox()
        self.spn_temp.setRange(0.0, 1.0)
        self.spn_temp.setSingleStep(0.1)
        self.spn_temp.setValue(float(llm.get("temperature", 0.3)))
        self.spn_timeout = QSpinBox()
        self.spn_timeout.setRange(10, 600)
        self.spn_timeout.setValue(int(llm.get("timeout", 120)))
        eform = QFormLayout(other_box)
        eform.addRow("温度：", self.spn_temp)
        eform.addRow("超时(秒)：", self.spn_timeout)

        self.btn_save = QPushButton("保存")
        self.btn_cancel = QPushButton("取消")

        # 连通性测试（使用对话框当前填写值，无需先保存）
        self.btn_test = QPushButton("测试连通性")
        self.lbl_test_result = QLabel("")
        self.lbl_test_result.setWordWrap(True)
        self.lbl_test_result.setStyleSheet("color: #555;")
        test_row = QHBoxLayout()
        test_row.addWidget(self.btn_test)
        test_row.addWidget(self.lbl_test_result, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(self.btn_save)
        btns.addWidget(self.btn_cancel)

        layout = QVBoxLayout(self)
        layout.addWidget(self.rd_ollama)
        layout.addWidget(ollama_box)
        layout.addWidget(self.rd_cloud)
        layout.addWidget(cloud_box)
        layout.addWidget(other_box)
        layout.addLayout(test_row)
        layout.addLayout(btns)
        self.resize(520, 660)

        self._test_thread = None
        self._test_worker = None
        self.btn_test.clicked.connect(self.test_now)

    def _collect_llm(self) -> dict:
        """收集对话框当前填写的 llm 配置（测试无需先保存）。"""
        return {
            "provider": "cloud" if self.rd_cloud.isChecked() else "ollama",
            "ollama": {
                "base_url": self.ollama_url.text().strip(),
                "model": self.ollama_model.text().strip(),
            },
            "cloud": {
                "base_url": self.cloud_url.text().strip(),
                "model": self.cloud_model.text().strip(),
                "api_key": self.cloud_key.text().strip(),
            },
        }

    def test_now(self):
        if self._test_thread is not None:
            return
        self.btn_test.setEnabled(False)
        self.lbl_test_result.setStyleSheet("color: #555;")
        self.lbl_test_result.setText("正在测试（连通 → 模型 → 推理），请稍候……")

        thread = QThread()
        worker = ConnTestWorker(self._collect_llm())
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._show_test_result)
        thread.start()
        self._test_thread = thread
        self._test_worker = worker

    def _show_test_result(self, result: dict):
        self.lbl_test_result.setStyleSheet(
            "color: #1a7f37;" if result["ok"] else "color: #c62828;"
        )
        self.lbl_test_result.setText(result["message"])
        self.btn_test.setEnabled(True)
        if self._test_thread is not None:
            self._test_thread.quit()
            self._test_thread.wait()
            self._test_worker.deleteLater()
            self._test_thread = None
            self._test_worker = None

    def closeEvent(self, event):
        # 关闭对话框时回收测试线程，避免悬挂
        if self._test_thread is not None:
            self._test_thread.quit()
            self._test_thread.wait(3000)
            if self._test_worker is not None:
                self._test_worker.deleteLater()
            self._test_thread = None
        super().closeEvent(event)

    def apply_preset(self):
        name = self.cmb_preset.currentText()
        presets = cloud_presets()
        if name in presets:
            url, model = presets[name]
            self.cloud_url.setText(url)
            self.cloud_model.setText(model)

    def result_config(self) -> dict:
        cfg = self.config
        cfg["llm"]["provider"] = "cloud" if self.rd_cloud.isChecked() else "ollama"
        cfg["llm"]["ollama"]["base_url"] = self.ollama_url.text().strip()
        cfg["llm"]["ollama"]["model"] = self.ollama_model.text().strip()
        cfg["llm"]["cloud"]["base_url"] = self.cloud_url.text().strip()
        cfg["llm"]["cloud"]["model"] = self.cloud_model.text().strip()
        cfg["llm"]["cloud"]["api_key"] = self.cloud_key.text().strip()
        cfg["llm"]["temperature"] = self.spn_temp.value()
        cfg["llm"]["timeout"] = self.spn_timeout.value()
        return cfg


# ---------------- 主窗口 ----------------

class MainWindow(QMainWindow):
    # 程序就绪信号：工具在工作线程产出程序后，经队列连接回到 GUI 线程刷新
    program_ready = Signal(dict)
    # MCGS 组态就绪信号
    scada_ready = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("STEP 7 AI Agent  |  MCGS 组态助手")
        self.resize(1280, 820)

        self.config = load_config()
        self.executor = ToolExecutor()
        self.assistant = Assistant(self.config, self.executor)

        self.chat = ChatPanel()
        self.plc_panel = PlcPanel(self.executor)
        self.code_panel = CodePanel()
        self.scada_panel = ScadaPanel(self.executor, self.config)
        self.plc_panel.sync_from_config(self.config)
        self.executor.allow_write = self.config["plc"].get("allow_write", False)

        # ---- 顶层 Tab：STEP 7 AI Agent 与 MCGS 组态助手同级 ----
        self.top_tabs = QTabWidget()

        # Tab 0：STEP 7 AI Agent（对话 + PLC/程序面板）
        step7_tabs = QTabWidget()
        step7_tabs.addTab(self.plc_panel, "PLC")
        step7_tabs.addTab(self.code_panel, "程序")
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.chat)
        splitter.addWidget(step7_tabs)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.top_tabs.addTab(splitter, "STEP 7 AI Agent")

        # Tab 1：MCGS 组态助手（独立面板）
        self.top_tabs.addTab(self.scada_panel, "MCGS 组态助手")

        # Tab 2：运行日志（应用内实时查看）
        self._build_log_tab()
        self.top_tabs.addTab(self._log_tab_widget, "📋 运行日志")

        self.setCentralWidget(self.top_tabs)

        # ---- 注册日志信号桥（让所有 logging 记录实时流入 UI） ----
        try:
            from app.core.logger import QtLogEmitter, set_log_emitter, tail_log
            self._log_emitter = QtLogEmitter()
            set_log_emitter(self._log_emitter)
            self._log_emitter.log_record.connect(self._on_log_record)
            # 先加载历史
            for line in tail_log(200):
                self.txt_log.append(line.rstrip())
        except Exception:
            pass

        # ---- 跨线程写确认 ----
        self._confirm_bridge = ConfirmBridge()
        self.executor.confirm_write = self._confirm_write
        self.executor.on_connection_changed = self._on_connection_changed
        # 程序刷新统一走信号
        self.program_ready.connect(self.code_panel.show_program)
        self.executor.on_program_generated = self.program_ready.emit
        # MCGS 组态刷新走信号 → ScadaPanel
        self.scada_ready.connect(self.scada_panel.show_scada)
        self.executor.on_scada_generated = self.scada_ready.emit

        # ---- 信号连接 ----
        self.chat.btn_send.clicked.connect(self._send_message)
        self.plc_panel.btn_mock.clicked.connect(self._toggle_mock)
        self.plc_panel.btn_connect.clicked.connect(self._toggle_connect)
        self.plc_panel.cmb_profile.currentIndexChanged.connect(
            self.plc_panel._fill_profile_defaults
        )
        self.plc_panel.btn_add.clicked.connect(lambda: self.plc_panel.add_tag())
        self.plc_panel.btn_remove.clicked.connect(self.plc_panel.remove_selected)
        self.plc_panel.btn_write.clicked.connect(self._write_selected)
        self.plc_panel.chk_auto.toggled.connect(self._toggle_auto_poll)
        self.plc_panel.poll_timer.timeout.connect(self.plc_panel.refresh_values)
        self.plc_panel.chk_write.toggled.connect(self._toggle_allow_write)
        self.code_panel.btn_copy.clicked.connect(self.code_panel.copy_code)
        self.code_panel.btn_export.clicked.connect(self.code_panel.export_file)
        self.code_panel.btn_awl.clicked.connect(self.code_panel.export_awl)
        self.code_panel.btn_png.clicked.connect(self.code_panel.export_ladder_png)

        # 工具栏：模式切换
        toolbar = self.addToolBar("主工具栏")
        toolbar.addWidget(QLabel("模式： "))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("工程模式", "engineering")
        self.cmb_mode.addItem("学习模式", "learning")
        if self.config.get("mode") == "learning":
            self.cmb_mode.setCurrentIndex(1)
        self.cmb_mode.currentIndexChanged.connect(self._toggle_mode)
        toolbar.addWidget(self.cmb_mode)
        toolbar.addSeparator()
        act_test = toolbar.addAction("测试连接")
        act_test.triggered.connect(self._test_current_connection)
        act_settings = toolbar.addAction("模型设置")
        act_settings.triggered.connect(self._open_settings)
        act_clear = toolbar.addAction("清空对话")
        act_clear.triggered.connect(self._clear_chat)
        act_scada = toolbar.addAction("MCGS 组态")
        act_scada.triggered.connect(self._open_scada_dialog)
        act_about = toolbar.addAction("关于")
        act_about.triggered.connect(self._show_about)

        self._thread = None
        self._worker = None
        self._conn_thread = None
        self._conn_worker = None
        self._settings_dialog = None

        self.plc_panel.refresh_status()
        self._welcome()

    # ---------- 欢迎语 ----------
    def _welcome(self):
        self.chat.add_message(
            "assistant",
            "你好！我是 **STEP 7 AI 助手**，可以帮你：\n\n"
            "1. 设计与编写西门子 PLC 程序（S7-200 SMART / S7-1200/1500 等）；\n"
            "2. 连接 PLC 读写变量、分析状态；\n"
            "3. 对不明确的需求向你提问、给出提示与建议。\n\n"
            "**快速开始**：你现在没有硬件也没关系，在右侧 **PLC 面板点击“启动模拟PLC”**，"
            "然后就可以对我说：\n\n"
            "- “用模板生成一个星三角降压启动程序”\n"
            "- “读取 VW100 的产量值”\n"
            "- “电机正反转怎么设计？”（可切换顶部的**学习模式**让我引导你思考）",
        )

    # ---------- 模型连通性测试（工具栏，测试已生效配置） ----------
    def _test_current_connection(self):
        if self._conn_thread is not None:
            return
        self.statusBar().showMessage("正在测试模型连接……")

        thread = QThread()
        worker = ConnTestWorker(self.config["llm"])
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_conn_test_done)
        thread.start()
        self._conn_thread = thread
        self._conn_worker = worker

    def _on_conn_test_done(self, result: dict):
        self.statusBar().showMessage(result["message"], 8000)
        if result["ok"]:
            QMessageBox.information(self, "模型连接正常", result["message"])
        else:
            QMessageBox.warning(self, "模型连接失败", result["message"])
        if self._conn_thread is not None:
            self._conn_thread.quit()
            self._conn_thread.wait()
            self._conn_worker.deleteLater()
            self._conn_thread = None
            self._conn_worker = None

    # ---------- 发送消息 ----------
    def _send_message(self):
        text = self.chat.current_input()
        if not text or self._thread is not None:
            return
        self.chat.clear_input()
        self.chat.add_message("user", text)
        self.chat.begin_stream()
        self.chat.set_busy(True)
        self.statusBar().showMessage("正在思考……")

        self._thread = QThread()
        self._worker = ChatWorker(self.assistant, text)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.delta.connect(self.chat.append_stream)
        self._worker.status.connect(lambda s: self.statusBar().showMessage(s))
        self._worker.tool.connect(self._on_tool_event)
        self._worker.error.connect(self._on_error)
        self._worker.program.connect(self.code_panel.show_program)
        self._worker.scada.connect(self.scada_panel.show_scada)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def _on_finished(self):
        self.chat.end_stream()
        self.chat.set_busy(False)
        self.statusBar().clearMessage()
        self.plc_panel.refresh_status()
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None

    def _on_error(self, text: str):
        self.chat.append_stream(f"\n\n> ⚠️ **错误：** {text}")

    def _on_tool_event(self, name: str, args: str):
        self.statusBar().showMessage(f"调用工具 {name} {args}")

    # ---------- 连接回调 ----------
    def _on_connection_changed(self):
        self.plc_panel.refresh_status()

    # ---------- PLC 面板动作 ----------
    def _toggle_mock(self):
        if self.executor.mock.running:
            # 若正连着模拟PLC先断开
            if self.executor.connected and self.executor.is_mock_connection:
                self.executor.driver.disconnect()
            self.executor.mock.stop()
        else:
            try:
                self.executor.mock.start()
            except Exception as e:
                QMessageBox.critical(self, "错误", str(e))
        self.plc_panel.refresh_status()

    def _toggle_connect(self):
        if self.executor.connected:
            self.executor.driver.disconnect()
            self.plc_panel.refresh_status()
            return
        use_mock = self.executor.mock.running
        if use_mock:
            result = self.executor.connect_plc(use_mock=True)
        else:
            result = self.executor.connect_plc(
                use_mock=False,
                profile=self.plc_panel.cmb_profile.currentText(),
                host=self.plc_panel.edt_host.text().strip(),
                rack=self.plc_panel.spn_rack.value(),
                slot=self.plc_panel.spn_slot.value(),
            )
        self.statusBar().showMessage(result, 5000)
        self.plc_panel.refresh_status()
        self.plc_panel.refresh_values()
        self._persist_plc_config()

    def _write_selected(self):
        address = self.plc_panel.selected_address()
        value = self.plc_panel.edt_write_value.text().strip()
        if not address or value == "":
            QMessageBox.information(self, "提示", "请选中一行并填写写入值。")
            return
        result = self.executor.write_tag(address, value)
        self.statusBar().showMessage(result, 5000)
        self.plc_panel.refresh_values()

    def _toggle_auto_poll(self, checked: bool):
        if checked:
            self.plc_panel.poll_timer.start()
        else:
            self.plc_panel.poll_timer.stop()

    def _toggle_allow_write(self, checked: bool):
        self.executor.allow_write = checked
        self.config["plc"]["allow_write"] = checked
        save_config(self.config)

    # ---------- 模式 / 设置 ----------
    def _toggle_mode(self, _index: int):
        mode = self.cmb_mode.currentData()
        self.config["mode"] = mode

    def _open_settings(self):
        dlg = SettingsDialog(self.config)
        dlg.btn_cancel.clicked.connect(dlg.close)
        dlg.cmb_preset.currentIndexChanged.connect(dlg.apply_preset)

        def _save():
            self.config = dlg.result_config()
            save_config(self.config)
            self.assistant.update_config(self.config)
            self._persist_plc_config()
            dlg.close()

        dlg.btn_save.clicked.connect(_save)
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg.show()

    def _clear_chat(self):
        self.chat.clear_all()
        self.assistant.reset()
        self._welcome()

    def _show_about(self):
        QMessageBox.information(
            self,
            "关于",
            "STEP 7 AI Agent\n\n"
            "西门子 S7 系列 PLC 的 AI 编程与通信助手\n"
            "支持 S7-200 SMART / S7-1200/1500 / S7-300/400\n"
            "模型后端：Ollama 本地 / OpenAI 兼容云端\n\n"
            "MCGS 组态设计助手：派生变量字典/通道CSV/画面设计书/McgsScript脚本\n"
            "支持 嵌入版 + 通用版，协议 PPI / Modbus / OPC\n\n"
            "安全提示：真机写入须人工确认，下载前请先编译与仿真。",
        )

    # ---------- MCGS 组态独立入口 ----------
    def _open_scada_dialog(self):
        """弹工艺描述输入对话框 + 版本/协议下拉，确认后直接调工具生成组态。"""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("MCGS 组态设计助手")
        dlg.setMinimumWidth(480)
        form = QFormLayout()
        edt_craft = QPlainTextEdit()
        edt_craft.setPlaceholderText(
            "请描述工艺需求，如：\n"
            "电机启停控制，带故障指示与运行状态\n"
            "传送带计数，累计产量保存\n"
            "也可直接写明地址（如 I0.0 启动 / Q0.0 运行 / VW100 设定值）"
        )
        edt_craft.setFixedHeight(120)
        cmb_v = QComboBox()
        cmb_v.addItems(["McgsPro", "嵌入版", "通用版"])
        cmb_v.setCurrentText(self.scada_panel.cmb_version.currentText())
        cmb_p = QComboBox()
        cmb_p.addItems(["PPI", "Modbus", "OPC"])
        cmb_p.setCurrentText(self.scada_panel.cmb_protocol.currentText())
        form.addRow("工艺描述：", edt_craft)
        form.addRow("MCGS 版本：", cmb_v)
        form.addRow("协议：", cmb_p)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay = QVBoxLayout(dlg)
        lay.addLayout(form)
        lay.addWidget(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        craft = edt_craft.toPlainText().strip()
        if not craft:
            QMessageBox.information(self, "提示", "请填写工艺描述。")
            return
        version = cmb_v.currentText()
        protocol = cmb_p.currentText()
        # 同步到 scada_panel 下拉
        vi = self.scada_panel.cmb_version.findText(version)
        if vi >= 0:
            self.scada_panel.cmb_version.setCurrentIndex(vi)
        pi = self.scada_panel.cmb_protocol.findText(protocol)
        if pi >= 0:
            self.scada_panel.cmb_protocol.setCurrentIndex(pi)
        # 持久化到 config
        self.config.setdefault("mcgs", {})
        self.config["mcgs"]["version"] = version
        self.config["mcgs"]["protocol"] = protocol
        save_config(self.config)
        # 直接调工具（同步执行，完成后通过回调走 scada_ready 信号刷新 GUI）
        self.statusBar().showMessage(f"正在生成 MCGS 组态（{version}·{protocol}）……", 3000)
        try:
            text = self.executor.generate_scada(
                craft_desc=craft,
                mcgs_version=version,
                protocol=protocol,
            )
        except Exception as e:
            QMessageBox.warning(self, "生成失败", str(e))
            return
        # 切到 MCGS 组态助手 tab
        self.top_tabs.setCurrentIndex(1)
        # 把工具返回的 markdown 文本塞进对话区
        self.chat.add_message("user", f"（MCGS 组态）{craft}（版本：{version}，协议：{protocol}）")
        self.chat.add_message("assistant", text)
        self.statusBar().showMessage("MCGS 组态已生成，请在「MCGS 组态助手」面板查看。", 5000)

    # ---------- 配置持久化 ----------
    def _persist_plc_config(self):
        plc = self.config["plc"]
        plc["profile"] = self.plc_panel.cmb_profile.currentText()
        plc["host"] = self.plc_panel.edt_host.text().strip()
        plc["rack"] = self.plc_panel.spn_rack.value()
        plc["slot"] = self.plc_panel.spn_slot.value()
        save_config(self.config)

    # ---------- 写确认（工作线程调用，阻塞到GUI回复） ----------
    def _confirm_write(self, address: str, value) -> bool:
        return self._confirm_bridge.ask(address, str(value))

    # ---------- 关闭清理 ----------
    # ---------- 运行日志 Tab ----------
    def _build_log_tab(self):
        """构建应用内日志查看器 Tab。"""
        self._log_tab_widget = QWidget()

        # 日志文本框（带颜色高亮）
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        log_font = self.txt_log.font()
        log_font.setFamily("Consolas, Courier New")
        self.txt_log.setFont(log_font)

        # 过滤控件
        self.chk_show_debug = QCheckBox("DEBUG")
        self.chk_show_debug.setChecked(False)
        self.chk_show_info = QCheckBox("INFO")
        self.chk_show_info.setChecked(True)
        self.chk_show_warn = QCheckBox("WARNING")
        self.chk_show_warn.setChecked(True)
        self.chk_show_error = QCheckBox("ERROR")
        self.chk_show_error.setChecked(True)
        self.chk_auto_scroll = QCheckBox("自动滚动")
        self.chk_auto_scroll.setChecked(True)
        self.chk_show_debug.toggled.connect(lambda: self._apply_log_filter())
        self.chk_show_info.toggled.connect(lambda: self._apply_log_filter())
        self.chk_show_warn.toggled.connect(lambda: self._apply_log_filter())
        self.chk_show_error.toggled.connect(lambda: self._apply_log_filter())

        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(lambda: self.txt_log.clear())
        btn_copy = QPushButton("复制全部")
        btn_copy.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.txt_log.toPlainText())
        )
        btn_open_file = QPushButton("打开日志文件")
        btn_open_file.clicked.connect(self._open_log_file)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("显示级别："))
        filter_row.addWidget(self.chk_show_debug)
        filter_row.addWidget(self.chk_show_info)
        filter_row.addWidget(self.chk_show_warn)
        filter_row.addWidget(self.chk_show_error)
        filter_row.addStretch(1)
        filter_row.addWidget(self.chk_auto_scroll)
        filter_row.addWidget(btn_clear)
        filter_row.addWidget(btn_copy)
        filter_row.addWidget(btn_open_file)

        lay = QVBoxLayout(self._log_tab_widget)
        lay.addLayout(filter_row)
        lay.addWidget(self.txt_log, 1)

        # 缓存所有日志记录（用于过滤）
        self._all_log_records: list = []

    def _on_log_record(self, level: int, time_str: str, logger: str, message: str):
        """Qt 信号槽：接收一条 logging 记录并追加到 UI。"""
        import logging
        self._all_log_records.append((level, time_str, logger, message))
        self._append_log_line(level, time_str, logger, message)

    def _append_log_line(self, level: int, time_str: str, logger: str, message: str):
        """追加一行带颜色的日志。"""
        # 级别过滤
        import logging
        if level == logging.DEBUG and not self.chk_show_debug.isChecked():
            return
        if level == logging.INFO and not self.chk_show_info.isChecked():
            return
        if level == logging.WARNING and not self.chk_show_warn.isChecked():
            return
        if level >= logging.ERROR and not self.chk_show_error.isChecked():
            return

        # 颜色
        color_map = {
            logging.DEBUG: QColor(128, 128, 128),   # 灰色
            logging.INFO: QColor(30, 30, 30),       # 黑色
            logging.WARNING: QColor(200, 120, 0),   # 橙色
            logging.ERROR: QColor(200, 0, 0),       # 红色
            logging.CRITICAL: QColor(150, 0, 150),  # 紫色
        }
        color = color_map.get(level, QColor(0, 0, 0))

        # 级别名
        name_map = {
            logging.DEBUG: "DEBUG",
            logging.INFO: "INFO",
            logging.WARNING: "WARN",
            logging.ERROR: "ERROR",
            logging.CRITICAL: "CRIT",
        }
        level_name = name_map.get(level, str(level))

        line = f"[{time_str}] [{level_name}] [{logger}] {message}"

        # 带 color 的追加
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        self.txt_log.moveCursor(QTextCursor.MoveOperation.End)
        self.txt_log.setCurrentCharFormat(fmt)
        self.txt_log.insertPlainText(line + "\n")
        self.txt_log.setCurrentCharFormat(QTextCharFormat())  # 恢复默认

        # 自动滚动
        if self.chk_auto_scroll.isChecked():
            self.txt_log.moveCursor(QTextCursor.MoveOperation.End)

    def _apply_log_filter(self):
        """重新应用过滤：清空后按过滤条件重绘所有缓存记录。"""
        self.txt_log.clear()
        for rec in self._all_log_records:
            self._append_log_line(*rec)

    def _open_log_file(self):
        """用系统默认程序打开 app.log。"""
        try:
            from app.core.logger import _log_file
            import os, subprocess
            path = _log_file()
            if os.path.isfile(path):
                os.startfile(path)
            else:
                QMessageBox.information(self, "日志文件不存在",
                                        f"日志文件尚未生成：{path}")
        except Exception as e:
            QMessageBox.warning(self, "打开失败", str(e))

    def closeEvent(self, event):
        if self._conn_thread is not None:
            self._conn_thread.quit()
            self._conn_thread.wait(3000)
            if self._conn_worker is not None:
                self._conn_worker.deleteLater()
            self._conn_thread = None
        try:
            self.executor.driver.disconnect()
            self.executor.mock.stop()
        finally:
            event.accept()
