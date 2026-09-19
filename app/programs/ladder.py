# -*- coding: utf-8 -*-
"""
梯形图数据模型、自绘渲染控件与 .awl 导出。

- Contact / Coil / FuncBox / Rung：梯形图梯级描述（地址先用模板参数 key 占位）；
- LADDER_MAP + build_ladder()：把 render() 输出的程序字典解析成可绘制的 Rung 列表，
  梯级顺序与模板 STL 的 NETWORK 编号一一对应；
- LadderWidget：QPainter 自绘只读梯形图（左右母线、触点、线圈、TON/CTU 功能框）；
- export_awl_text()：生成 Micro/WIN SMART 可导入的 STL(.awl) 文本。
"""
from dataclasses import dataclass, field

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

NO = "no"    # 常开触点 --| |--
NC = "nc"    # 常闭触点 --|/|--
P = "p"      # 上升沿触点 --|P|--
N = "n"      # 下降沿触点 --|N|--
NOTK = "not"  # 逻辑取反 --|NOT|--


@dataclass
class Contact:
    addr: str
    kind: str = NO
    label: str = ""


@dataclass
class Coil:
    addr: str
    label: str = ""


@dataclass
class FuncBox:
    kind: str            # TON / CTU / R
    name: str = ""       # 定时器/计数器号
    pt: str = ""         # 预设值（PT/PV）
    r: str = ""          # CTU 复位输入


@dataclass
class Rung:
    comment: str = ""
    nodes: list = field(default_factory=list)   # 串联节点；节点=并联支路列表；支路=[Contact]
    outputs: object = None                      # Coil / FuncBox / 其列表

    def __post_init__(self):
        # 兼容单个输出对象的写法（LADDER_MAP 中直接传 Coil/FuncBox）
        if self.outputs is not None and not isinstance(self.outputs, list):
            self.outputs = [self.outputs]


def _C(addr, kind=NO, label=""):
    return Contact(addr, kind, label)


# ---------------- 各模板的梯形图结构（地址为模板参数 key，运行时替换） ----------------

