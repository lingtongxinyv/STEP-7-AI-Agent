# -*- coding: utf-8 -*-
"""
Agent 工具层：
1) TOOL_SPECS：OpenAI 工具调用（function calling）的 JSON 描述
2) ToolExecutor：真正执行工具动作（连接模拟/真机 PLC、读写、扫描、生成程序）

写入门禁：allow_write=False 时拒绝写入；True 时逐条经 confirm_write 回调确认。
"""
import json

from app.plc.driver import PlcDriver, PlcError
from app.plc.mock import MockPlc
from app.plc.profiles import get_profile
from app.programs.templates import (
    get_template,
    list_templates,
    render,
    render_for_chat,
)
from app.scada import (
    derive_scada,
    render_scada_for_chat,
    SUPPORTED_VERSIONS,
    SUPPORTED_PROTOCOLS,
)


# ---------------- OpenAI 工具描述 ----------------

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "connect_plc",
            "description": "连接 PLC。use_mock=true 时启动并连接内置模拟PLC（无需硬件）；否则连接现场真机。",
            "parameters": {
                "type": "object",
                "properties": {
                    "use_mock": {"type": "boolean", "description": "是否使用内置模拟PLC"},
                    "profile": {
                        "type": "string",
                        "enum": ["S7-200 SMART", "S7-200", "S7-300/400", "S7-1200/1500"],
                        "description": "目标设备型号",
                    },
                    "host": {"type": "string", "description": "真机 IP 地址"},
                    "rack": {"type": "integer", "description": "机架号（常用 0）"},
                    "slot": {"type": "integer", "description": "槽位号（200SMART 常用1，300 常用2）"},
                },
                "required": ["use_mock"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "disconnect_plc",
            "description": "断开与 PLC 的连接（不会停止模拟PLC服务）。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_tag",
            "description": "读取一个 PLC 变量，如 I0.0、Q0.1、M0.0、VB100、VW100、VD100、DB1.DBW2。",
            "parameters": {
                "type": "object",
                "properties": {"address": {"type": "string", "description": "变量地址"}},
                "required": ["address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_tag",
            "description": (
                "写入一个 PLC 变量。受安全门禁保护：只读模式下会被拒绝，"
                "允许写入时需用户在弹窗中逐条确认。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {"type": "string", "description": "变量地址"},
                    "value": {"type": "string", "description": "要写入的值（布尔写 true/false）"},
                },
                "required": ["address", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scan_area",
            "description": "扫描一片连续字节区域（1~256 字节），返回每个字节的偏移/十六进制/十进制。",
            "parameters": {
                "type": "object",
                "properties": {
                    "area": {"type": "string", "enum": ["V", "M", "I", "Q"], "description": "区域"},
                    "start": {"type": "integer", "description": "起始字节偏移"},
                    "length": {"type": "integer", "description": "字节数(1~256)"},
                },
                "required": ["area", "start", "length"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plc_status",
            "description": "查看当前连接状态、CPU 运行状态；模拟PLC下附带演示数据摘要。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_templates",
            "description": "列出可直接生成的经验证程序模板（可按目标设备过滤）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "可选：S7-200 SMART 或 S7-1200/1500",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_program",
            "description": "按模板 key 与参数生成完整 PLC 程序（含IO表、代码、原理、导入步骤）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "template_key": {"type": "string", "description": "模板 key，如 star_delta"},
                    "params": {
                        "type": "object",
                        "description": "参数键值对，如 {\"switch_pt\":\"80\"}；留空使用默认参数",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["template_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_scada",
            "description": (
                "生成 MCGS 组态素材（变量字典/设备通道CSV/画面设计书/McgsScript脚本/协议说明）。"
                "两种模式：① 联动模式 — 传 template_key 从已生成 PLC 程序派生变量；"
                "② 独立模式 — 传 craft_desc 按工艺描述派生典型 I/O。"
                "两种模式二选一：template_key 优先。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "template_key": {
                        "type": "string",
                        "description": "联动模式：PLC 程序模板 key（如 motor_latch），从其 io_table 派生 MCGS 变量",
                    },
                    "params": {
                        "type": "object",
                        "description": "联动模式：模板参数键值对，留空用默认",
                        "additionalProperties": {"type": "string"},
                    },
                    "craft_desc": {
                        "type": "string",
                        "description": "独立模式：工艺描述文本，如「电机启停控制，带故障指示」",
                    },
                    "mcgs_version": {
                        "type": "string",
                        "enum": SUPPORTED_VERSIONS,
                        "description": "MCGS 版本，默认嵌入版",
                    },
                    "protocol": {
                        "type": "string",
                        "enum": sorted({p for ps in SUPPORTED_PROTOCOLS.values() for p in ps}),
                        "description": "通信协议，默认 PPI",
                    },
                    "name": {"type": "string", "description": "组态工程名（可选）"},
                },
            },
        },
    },
]


# ---------------- 工具执行器 ----------------

class ToolExecutor:
    def __init__(self):
        self.driver = PlcDriver()
        self.mock = MockPlc()
        self.profile = "S7-200 SMART"
        self.is_mock_connection = False
        self.allow_write = False
        # 应用配置（由 UI 注入；未注入时使用空 dict 保证默认 port 兜底可用）
        self.config = {}
        # UI 注入的回调
        self.confirm_write = None          # (address, value) -> bool
        self.on_connection_changed = None  # () -> None
        self.on_program_generated = None   # (program_dict) -> None
        self.on_scada_generated = None     # (scada_dict) -> None

    # ---------- 状态 ----------
    @property
    def connected(self) -> bool:
        return self.driver.connected

    def device_context(self) -> str:
        if self.connected:
            kind = "内置模拟PLC" if self.is_mock_connection else f"真机（{self.profile}）"
            try:
                state = self.driver.cpu_state()
            except PlcError:
                state = "未知"
            return f"已连接{kind}，CPU 状态：{state}；写入门禁：{'关闭(只读)' if not self.allow_write else '开启(逐条确认)'}"
        return (
            "当前未连接 PLC。可使用 connect_plc(use_mock=true) 启动内置模拟PLC，"
            "或连接同网段真机（S7-200 SMART 默认 IP 多为 192.168.2.1）。"
        )

    def _notify(self):
        if self.on_connection_changed:
            self.on_connection_changed()

    # ---------- I/O 地址库 ----------
    def io_library(self) -> list:
        """用户预设的 I/O 地址库条目（未注入配置时为空）。"""
        lib = self.config.get("io_library") or []
        return lib if isinstance(lib, list) else []

    def io_library_text(self) -> str:
        """把地址库渲染成 Markdown 表格文本，供系统提示注入；库为空返回空串。"""
        lib = self.io_library()
        if not lib:
            return ""
        lines = ["| 元件/符号 | 地址 | 备注 |", "| --- | --- | --- |"]
        for e in lib:
            lines.append(
                f"| {e.get('symbol', '')} | {e.get('address', '')} | {e.get('comment', '')} |"
            )
        return "\n".join(lines)

    def _io_library_note(self, program: dict) -> str:
        """地址库与模板 I/O 分配的差异提示（库为空或无差异时返回空串）。"""
        lib = self.io_library()
        if not lib:
            return ""
        io_table = program.get("io_table") or []
        used = {addr for addr, _d in io_table}
        by_desc = {str(d): addr for addr, d in io_table}
        conflicts, uncovered = [], []
        for e in lib:
            sym, addr = str(e.get("symbol", "")), str(e.get("address", ""))
            if not sym or not addr or addr in used:
                continue
            hit = by_desc.get(sym)
            if hit:
                conflicts.append(f"{sym}：模板用 {hit}，地址库预设 {addr}")
            else:
                uncovered.append(f"{sym} = {addr}")
        if not conflicts and not uncovered:
            return ""
        parts = ["> ℹ️ 用户 I/O 地址库与本模板默认 I/O 分配存在差异："]
        parts += [f"> - 地址不同：{c}" for c in conflicts]
        parts += [f"> - 模板未用到：{u}（如需该元件请向用户确认如何增补）" for u in uncovered]
        parts.append(
            "> 模板程序为经验验证代码，请勿改动其地址；"
            "如需完全按地址库生成，请向用户说明后用非标方式编写。"
        )
        return "\n" + "\n".join(parts)

    # ---------- 连接 ----------
    def connect_plc(self, use_mock=False, profile=None, host=None,
                    rack=None, slot=None, port=None) -> str:
        try:
            if use_mock:
                if not self.mock.running:
                    self.mock.start()
                self.driver.connect(MockPlc.HOST, MockPlc.RACK, MockPlc.SLOT, MockPlc.PORT)
                self.is_mock_connection = True
                self.profile = "S7-200 SMART"
                self._notify()
                return "已连接内置模拟PLC（rack=0/slot=2），V/M/I/Q 区可读写。"

            if profile:
                self.profile = profile
            pf = get_profile(self.profile)
            host = host or pf["host"]
            rack = pf["rack"] if rack is None else rack
            slot = pf["slot"] if slot is None else slot
            if port is None:
                port = self.config.get("plc", {}).get("port", 102)
            self.driver.connect(host, rack, slot, port)
            self.is_mock_connection = False
            self._notify()
            return f"已连接真机 {self.profile} @ {host}（rack={rack}, slot={slot}, port={port}）。"
        except PlcError as e:
            return f"连接失败：{e}"

    def disconnect_plc(self) -> str:
        if self.driver.connected:
            self.driver.disconnect()
            self._notify()
            return "已断开 PLC 连接。"
        return "当前本来就未连接。"

    # ---------- 读写 ----------
    def _require_connection(self):
        if not self.driver.connected:
            raise PlcError("尚未连接 PLC，请先连接（无硬件可启动模拟PLC）。")

    def read_tag(self, address: str) -> str:
        try:
            self._require_connection()
            value = self.driver.read(address)
            return f"{address} = {value}"
        except (PlcError, ValueError) as e:
            return f"读取失败：{e}"

    def write_tag(self, address: str, value: str) -> str:
        try:
            self._require_connection()
            if not self.allow_write:
                return "写入被拒绝：当前为只读安全模式。确需写入时，请在 PLC 面板勾选“允许写入”。"
            if self.confirm_write and not self.confirm_write(address, value):
                return "写入已取消：用户未确认。"
            self.driver.write(address, value)
            return f"写入成功：{address} = {value}（建议立即回读核验）"
        except (PlcError, ValueError) as e:
            return f"写入失败：{e}"

    def scan_area(self, area: str, start: int, length: int) -> str:
        try:
            self._require_connection()
            rows = self.driver.scan(area, start, length)
            lines = [f"{area}{off}: {hexi} ({dec})" for off, hexi, dec in rows]
            return "\n".join(lines)
        except (PlcError, ValueError) as e:
            return f"扫描失败：{e}"

    def plc_status(self) -> str:
        lines = [self.device_context()]
        if self.driver.connected and self.is_mock_connection:
            lines.append("模拟产线数据摘要：")
            for addr in ("M0.0", "VW100", "VW102", "VD120", "VB200", "VW210"):
                lines.append("  " + self.read_tag(addr))
        return "\n".join(lines)

    # ---------- 模板与程序 ----------
    def list_templates(self, target: str = "") -> str:
        items = list_templates(target or None)
        if not items:
            return f"没有找到适用于 {target} 的模板。"
        lines = ["可用程序模板（generate_program 的 params 只接受下列参数 key）："]
        for t in items:
            param_txt = ", ".join(f"{k}({label}, 默认{d})" for k, label, d in t.params)
            lines.append(
                f"- {t.key}：{t.name}（{t.target} · {t.language}）——{t.description}\n"
                f"    参数：{param_txt}"
            )
        return "\n".join(lines)

    def generate_program(self, template_key: str, params=None) -> str:
        try:
            template = get_template(template_key)
            params = params or {}
            valid_keys = {k for k, _l, _d in template.params}
            unknown = [k for k in params if k not in valid_keys]
            program = render(template, params)
        except KeyError as e:
            return f"生成失败：{e}"
        if self.on_program_generated:
            self.on_program_generated(program)
        text = render_for_chat(program)
        if unknown:
            valid_txt = ", ".join(f"{k}={d}" for k, _l, d in template.params)
            text += (
                f"\n\n> ⚠️ 已忽略未知参数：{', '.join(unknown)}。"
                f"如需调整，请使用正确的参数 key 重新调用本工具。可用参数：{valid_txt}"
            )
        note = self._io_library_note(program)
        if note:
            text += "\n\n" + note
        return text

    # ---------- MCGS 组态 ----------
    def generate_scada(self, template_key=None, params=None, craft_desc=None,
                       mcgs_version="嵌入版", protocol="PPI", name=None) -> str:
        """生成 MCGS 组态素材。

        联动模式（template_key）：先调 get_template+render 得 program，再 derive_scada(program=...)
        独立模式（craft_desc）：直接 derive_scada(craft_desc=...)
        回调 on_scada_generated(scada)；返回 render_scada_for_chat(scada)。
        """
        try:
            program = None
            if template_key:
                template = get_template(template_key)
                program = render(template, params or {})
                # 联动模式下，若也产生 PLC 程序，触发一次 program 回调让程序面板同步
                if self.on_program_generated:
                    self.on_program_generated(program)

            if program is not None:
                scada = derive_scada(
                    program=program,
                    mcgs_version=mcgs_version,
                    protocol=protocol,
                    name=name,
                )
            else:
                if not craft_desc:
                    return "请提供 template_key（联动模式）或 craft_desc（独立模式）之一。"
                scada = derive_scada(
                    craft_desc=craft_desc,
                    mcgs_version=mcgs_version,
                    protocol=protocol,
                    name=name,
                )
        except Exception as e:
            return f"MCGS 组态生成失败：{e}"

        if self.on_scada_generated:
            self.on_scada_generated(scada)
        return render_scada_for_chat(scada)

    # ---------- 总入口 ----------
    def dispatch(self, name: str, arguments: str) -> str:
        try:
            kwargs = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return f"工具参数解析失败：{arguments}"
        handler = {
            "connect_plc": self.connect_plc,
            "disconnect_plc": self.disconnect_plc,
            "read_tag": self.read_tag,
            "write_tag": self.write_tag,
            "scan_area": self.scan_area,
            "plc_status": self.plc_status,
            "list_templates": self.list_templates,
            "generate_program": self.generate_program,
            "generate_scada": self.generate_scada,
        }.get(name)
        if handler is None:
            return f"未知工具：{name}"
        try:
            return handler(**kwargs)
        except TypeError as e:
            return f"工具参数错误：{e}"
        except Exception as e:  # 防止工具异常中断整个对话
            return f"工具执行出错：{e}"
