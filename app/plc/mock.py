# -*- coding: utf-8 -*-
"""
内置模拟 PLC（基于 snap7 Server）。

无需任何真实硬件：
- V 区 (DB1) 2048 字节、M 区 256 字节、I 区 32 字节、Q 区 32 字节
- TM/CT 定时器/计数器区各 32 个元件（每个 2 字节）
- 仅绑定 127.0.0.1，不影响外网与真实设备
- 预设有教学演示数据
连接模拟 PLC 时客户端使用 rack=0 / slot=2（snap7 Server 的兼容寻址）。
"""
import logging

import snap7

# snap7 Server 在建链协商阶段会输出无害的内部警告，将其静音
logging.getLogger("snap7").setLevel(logging.CRITICAL)


class MockPlcError(RuntimeError):
    pass


class MockPlc:
    HOST = "127.0.0.1"
    PORT = 102
    # snap7 Server 接受的客户端寻址
    RACK = 0
    SLOT = 2

    def __init__(self):
        self._server = None
        self.v = bytearray(2048)
        self.m = bytearray(256)
        self.i = bytearray(32)
        self.q = bytearray(32)
        # 定时器/计数器区：每个元件占 2 字节，32 个元件
        self.tm = bytearray(64)
        self.ct = bytearray(64)

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> None:
        if self._server is not None:
            return
        server = snap7.server.Server()
        try:
            server.create()
            sa = snap7.type.SrvArea
            server.register_area(sa.DB, 1, self.v)
            server.register_area(sa.MK, 0, self.m)
            server.register_area(sa.PE, 0, self.i)
            server.register_area(sa.PA, 0, self.q)
            server.register_area(sa.TM, 0, self.tm)
            server.register_area(sa.CT, 0, self.ct)
            self._seed()
            server.start_to(self.HOST, self.PORT)
        except Exception as e:
            try:
                server.destroy()
            except Exception:
                pass
            raise MockPlcError(f"模拟 PLC 启动失败：{e}")
        self._server = server

    def stop(self) -> None:
        if self._server is None:
            return
        server = self._server
        self._server = None
        try:
            server.stop()
        except Exception:
            pass
        try:
            server.destroy()
        except Exception:
            pass

    def _seed(self) -> None:
        """预置一组模拟产线数据，便于学习与演示。"""
        util = snap7.util
        # VW100：今日产量
        util.set_int(self.v, 100, 128)
        # VW102：目标产量
        util.set_int(self.v, 102, 500)
        # VD120：炉温 (℃)
        util.set_real(self.v, 120, 36.5)
        # VB200：设备状态字（bit0 就绪 bit1 运行）
        self.v[200] = 0x03
        # VW210：报警代码（0 无报警）
        util.set_int(self.v, 210, 0)
        # M0.0：系统运行标志
        util.set_bool(self.m, 0, 0, True)
        # T37：定时器当前值演示
        # 注意 snap7 Server TM/CT 区元件 N 落在缓冲字节 N、N+1（非 N*2）
        util.set_int(self.tm, 37, 50)
        # C1：计数器当前值演示
        util.set_int(self.ct, 1, 12)
