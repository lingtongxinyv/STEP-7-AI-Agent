# -*- coding: utf-8 -*-
"""统一视觉主题：配色、间距、控件样式集中管理。

仅依赖 PySide6，通过全局 QSS + Fusion 风格生效，不引入任何第三方资源，
保证源码运行、内置 runtime 与 PyInstaller 打包三种方式下表现一致。
"""

# ---- 设计令牌 ----
PRIMARY = "#2563eb"        # 主色（蓝）
PRIMARY_HOVER = "#1d4ed8"
PRIMARY_PRESSED = "#1e40af"
SUCCESS = "#16a34a"
DANGER = "#dc2626"
DANGER_HOVER = "#b91c1c"
BG = "#f4f6fb"             # 窗口底色
SURFACE = "#ffffff"        # 卡片/面板
BORDER = "#e3e8f0"
TEXT = "#1f2937"
TEXT_MUTED = "#6b7280"

FONT_FAMILY = "Microsoft YaHei UI, Microsoft YaHei, Segoe UI, Arial"

GLOBAL_QSS = f"""
* {{
    font-family: {FONT_FAMILY};
    color: {TEXT};
}}
QWidget {{
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background: {BG};
}}

/* ---- 卡片式分组框 ---- */
QGroupBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 14px;
    padding: 10px 10px 8px 10px;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: {TEXT};
}}

/* ---- 按钮 ---- */
QPushButton {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover {{
    border-color: {PRIMARY};
    color: {PRIMARY};
}}
QPushButton:pressed {{
    background: #eef2ff;
}}
QPushButton:disabled {{
    color: #9ca3af;
    border-color: #eef0f4;
    background: #fafbfd;
}}
QPushButton[variant="primary"] {{
    background: {PRIMARY};
    border: 1px solid {PRIMARY};
    color: white;
    font-weight: bold;
}}
QPushButton[variant="primary"]:hover {{
    background: {PRIMARY_HOVER};
    border-color: {PRIMARY_HOVER};
    color: white;
}}
QPushButton[variant="primary"]:pressed {{
    background: {PRIMARY_PRESSED};
    color: white;
}}
QPushButton[variant="success"] {{
    background: {SUCCESS};
    border: 1px solid {SUCCESS};
    color: white;
    font-weight: bold;
}}
QPushButton[variant="success"]:hover {{
    background: #15803d;
    border-color: #15803d;
    color: white;
}}
QPushButton[variant="danger"] {{
    background: {DANGER};
    border: 1px solid {DANGER};
    color: white;
}}
QPushButton[variant="danger"]:hover {{
    background: {DANGER_HOVER};
    border-color: {DANGER_HOVER};
    color: white;
}}

/* ---- 输入控件 ---- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: {PRIMARY};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {PRIMARY};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    selection-background-color: #e0e7ff;
    selection-color: {TEXT};
}}

/* ---- 表格 ---- */
QTableWidget {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: #eef1f6;
    selection-background-color: #e0e7ff;
    selection-color: {TEXT};
}}
QHeaderView::section {{
    background: #f8fafc;
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px;
    font-weight: bold;
}}

/* ---- 选项卡 ---- */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    background: {SURFACE};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    border: none;
    padding: 8px 16px;
    color: {TEXT_MUTED};
}}
QTabBar::tab:selected {{
    color: {PRIMARY};
    border-bottom: 2px solid {PRIMARY};
    font-weight: bold;
}}
QTabBar::tab:hover:!selected {{
    color: {TEXT};
}}

/* ---- 滚动条 ---- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #cbd5e1;
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: #94a3b8;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: #cbd5e1;
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #94a3b8;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0; width: 0;
}}

/* ---- 进度条 ---- */
QProgressBar {{
    background: #e5eaf3;
    border: none;
    border-radius: 5px;
    text-align: center;
    height: 14px;
}}
QProgressBar::chunk {{
    background: {PRIMARY};
    border-radius: 5px;
}}

/* ---- 工具提示 ---- */
QToolTip {{
    background: {TEXT};
    color: white;
    border: none;
    padding: 4px 8px;
}}

/* ---- 分割器 ---- */
QSplitter::handle {{
    background: {BORDER};
}}
QSplitter::handle:horizontal {{
    width: 2px;
}}
"""


def apply_theme(app):
    """在 QApplication 上应用全局主题。"""
    app.setStyle("Fusion")
    app.setStyleSheet(GLOBAL_QSS)