LADDER_MAP = {
    "motor_latch": [
        Rung("电机启保停",
             [[[_C("start")], [_C("motor", label="自锁触点")]],
              [[_C("stop", NC, "停止(常闭)")]]],
             Coil("motor", "电机接触器")),
    ],
    "motor_fwd_rev": [
        Rung("正转控制",
             [[[_C("fwd_start")], [_C("fwd", label="自锁")]],
              [[_C("stop", NC)]],
              [[_C("rev", NC, "软件互锁")]]],
             Coil("fwd", "正转接触器")),
        Rung("反转控制",
             [[[_C("rev_start")], [_C("rev", label="自锁")]],
              [[_C("stop", NC)]],
              [[_C("fwd", NC, "软件互锁")]]],
             Coil("rev", "反转接触器")),
    ],
    "star_delta": [
        Rung("主接触器自锁",
             [[[_C("start")], [_C("main", label="自锁")]],
              [[_C("stop", NC)]]],
             Coil("main", "主接触器")),
        Rung("星三角切换计时（100ms 时基）",
             [[[_C("main")]]],
             FuncBox("TON", "timer", pt="switch_pt")),
        Rung("星形接触器",
             [[[_C("main")]],
              [[_C("timer", NC, "计时到断开")]],
              [[_C("delta", NC, "软件互锁")]]],
             Coil("star", "星形接触器")),
        Rung("三角接触器",
             [[[_C("timer")]],
              [[_C("star", NC, "软件互锁")]]],
             Coil("delta", "三角接触器")),
    ],
    "flasher": [
        Rung("灭灯期间计时",
             [[[_C("timer_b", NC)]]],
             FuncBox("TON", "timer_a", pt="off_pt")),
        Rung("亮灯期间计时",
             [[[_C("timer_a")]]],
             FuncBox("TON", "timer_b", pt="on_pt")),
        Rung("闪烁输出",
             [[[_C("timer_a")]]],
             Coil("lamp", "闪烁输出")),
    ],
    "traffic_light": [
        Rung("启停自锁",
             [[[_C("run")], [_C("M0.0", label="运行标志")]],
              [[_C("stop", NC)]]],
             Coil("M0.0", "运行标志")),
        Rung("南北绿计时",
             [[[_C("M0.0")]]],
             FuncBox("TON", "T37", pt="g_ns_pt")),
        Rung("南北黄计时",
             [[[_C("T37")]]],
             FuncBox("TON", "T38", pt="y_ns_pt")),
        Rung("东西绿计时",
             [[[_C("T38")]]],
             FuncBox("TON", "T39", pt="g_ew_pt")),
        Rung("东西黄计时",
             [[[_C("T39")]]],
             FuncBox("TON", "T40", pt="y_ew_pt")),
        Rung("周期到复位定时器链",
             [[[_C("T40", P, "上升沿")]]],
             FuncBox("R", "T37, 4")),
        Rung("南北绿灯",
             [[[_C("M0.0")], [_C("T37", NC)]]],
             Coil("ns_g", "南北绿灯")),
        Rung("南北黄灯",
             [[[_C("T37")], [_C("T38", NC)]]],
             Coil("ns_y", "南北黄灯")),
        Rung("南北红灯",
             [[[_C("T38")], [_C("T40", NC)]]],
             Coil("ns_r", "南北红灯")),
        Rung("东西绿灯",
             [[[_C("T38")], [_C("T39", NC)]]],
             Coil("ew_g", "东西绿灯")),
        Rung("东西黄灯",
             [[[_C("T39")], [_C("T40", NC)]]],
             Coil("ew_y", "东西黄灯")),
        Rung("东西红灯",
             [[[_C("M0.0")], [_C("T38", NC)]]],
             Coil("ew_r", "东西红灯")),
    ],
    "conveyor": [
        Rung("传送带运行",
             [[[_C("start")], [_C("belt", label="自锁")]],
              [[_C("stop", NC, "停止/复位")]],
              [[_C("T37", NC, "延时到停机")]]],
             Coil("belt", "传送带电机")),
        Rung("无料延时停机（有料时 T37 保持复位）",
             [[[_C("belt")], [_C("sensor", NC)]]],
             FuncBox("TON", "T37", pt="delay_pt")),
        Rung("物料计数：光电上升沿加一",
             [[[_C("sensor", P, "上升沿计数")]],
              [[_C("stop")]]],
             FuncBox("CTU", "counter", pt="target", r="stop")),
    ],
    "dual_belts": [
        Rung("下游皮带先启动",
             [[[_C("start")], [_C("belt2", label="自锁")]],
              [[_C("T37", NC, "排空延时到")]]],
             Coil("belt2", "下游 2 号皮带")),
        Rung("启动间隔计时",
             [[[_C("belt2")]]],
             FuncBox("TON", "T38", pt="start_pt")),
        Rung("上游皮带延时启动，按停止立即停",
             [[[_C("T38")]],
              [[_C("stop", NC)]]],
             Coil("belt1", "上游 1 号皮带")),
        Rung("停车后排空延时",
             [[[_C("stop")]]],
             FuncBox("TON", "T37", pt="stop_pt")),
    ],
    "shuttle": [
        Rung("右行控制",
             [[[_C("start")], [_C("right_motor", label="自锁")],
               [_C("left_limit", label="左限位换向")]],
              [[_C("stop", NC)]],
              [[_C("right_limit", NC, "右限位")]],
              [[_C("left_motor", NC, "软件互锁")]]],
             Coil("right_motor", "右行接触器")),
        Rung("左行控制",
             [[[_C("right_limit")], [_C("left_motor", label="自锁")]],
              [[_C("stop", NC)]],
              [[_C("left_limit", NC, "左限位")]],
              [[_C("right_motor", NC, "软件互锁")]]],
             Coil("left_motor", "左行接触器")),
    ],
}


