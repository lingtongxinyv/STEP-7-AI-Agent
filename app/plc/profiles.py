# -*- coding: utf-8 -*-
"""西门子 PLC 设备配置：连接默认参数与使用说明。"""
from collections import OrderedDict

# rack/slot 仅为常用默认值，可在界面中按实际修改
PROFILES = OrderedDict([
    ("S7-200 SMART", {
        "rack": 0,
        "slot": 1,
        "host": "192.168.2.1",
        "areas": "V / M / I / Q（V 区在 S7 协议中映射为 DB1）",
        "note": "CPU 出厂 IP 多为 192.168.2.1；若连不上可在 Micro/WIN SMART 中核对实际 IP。",
    }),
    ("S7-200", {
        "rack": 0,
        "slot": 1,
        "host": "192.168.2.1",
        "areas": "V / M / I / Q",
        "note": "老款 S7-200 经 CP243-1 或以太网模块通信，TSAP 需与模块组态一致，部分情况 rack=0/slot=0。",
    }),
    ("S7-300/400", {
        "rack": 0,
        "slot": 2,
        "host": "192.168.0.1",
        "areas": "DB / M / I / Q / T / C",
        "note": "S7-300 经典组态 CPU 通常在 slot 2（slot 1 为电源）。",
    }),
    ("S7-1200/1500", {
        "rack": 0,
        "slot": 1,
        "host": "192.168.0.1",
        "areas": "DB / M / I / Q / T / C",
        "note": "若使用经典 S7 通信，需在 TIA Portal 中开启 CPU 属性“允许 PUT/GET 通信访问”，并使用非优化 DB 块。",
    }),
])


def profile_names():
    return list(PROFILES.keys())


def get_profile(name: str) -> dict:
    return PROFILES.get(name, PROFILES["S7-200 SMART"])
