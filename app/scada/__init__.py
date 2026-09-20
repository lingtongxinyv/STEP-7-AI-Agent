# -*- coding: utf-8 -*-
"""MCGS 组态设计助手模块。

负责从已生成的 PLC 程序或独立工艺描述派生 MCGS 组态素材：
- 变量字典（数据对象定义清单）
- 设备通道 CSV（11 列，可被 MCGS 嵌入版"设备信息导入"接口直接导入）
- 画面设计书（含 SVG 示意图）
- McgsScript 脚本（可直接粘贴到 MCGS 脚本编辑器）
- 协议说明（驱动选型/串口参数/从站地址/接线）

不生成 .mcg/.mce 工程文件（私有二进制，无开源解析器）。
"""
from .mcgs_templates import (
    derive_scada,
    render_scada_for_chat,
    build_export_package,
    SUPPORTED_VERSIONS,
    SUPPORTED_PROTOCOLS,
)
from .mcgs_knowledge import find_mcgs_installed
from .mcgs_auto_writer import MCGSAutoWriter, StepResult, find_mcgs_setpro_window

__all__ = [
    "derive_scada",
    "render_scada_for_chat",
    "build_export_package",
    "SUPPORTED_VERSIONS",
    "SUPPORTED_PROTOCOLS",
    "find_mcgs_installed",
    "MCGSAutoWriter",
    "StepResult",
    "find_mcgs_setpro_window",
]