def build_ladder(program: dict):
    """把渲染后的程序字典解析成 Rung 列表；STL 之外的程序返回 None。"""
    if program.get("language") != "STL":
        return None
    template_rungs = LADDER_MAP.get(program.get("key"))
    if template_rungs is None:
        # 非标 STL：自动解析指令为梯形图；不支持的指令则降级
        from app.programs.stl_parser import UnsupportedStl, parse_stl

        try:
            return parse_stl(program["code"])
        except UnsupportedStl:
            return None
    rungs = template_rungs
    values = program.get("params", {}) or {}

    def rs(token: str) -> str:
        return str(values.get(token, token))

    resolved = []
    for rung in rungs:
        nodes = []
        for node in rung.nodes:
            nodes.append(
                [[Contact(rs(c.addr), c.kind, c.label) for c in branch] for branch in node]
            )
        outs = []
        for out in rung.outputs:
            if isinstance(out, Coil):
                outs.append(Coil(rs(out.addr), out.label))
            elif isinstance(out, FuncBox):
                outs.append(
                    FuncBox(
                        out.kind,
                        rs(out.name) if out.name else "",
                        rs(out.pt) if out.pt else "",
                        rs(out.r) if out.r else "",
                    )
                )
        resolved.append(Rung(rung.comment, nodes, outs))
    return resolved


# ---------------- .awl 导出（Micro/WIN SMART 可导入的 STL 文本） ----------------

def export_awl_text(program: dict) -> str:
    lines = [
        "// ==================================================",
        f"// {program['name']}",
        f"// 目标设备：{program['target']}    语言：STL",
        "// 由 STEP 7 AI Agent 生成，Micro/WIN SMART 可直接导入",
        "// ==================================================",
        "",
        program["code"].rstrip(),
        "",
    ]
    return "\n".join(lines)


# ---------------- 梯形图绘制控件 ----------------

_RAIL_L = 40            # 左母线 x
_RAIL_R_PAD = 46        # 右侧留白（含右母线）
_LANE = 42              # 并联支路行距
_TOP = 54               # 梯级顶部到主行中心
_CW = 42                # 触点单元宽
_NGAP = 34              # 相邻节点间连线
_COIL_W = 64
_BOX_W = 156
_BOX_H = 68
_MIN_W = 660

_ADDR_COLOR = QColor("#0b4f9e")
_LABEL_COLOR = QColor("#777777")
_WIRE_COLOR = QColor("#1a1a1a")
_BOX_FILL = QColor("#fff8e1")


