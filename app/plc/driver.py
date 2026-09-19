# -*- coding: utf-8 -*-
"""基于 python-snap7 的真机 PLC 驱动：连接、读、写、区域扫描、CPU 状态。"""
import snap7

from .address import AddressError, parse_address

_UTIL = snap7.util


class PlcError(RuntimeError):
    pass


def _decode(buf: bytearray, parsed) -> object:
    dtype = parsed.dtype
    if dtype == "BOOL":
        return bool(_UTIL.get_bool(buf, 0, parsed.bit))
    if dtype == "BYTE":
        return int(buf[0])
    if dtype == "INT":
        return int(_UTIL.get_int(buf, 0))
    if dtype == "WORD":
        return int(_UTIL.get_word(buf, 0))
    if dtype == "DINT":
        return int(_UTIL.get_dint(buf, 0))
    if dtype == "DWORD":
        return int(_UTIL.get_dword(buf, 0))
    if dtype == "REAL":
        return round(float(_UTIL.get_real(buf, 0)), 6)
    raise PlcError(f"不支持的数据类型：{dtype}")


def _encode(parsed, value) -> bytearray:
    buf = bytearray(parsed.size)
    dtype = parsed.dtype
    try:
        if dtype == "BOOL":
            if isinstance(value, str):
                b = value.strip().lower() in ("1", "true", "on", "yes", "开", "真")
            else:
                b = bool(value)
            _UTIL.set_bool(buf, 0, parsed.bit, b)
        elif dtype == "BYTE":
            v = int(float(value))
            if not 0 <= v <= 255:
                raise ValueError
            buf[0] = v
        elif dtype in ("INT",):
            v = int(float(value))
            if not -32768 <= v <= 32767:
                raise ValueError
            _UTIL.set_int(buf, 0, v)
        elif dtype == "WORD":
            v = int(float(value))
            if not 0 <= v <= 65535:
                raise ValueError
            _UTIL.set_word(buf, 0, v)
        elif dtype == "DINT":
            v = int(float(value))
            if not -2147483648 <= v <= 2147483647:
                raise ValueError
            _UTIL.set_dint(buf, 0, v)
        elif dtype == "DWORD":
            v = int(float(value))
            if not 0 <= v <= 4294967295:
                raise ValueError
            _UTIL.set_dword(buf, 0, v)
        elif dtype == "REAL":
            _UTIL.set_real(buf, 0, float(value))
        else:
            raise PlcError(f"不支持的数据类型：{dtype}")
    except (TypeError, ValueError):
        raise PlcError(f"值 {value!r} 无法转换为 {dtype}")
    return buf


class PlcDriver:
    """所有西门子 PLC 共用的 snap7 客户端驱动。"""

    def __init__(self):
        self._client = None

    # ---------- 连接管理 ----------
    def connect(self, host: str, rack: int, slot: int, port: int = 102) -> None:
        self.disconnect()
        client = snap7.client.Client()
        try:
            client.connect(host, int(rack), int(slot), int(port))
        except Exception as e:  # snap7 异常类型较多，统一封装
            client.destroy()
            raise PlcError(f"连接 {host} 失败：{e}")
        self._client = client

    def disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
            try:
                self._client.destroy()
            except Exception:
                pass
            self._client = None

    @property
    def connected(self) -> bool:
        if self._client is None:
            return False
        try:
            return bool(self._client.get_connected())
        except Exception:
            return False

    # ---------- 读写 ----------
    def read(self, address: str):
        parsed = parse_address(address)
        try:
            buf = self._client.read_area(parsed.area, parsed.dbnumber, parsed.offset, parsed.size)
        except Exception as e:
            raise PlcError(f"读取 {address} 失败：{e}")
        return _decode(buf, parsed)

    def write(self, address: str, value) -> None:
        parsed = parse_address(address)
        buf = _encode(parsed, value)
        try:
            self._client.write_area(parsed.area, parsed.dbnumber, parsed.offset, buf)
        except Exception as e:
            raise PlcError(f"写入 {address} 失败：{e}")

    # ---------- 批量扫描 ----------
    def scan(self, area: str, start: int, length: int) -> list:
        """
        扫描一片字节区域。
        area: V / M / I / Q（V 映射 DB1）
        返回 [(偏移, 十六进制, 十进制), ...]
        """
        if length <= 0 or length > 256:
            raise PlcError("扫描长度需在 1~256 字节之间")
        area = (area or "").strip().upper()
        area_map = {
            "V": (snap7.type.Areas.DB, 1),
            "M": (snap7.type.Areas.MK, 0),
            "I": (snap7.type.Areas.PE, 0),
            "Q": (snap7.type.Areas.PA, 0),
        }
        if area not in area_map:
            raise AddressError("扫描区域只支持 V / M / I / Q")
        area_enum, dbnumber = area_map[area]
        try:
            buf = self._client.read_area(area_enum, dbnumber, int(start), int(length))
        except Exception as e:
            raise PlcError(f"扫描 {area}{start} 失败：{e}")
        return [(int(start) + i, f"0x{buf[i]:02X}", int(buf[i])) for i in range(len(buf))]

    # ---------- CPU ----------
    def cpu_state(self) -> str:
        try:
            return str(self._client.get_cpu_state())
        except Exception as e:
            raise PlcError(f"获取 CPU 状态失败：{e}")
