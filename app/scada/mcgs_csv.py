# -*- coding: utf-8 -*-
"""MCGS 设备通道 CSV 构建器。

生成 MCGS 嵌入版/通用版/McgsPro「设备窗口 → 右键 → 设备信息导入」接口
可识别的 11 列 CSV。按协议 + 版本派生各列：

嵌入版/通用版：
- PPI：寄存器名=地址，寄存器地址=地址，数据类型=PLC dtype
- Modbus：调 s7_to_modbus_register 映射 0x/1x/4x
- OPC：调 s7_to_opc_item 生成项路径

McgsPro（列内容格式不同）：
- 通道号从 0 开始（嵌入版/通用版从 1 开始）
- 变量类型用英文：INTEGER(BOOL/整数) / SINGLE(浮点)
- 通道名称固定格式：读写+区域+地址（如 读写M010.0 / 读写VDF0020）
- 寄存器名称用中文描述（如 V数据寄存器 / M内部继电器）
- 数据类型列用中文描述（如 通道的第00位 / 32位 浮点数）
- 寄存器地址用数值
"""
import csv
import io

from .mcgs_knowledge import (
    CSV_COLUMNS,
    s7_to_modbus_register,
    s7_to_opc_item,
    MCGSPRO_VAR_TYPE_MAP,
    MCGSPRO_REGISTER_NAMES,
    MCGSPRO_CHANNEL_DTYPE_MAP,
    mcgspro_channel_name,
    mcgspro_register_address,
)


def _build_row_legacy(variable, index, protocol):
    """嵌入版/通用版行构建（通道号从 1 开始，中文变量类型）。"""
    addr = variable.get("address", "")
    name = variable.get("name", "")
    var_type = variable.get("var_type", "开关型")
    dtype = variable.get("dtype", "BOOL")
    read_write = "只读" if variable.get("read_only") else "读写"

    if protocol == "PPI":
        reg_name = addr
        reg_addr = addr
        reg_dtype = dtype
    elif protocol == "Modbus":
        reg_name, reg_addr, mod_dtype = s7_to_modbus_register(addr)
        reg_dtype = mod_dtype
    else:  # OPC
        reg_name = s7_to_opc_item(addr)
        reg_addr = ""
        reg_dtype = dtype

    return {
        "通道号": str(index),
        "变量名": name,
        "变量类型": var_type,
        "通道名称": name,
        "读写类型": read_write,
        "寄存器名称": reg_name,
        "数据类型": reg_dtype,
        "寄存器地址": str(reg_addr),
        "地址偏移": "0",
        "采集频次": "1",
        "通道处理": "",
    }


def _build_row_pro(variable, index0, protocol):
    """McgsPro 行构建（通道号从 0 开始，英文变量类型，中文描述列）。"""
    addr = variable.get("address", "")
    name = variable.get("name", "")
    dtype = variable.get("dtype", "BOOL")
    read_only = variable.get("read_only", False)
    read_write = "只读" if read_only else "读写"

    # McgsPro 专用列
    pro_var_type = MCGSPRO_VAR_TYPE_MAP.get(dtype, "INTEGER")
    ch_name = mcgspro_channel_name(addr, read_only)
    # 寄存器名称：取地址首字母对应中文描述
    import re
    m = re.match(r"^([A-Za-z]+)", addr)
    area = m.group(1).upper() if m else "M"
    reg_name = MCGSPRO_REGISTER_NAMES.get(area, f"{area}寄存器")
    # 数据类型列：McgsPro 用中文描述
    ch_dtype_desc = MCGSPRO_CHANNEL_DTYPE_MAP.get(dtype, dtype)
    reg_addr_num = mcgspro_register_address(addr)

    return {
        "通道号": str(index0),
        "变量名": name,
        "变量类型": pro_var_type,
        "通道名称": ch_name,
        "读写类型": read_write,
        "寄存器名称": reg_name,
        "数据类型": ch_dtype_desc,
        "寄存器地址": str(reg_addr_num),
        "地址偏移": "0",
        "采集频次": "1",
        "通道处理": "",
    }


def build_device_channels_csv(variables, mcgs_version="嵌入版", protocol="PPI"):
    """生成 11 列设备通道 CSV 文本（UTF-8 BOM，便于 MCGS 识别中文）。

    variables 为 scada dict 中 variables 字段的列表，每项含：
        name / address / var_type / dtype / read_only
    """
    out = io.StringIO()
    out.write("\ufeff")  # UTF-8 BOM
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS)
    writer.writeheader()

    if mcgs_version == "McgsPro":
        # McgsPro：通道号从 0 开始
        for i0, var in enumerate(variables):
            row = _build_row_pro(var, i0, protocol)
            writer.writerow(row)
    else:
        # 嵌入版/通用版：通道号从 1 开始
        for i, var in enumerate(variables, start=1):
            row = _build_row_legacy(var, i, protocol)
            writer.writerow(row)

    return out.getvalue()