class LadderWidget(QWidget):
    """只读梯形图画布（配合 QScrollArea 使用）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._title = ""
        self._rungs = []
        self._laid = []
        self._width = _MIN_W
        small = QFont("Microsoft YaHei UI")
        small.setPointSizeF(8.5)
        self._small = small
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor("white"))
        self.setPalette(pal)
        self.setMinimumSize(_MIN_W, 160)

    def has_content(self) -> bool:
        return bool(self._rungs)

    def set_program(self, title: str, rungs):
        self._title = title or ""
        self._rungs = rungs or []
        self._layout_rungs()
        self.update()

    # ---------- 布局 ----------
    @staticmethod
    def _out_half(out) -> int:
        return _BOX_H // 2 if isinstance(out, FuncBox) else 12

    def _layout_rungs(self):
        self._laid = []
        max_end = 0
        y = 34
        if self._title:
            y += 24
        for rung in self._rungs:
            lanes = max([len(n) for n in rung.nodes], default=1) or 1
            lane0 = y + _TOP
            info = {"rung": rung, "y": y, "nodes": []}

            # ---- 逻辑节点布局 ----
            x = _RAIL_L
            for node in rung.nodes:
                node_w = max(len(b) for b in node) * _CW
                info["nodes"].append({"x0": x, "w": node_w, "branches": node})
                x += node_w + _NGAP
            x -= _NGAP

            # ---- 输出位置：单输出在主行；多输出垂直堆叠 ----
            outs = rung.outputs
            positions = []
            if len(outs) == 1:
                positions.append((lane0, self._out_half(outs[0]), outs[0]))
            elif len(outs) > 1:
                yc = lane0 - 18
                for out in outs:
                    half = self._out_half(out)
                    yc += half + 6
                    positions.append((yc, half, out))
                    yc += half + 6
            info["out_positions"] = positions

            has_box = any(isinstance(o, FuncBox) for o in outs)
            info["out_w"] = _BOX_W if has_box else (_COIL_W if outs else 0)
            info["out_x"] = x

            logic_bottom = lane0 + (lanes - 1) * _LANE
            out_bottom = positions[-1][0] + positions[-1][1] if positions else lane0
            bottom = max(logic_bottom, out_bottom) + 14
            info["bottom"] = bottom

            max_end = max(max_end, x + info["out_w"] + 26)
            y = bottom + 12
            self._laid.append(info)
        self._width = max(_MIN_W, max_end + _RAIL_R_PAD)
        self.setMinimumSize(self._width, max(160, y + 8))

    # ---------- 绘制 ----------
    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("white"))
        if not self._rungs:
            p.setPen(QColor("#888888"))
            p.drawText(
                self.rect().adjusted(24, 24, -24, -24),
                Qt.AlignmentFlag.AlignCenter,
                "该程序暂不支持梯形图显示（可能含无法识别的 STL 指令；"
                "标准位逻辑、定时器/计数器、置位复位指令可自动转换）。",
            )
            return

        p.setFont(self._small)
        if self._title:
            p.setPen(QColor("#333333"))
            p.drawText(QRect(_RAIL_L, 6, self._width - _RAIL_L - 40, 18),
                       Qt.AlignmentFlag.AlignLeft, self._title)

        pen = QPen(_WIRE_COLOR, 2)
        rail_r = self._width - 34
        first_lane0 = self._laid[0]["y"] + _TOP
        last_bottom = self._laid[-1]["bottom"]

        # 左右母线
        p.setPen(pen)
        p.drawLine(_RAIL_L, first_lane0, _RAIL_L, last_bottom)
        p.drawLine(rail_r, first_lane0, rail_r, last_bottom)

        for index, li in enumerate(self._laid):
            rung = li["rung"]
            y0 = li["y"]
            lane0 = y0 + _TOP

            p.setFont(self._small)
            p.setPen(QColor("#555555"))
            p.drawText(QRect(_RAIL_L + 8, y0 + 2, 620, 16),
                       Qt.AlignmentFlag.AlignLeft, f"{index + 1}. {rung.comment}")
            p.setPen(pen)

            prev_end = _RAIL_L
            for node in li["nodes"]:
                x0, w = node["x0"], node["w"]
                p.drawLine(prev_end, lane0, x0, lane0)  # 节点间主行连线
                nb = len(node["branches"])
                for bi, branch in enumerate(node["branches"]):
                    ly = y0 + _TOP + bi * _LANE
                    cx = x0
                    for ci, contact in enumerate(branch):
                        cell_x = x0 + ci * _CW
                        self._draw_contact(p, cell_x, ly, contact)
                        cx = cell_x + _CW
                    if cx < x0 + w:
                        p.drawLine(cx, ly, x0 + w, ly)
                if nb > 1:
                    p.drawLine(x0, lane0, x0, y0 + _TOP + (nb - 1) * _LANE)
                    p.drawLine(x0 + w, lane0, x0 + w, y0 + _TOP + (nb - 1) * _LANE)
                prev_end = x0 + w

            # 主逻辑行延伸到输出区
            p.drawLine(prev_end, lane0, li["out_x"], lane0)
            positions = li["out_positions"]
            multi = len(positions) > 1
            if multi:
                # 输出侧竖母线，挂接多个线圈/功能框
                p.drawLine(
                    li["out_x"],
                    positions[0][0] - positions[0][1] - 4,
                    li["out_x"],
                    positions[-1][0] + positions[-1][1] + 4,
                )
            for cy, _half, out in positions:
                if isinstance(out, FuncBox):
                    self._draw_box(p, li["out_x"], cy, out)
                    p.drawLine(li["out_x"] + _BOX_W, cy, rail_r, cy)
                else:
                    cx_c = li["out_x"] + 16
                    if multi or cy != lane0:
                        p.drawLine(li["out_x"], cy, cx_c - 10, cy)
                    p.drawEllipse(cx_c - 10, cy - 10, 20, 20)
                    p.drawLine(cx_c + 10, cy, rail_r, cy)
                    p.setFont(self._small)
                    p.setPen(_ADDR_COLOR)
                    p.drawText(QRect(cx_c - 44, cy - 28, 88, 14),
                               Qt.AlignmentFlag.AlignCenter, out.addr)
                    if out.label:
                        p.setPen(_LABEL_COLOR)
                        p.drawText(QRect(cx_c - 54, cy + 14, 108, 14),
                                   Qt.AlignmentFlag.AlignCenter, out.label)
                    p.setPen(pen)
            if not positions:
                # 无输出元素的网络：直接贯通右母线
                p.drawLine(li["out_x"], lane0, rail_r, lane0)

    def _draw_contact(self, p: QPainter, cell_x: int, ly: int, contact: Contact):
        b1 = cell_x + 8
        b2 = cell_x + _CW - 8
        p.setPen(QPen(_WIRE_COLOR, 2))
        p.drawLine(cell_x - 6, ly, b1, ly)      # 入线（含与前一元素的间隙）
        p.drawLine(b2, ly, cell_x + _CW, ly)    # 出线
        p.drawLine(b1, ly - 11, b1, ly + 11)
        p.drawLine(b2, ly - 11, b2, ly + 11)
        if contact.kind == NC:
            p.drawLine(b1 - 2, ly + 9, b2 + 2, ly - 9)
        elif contact.kind == P:
            p.setFont(self._small)
            p.drawText(QRect(b1, ly - 10, b2 - b1, 20),
                       Qt.AlignmentFlag.AlignCenter, "P")
        elif contact.kind == N:
            p.setFont(self._small)
            p.drawText(QRect(b1, ly - 10, b2 - b1, 20),
                       Qt.AlignmentFlag.AlignCenter, "N")
        elif contact.kind == NOTK:
            p.setFont(self._small)
            p.drawText(QRect(b1, ly - 10, b2 - b1, 20),
                       Qt.AlignmentFlag.AlignCenter, "NOT")
        # 地址与注释
        p.setFont(self._small)
        p.setPen(_ADDR_COLOR)
        p.drawText(QRect(cell_x - 6, ly - 26, _CW + 12, 14),
                   Qt.AlignmentFlag.AlignCenter, contact.addr)
        if contact.label:
            p.setPen(_LABEL_COLOR)
            p.drawText(QRect(cell_x - 14, ly + 14, _CW + 28, 14),
                       Qt.AlignmentFlag.AlignCenter, contact.label)

    def _draw_box(self, p: QPainter, x: int, ly: int, box: FuncBox):
        p.setPen(QPen(_WIRE_COLOR, 2))
        p.setBrush(_BOX_FILL)
        p.drawRect(x, ly - _BOX_H // 2, _BOX_W, _BOX_H)
        p.setBrush(Qt.BrushStyle.NoBrush)

        lines = [f"{box.kind} {box.name}".strip()]
        if box.pt:
            tag = "PV" if box.kind == "CTU" else "PT"
            lines.append(f"{tag}: {box.pt}")
        if box.r:
            lines.append(f"R : {box.r}")
        p.setFont(self._small)
        p.setPen(QColor("#1a1a1a"))
        line_h = 16
        top = ly - (len(lines) * line_h) // 2 + 2
        for i, text in enumerate(lines):
            p.drawText(QRect(x + 8, top + i * line_h, _BOX_W - 16, line_h),
                       Qt.AlignmentFlag.AlignLeft, text)
