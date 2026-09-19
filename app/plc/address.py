# -*- coding: utf-8 -*-
"""
PLC 地址解析。

支持 S7-200 / 200 SMART 风格：
    I0.0  Q0.1  M0.2          位
    VB100                     字节
    VW100                     有符号整数 (INT, 2字节)
    VD100                     实数 (REAL, 4字节)，VD 也可显式指定 :dint / :dword
支持标准 S7 风格（S7-300/400/1200/1500）：
    M0.0  I0.0  Q0.0
    DB1.DBX0.0  DB1.DBB1  DB1.DBW2  DB1.DBD4
可附加显式类型：VD100:dint、MD20:dword
"""
import re
from dataclasses import dataclass

import snap7

Areas = snap7.type.Areas

# 数据类型 -> 字节长度
_SIZES = {
    "BOOL": 1,
    "BYTE": 1,
    "INT": 2,
    "WORD": 2,
    "DINT": 4,
    "DWORD": 4,
    "REAL": 4,
}

_PREFIX_AREA = {
    "I": Areas.PE,
    "Q": Areas.PA,
    "M": Areas.MK,
}


@dataclass
class ParsedAddress:
    area: int            # snap7 Areas
    dbnumber: int
    offset: int
    dtype: str
    bit: int = 0

    @property
    def size(self) -> int:
        return _SIZES[self.dtype]


class AddressError(ValueError):
    pass


def _check_dtype(dtype: str):
    if dtype not in _SIZES:
        raise AddressError(f"不支持的数据类型：{dtype}")


def parse_address(text: str) -> ParsedAddress:
    if not text or not isinstance(text, str):
        raise AddressError("地址为空")
    raw = text.strip().replace(" ", "").upper()
    if not raw:
        raise AddressError("地址为空")

    # 显式类型后缀 :DINT / :DWORD / :REAL ...
    explicit = None
    if ":" in raw:
        raw, suffix = raw.rsplit(":", 1)
        explicit = suffix
        _check_dtype(explicit)

    # 1) DB 风格：DB1.DBX0.0 / DBB / DBW / DBD
    m = re.fullmatch(r"DB(\d+)\.(DB[XBWD])(\d+)(?:\.(\d+))?", raw)
    if m:
        dbnumber = int(m.group(1))
        code = m.group(2)
        offset = int(m.group(3))
        bit_txt = m.group(4)
        if code == "DBX":
            if bit_txt is None:
                raise AddressError("位地址缺少位号，例如 DB1.DBX0.0")
            bit = int(bit_txt)
            if bit > 7:
                raise AddressError("位号必须在 0~7 之间")
            dtype = explicit or "BOOL"
            return ParsedAddress(Areas.DB, dbnumber, offset, dtype, bit)
        dtype = {
            "DBB": "BYTE",
            "DBW": "INT",
            "DBD": "REAL",
        }[code]
        if bit_txt is not None:
            raise AddressError("字节/字/双字地址不能带位号")
        return ParsedAddress(Areas.DB, dbnumber, offset, explicit or dtype)

    # 2) S7-200 风格：V / M / I / Q + 位 或 B/W/D
    m = re.fullmatch(r"([VMQI])(\d+)(?:\.(\d+))?", raw)
    if m:
        prefix = m.group(1)
        offset = int(m.group(2))
        bit_txt = m.group(3)
        if bit_txt is not None:
            bit = int(bit_txt)
            if bit > 7:
                raise AddressError("位号必须在 0~7 之间")
            dtype = explicit or "BOOL"
            if prefix == "V":
                return ParsedAddress(Areas.DB, 1, offset, dtype, bit)
            return ParsedAddress(_PREFIX_AREA[prefix], 0, offset, dtype, bit)
        # 无位号时必须给 B/W/D 宽度或显式类型
        if explicit:
            if prefix == "V":
                return ParsedAddress(Areas.DB, 1, offset, explicit)
            return ParsedAddress(_PREFIX_AREA[prefix], 0, offset, explicit)
        raise AddressError(
            f"地址 {text} 缺少宽度：字节 VB/MB/IB/QB，字 VW/MW/IW/QW，双字 VD/MD/ID/QD"
        )

    # 3) 带宽度的 S7-200 风格：VB100 / VW100 / VD100、MW20 等
    m = re.fullmatch(r"([VMQI])([BWD])(\d+)", raw)
    if m:
        prefix, width, off_txt = m.groups()
        offset = int(off_txt)
        dtype = {
            "B": "BYTE",
            "W": "INT",
            "D": "REAL",
        }[width]
        dtype = explicit or dtype
        if prefix == "V":
            return ParsedAddress(Areas.DB, 1, offset, dtype)
        return ParsedAddress(_PREFIX_AREA[prefix], 0, offset, dtype)

    raise AddressError(
        f"无法识别的地址：{text}。示例：I0.0、Q0.1、M0.0、VB100、VW100、VD100、DB1.DBW2"
    )
