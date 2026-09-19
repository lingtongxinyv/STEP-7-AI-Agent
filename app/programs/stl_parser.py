# -*- coding: utf-8 -*-
"""
STL（语句表）→ 梯形图 Rung 自动解析。

支持 S7-200 SMART 标准指令：
    LD / LDN        装载 常开/常闭
    O  / ON         或 常开/常闭（并联支路）
    A  / AN         与 常开/常闭（串联节点）
    EU / ED         上升沿 / 下降沿
    NOT             结果取反
    =               输出线圈（同一网络可多个）
    TON/TOF/TONR/TP 定时器功能框（名, PT）
    CTU/CTD         计数器功能框（名, PV；CTU 尽力提取复位输入）
    S / R           置位 / 复位线圈（addr, n）

解析模型为“串联节点（节点内并联支路）”，适用于无 ALD/OLD 栈操作的平面 STL；
遇到不支持的指令抛 UnsupportedStl，调用方据此优雅降级。
"""
import re

from app.programs.ladder import (
    Contact,
    Coil,
    FuncBox,
    Rung,
    NO,
    NC,
    P,
    N,
    NOTK,
)


class UnsupportedStl(Exception):
    """STL 含无法转换为梯形图的指令。"""


_NETWORK = re.compile(r"^\s*NETWORK\s+\d+", re.I)
_TOKEN = re.compile(r"^\s*([A-Za-z=]+)\s*(.*)$")

_LOADS = {"LD": NO, "LDN": NC}
_ORS = {"O": NO, "ON": NC}
_ANDS = {"A": NO, "AN": NC}
_TIMERS = {"TON", "TOF", "TONR", "TP"}


def _strip_comment(text: str) -> str:
    i = text.find("//")
    return text[:i] if i >= 0 else text


def parse_stl(code: str):
    """把多 NETWORK 的 STL 文本解析成 Rung 列表。"""
    networks = []
    current = None

    for raw in code.splitlines():
        if _NETWORK.match(raw.strip()):
            if current is not None:
                networks.append(current)
            tail = re.sub(r"^\s*NETWORK\s+\d+\s*", "", raw, flags=re.I)
            current = {"lines": [], "comment": tail.lstrip("/ ").strip()}
            continue
        if current is None:
            current = {"lines": [], "comment": ""}
        body = _strip_comment(raw).strip()
        if body:
            current["lines"].append(body)
    if current is not None:
        networks.append(current)

    if not networks:
        raise UnsupportedStl("未找到任何指令行")
    return [_parse_network(n["lines"], n["comment"]) for n in networks]


def _single_contact(operand: str, kind: str) -> Contact:
    operand = re.sub(r"\s+", " ", operand.strip())
    return Contact(operand, kind)


def _parse_network(lines: list, comment: str) -> Rung:
    series = []      # 已完成的串联节点（并联组）
    group = None    # 当前并联组：[[Contact], [Contact]...]
    outputs = []

    for line in lines:
        m = _TOKEN.match(line)
        if not m:
            continue
        op = m.group(1).upper()
        oper = re.sub(r"\s+", " ", m.group(2).strip())

        if op in _LOADS:
            group = [[_single_contact(oper, _LOADS[op])]]

        elif op in _ORS:
            contact = _single_contact(oper, _ORS[op])
            if group is None:           # 容错：孤立 O 当作新组
                group = [[contact]]
            else:
                group.append([contact])

        elif op in _ANDS:
            contact = _single_contact(oper, _ANDS[op])
            if group is None:           # 容错：孤立 A 当作新组
                group = [[contact]]
            else:
                series.append(group)
                group = [[contact]]

        elif op in ("EU", "ED"):
            if group is not None:
                series.append(group)
            group = [[Contact("", P if op == "EU" else N)]]

        elif op == "NOT":
            if group is not None:
                series.append(group)
            group = [[Contact("", NOTK)]]

        elif op == "=":
            if group is not None:
                series.append(group)
                group = None
            outputs.append(Coil(oper))

        elif op in _TIMERS:
            parts = [p.strip() for p in oper.split(",")]
            if len(parts) < 2 or not parts[0] or not parts[1]:
                raise UnsupportedStl(line.strip())
            if group is not None:
                series.append(group)
                group = None
            outputs.append(FuncBox(op, parts[0], pt=parts[1]))

        elif op in ("CTU", "CTD"):
            parts = [p.strip() for p in oper.split(",")]
            if len(parts) < 2:
                raise UnsupportedStl(line.strip())
            # S7-200 栈式写法：CTU 前最后一个 LD 是复位输入 R，之前的逻辑是计数输入 CU
            r_addr = ""
            if group is not None:
                first = group[0][0]
                if (
                    len(group) == 1
                    and len(group[0]) == 1
                    and first.kind == NO
                    and first.addr
                ):
                    r_addr = first.addr
                else:
                    series.append(group)
                group = None
            outputs.append(FuncBox(op, parts[0], pt=parts[1], r=r_addr))

        elif op in ("S", "R"):
            if not oper:
                raise UnsupportedStl(line.strip())
            if group is not None:
                series.append(group)
                group = None
            addr = oper.split(",")[0].strip()
            outputs.append(Coil(addr, "置位" if op == "S" else "复位"))

        else:
            # ALD/OLD/FOR/NEXT/MOV/间接寻址等：无法可靠转为平面梯形图
            raise UnsupportedStl(op)

    if group is not None:
        series.append(group)
    return Rung(comment, series, outputs)
