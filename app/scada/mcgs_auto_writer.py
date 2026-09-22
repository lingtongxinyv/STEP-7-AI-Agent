# -*- coding: utf-8 -*-
"""MCGS UI 自动化写入（零第三方依赖版）。

利用 McgsPro（McgsSetPro.exe）使用 MFC 标准 Win32 控件（SysListView32 / Button /
ToolbarWindow32 / Menu）的特性，通过 ctypes 直接调用 Win32 API 模拟用户操作，
将 AI 生成的组态素材自动写入 MCGS 工程。

支持的自动化步骤：
0. 启动/激活 McgsSetPro 主窗口
1. 自动导入设备通道 CSV（主菜单 设备>设备信息导入，或设备窗口右键菜单）
2. 自动粘贴 McgsScript（剪贴板 + Ctrl+A/V，目标编辑器需处于活动状态）
3. 数据对象（变量）创建 — MCGS 无批量接口，无法自动化，引导手动完成

设计原则：
- 每步独立 try/except，失败时优雅回退并给出手动操作指引，不阻塞后续步骤
- 通过回调 on_progress(step, message) 报告进度，返回 StepResult 列表
- 仅依赖 Python 标准库 ctypes，任何干净 Windows 电脑均可运行
"""
import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Optional


# ================= Win32 绑定 =================

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

# 消息 / 标志常量
WM_COMMAND = 0x0111
WM_SETTEXT = 0x000C
BM_CLICK = 0x00F5
MN_GETHMENU = 0x01E1
GW_OWNER = 4
SW_RESTORE = 9
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_RETURN = 0x0D

MIIM_ID = 0x00000002
MIIM_SUBMENU = 0x00000004
MIIM_STRING = 0x00000040
MIIM_FTYPE = 0x00000100


class MENUITEMINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("fMask", wintypes.UINT),
        ("fType", wintypes.UINT),
        ("fState", wintypes.UINT),
        ("wID", wintypes.UINT),
        ("hSubMenu", wintypes.HMENU),
        ("hbmpChecked", wintypes.HBITMAP),
        ("hbmpUnchecked", wintypes.HBITMAP),
        ("dwItemData", ctypes.c_size_t),
        ("dwTypeData", wintypes.LPWSTR),
        ("cch", wintypes.UINT),
        ("hbmpItem", wintypes.HBITMAP),
    ]


def _bind_win32():
    """设置原型，避免 64 位下句柄被截断为 int。"""
    u = user32
    u.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    u.EnumWindows.restype = wintypes.BOOL
    u.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]
    u.EnumChildWindows.restype = wintypes.BOOL
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.IsWindow.argtypes = [wintypes.HWND]
    u.IsIconic.argtypes = [wintypes.HWND]
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    u.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
    u.GetWindow.restype = wintypes.HWND
    u.GetMenu.argtypes = [wintypes.HWND]
    u.GetMenu.restype = wintypes.HMENU
    u.GetSubMenu.argtypes = [wintypes.HMENU, ctypes.c_int]
    u.GetSubMenu.restype = wintypes.HMENU
    u.GetMenuItemCount.argtypes = [wintypes.HMENU]
    u.GetMenuItemInfoW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.BOOL,
                                   ctypes.POINTER(MENUITEMINFOW)]
    u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.SendMessageW.restype = wintypes.LPARAM
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.BringWindowToTop.argtypes = [wintypes.HWND]
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.GetWindowThreadProcessId.restype = wintypes.DWORD
    u.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    u.GetForegroundWindow.restype = wintypes.HWND
    u.OpenClipboard.argtypes = [wintypes.HWND]
    u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u.SetClipboardData.restype = wintypes.HANDLE
    u.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.POINTER(wintypes.ULONG)]
    u.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                              wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
    u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]

    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

    shell32.ShellExecuteW.argtypes = [
        wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.LPCWSTR, ctypes.c_int,
    ]
    shell32.ShellExecuteW.restype = wintypes.HINSTANCE


_bind_win32()


# ================= 基础 Win32 工具 =================

def _window_text(hwnd) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _enum_windows():
    found = []

    def cb(hwnd, _):
        found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


def _enum_children(parent):
    found = []

    def cb(hwnd, _):
        found.append(hwnd)
        return True

    user32.EnumChildWindows(parent, WNDENUMPROC(cb), 0)
    return found


def _menu_items(hmenu) -> list:
    """列出菜单各项的 (位置, wID, hSubMenu, 文本)。"""
    result = []
    count = user32.GetMenuItemCount(hmenu)
    for i in range(max(count, 0)):
        info = MENUITEMINFOW()
        info.cbSize = ctypes.sizeof(MENUITEMINFOW)
        info.fMask = MIIM_ID | MIIM_SUBMENU | MIIM_STRING | MIIM_FTYPE
        buf = ctypes.create_unicode_buffer(256)
        info.dwTypeData = ctypes.cast(buf, wintypes.LPWSTR)
        info.cch = 255
        if user32.GetMenuItemInfoW(hmenu, i, True, ctypes.byref(info)):
            result.append((i, info.wID, info.hSubMenu, buf.value))
    return result


def _find_in_menu(hmenu, text: str):
    """在菜单中递归查找文本包含 text 的项，返回 (wID, hSubMenu)。"""
    for _pos, wid, sub, label in _menu_items(hmenu):
        if text in (label or ""):
            return wid, sub
        if sub:
            found = _find_in_menu(sub, text)
            if found:
                return found
    return None


def _set_clipboard_text(text: str) -> None:
    """把 Unicode 文本写入剪贴板（自行完成全局内存分配）。"""
    buf = (text + "\x00").encode("utf-16-le")
    hglobal = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(buf))
    if not hglobal:
        raise MemoryError("GlobalAlloc 失败")
    ptr = kernel32.GlobalLock(hglobal)
    if not ptr:
        raise MemoryError("GlobalLock 失败")
    ctypes.memmove(ptr, buf, len(buf))
    kernel32.GlobalUnlock(hglobal)
    if not user32.OpenClipboard(None):
        raise OSError("OpenClipboard 失败（剪贴板被占用）")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, hglobal):
            raise OSError("SetClipboardData 失败")
        hglobal = None  # 所有权已移交，不可再释放
    finally:
        user32.CloseClipboard()


def _key_press(vk: int):
    user32.keybd_event(vk, 0, 0, None)
    time.sleep(0.03)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, None)


def _hotkey(*vkeys):
    for vk in vkeys:
        user32.keybd_event(vk, 0, 0, None)
        time.sleep(0.03)
    time.sleep(0.05)
    for vk in reversed(vkeys):
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, None)
        time.sleep(0.03)


def _mouse_click(x: int, y: int, right: bool = False):
    down = 0x0008 if right else 0x0002  # RIGHTDOWN / LEFTDOWN
    up = 0x0010 if right else 0x0004    # RIGHTUP / LEFTUP
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    user32.mouse_event(down, 0, 0, 0, None)
    time.sleep(0.05)
    user32.mouse_event(up, 0, 0, 0, None)


# ================= 结果类型 =================

@dataclass
class StepResult:
    step: int            # 步骤序号
    name: str            # 步骤名称
    success: bool        # 是否成功
    manual: bool = False  # 是否需要手动完成
    message: str = ""    # 结果/错误/引导信息


# ================= MCGS 窗口识别 =================

MCGS_MAIN_TITLE_KEYWORDS = ("mcgspro组态环境", "mcgs组态环境", "mcgspro", "mcgset")


def find_mcgs_setpro_window() -> Optional[int]:
    """找到 McgsSetPro 主窗口 hwnd。"""
    target = None
    for hwnd in _enum_windows():
        if not user32.IsWindowVisible(hwnd):
            continue
        title = _window_text(hwnd).lower()
        if any(k in title for k in MCGS_MAIN_TITLE_KEYWORDS):
            target = hwnd
            break
    return target


def bring_window_to_front(hwnd: int) -> bool:
    """把窗口恢复、置顶并激活；用 AttachThreadInput 绕过前台锁定。"""
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        cur_tid = kernel32.GetCurrentThreadId()
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        fg = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        if fg_tid and fg_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, fg_tid, True)
        if target_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, target_tid, True)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if target_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, target_tid, False)
        if fg_tid and fg_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, fg_tid, False)
        time.sleep(0.3)
        return True
    except Exception:
        return False


# ================= MCGS 自动化写入器 =================

class MCGSAutoWriter:
    """MCGS 组态自动写入器（纯 ctypes，无 pywin32 依赖）。

    使用：
        writer = MCGSAutoWriter(scada, mcgs_exe_path)
        results = writer.run(on_progress=lambda step, msg: ...)
    """

    def __init__(self, scada: dict, mcgs_exe_path: str = None):
        self.scada = scada
        self.mcgs_exe_path = mcgs_exe_path
        self.results: list = []
        self._csv_path: Optional[str] = None
        self._script_path: Optional[str] = None
        self._progress_cb: Optional[Callable] = None

    def _progress(self, step: int, message: str):
        if self._progress_cb:
            self._progress_cb(step, message)

    def run(self, on_progress: Callable = None) -> list:
        """执行所有自动化步骤，返回 StepResult 列表。"""
        self._progress_cb = on_progress
        self.results = []
        self._add_temp_files()

        # Step 0：启动/激活 MCGS
        self._progress(0, "正在启动/激活 MCGS 组态环境……")
        ok = self._ensure_mcgs_running()
        self.results.append(StepResult(
            0, "启动/激活 MCGS", ok,
            message="ok" if ok else "MCGS 未启动且无法自动启动，请手动打开后重试"))

        if not ok:
            self._progress(0, "MCGS 未就绪，后续步骤跳过（临时文件已生成，可手动导入）。")
            return self.results + [
                StepResult(1, "导入设备通道 CSV", False,
                           message=f"MCGS 未就绪，可手动导入：{self._csv_path}"),
                StepResult(2, "粘贴 McgsScript", False,
                           message=f"MCGS 未就绪，脚本文件：{self._script_path}"),
                StepResult(3, "数据对象创建", False, manual=True, message="需手动创建"),
            ]

        # Step 1：导入设备通道 CSV
        self._progress(1, "正在自动导入设备通道 CSV……")
        ok, msg = self._import_device_channels_csv()
        self.results.append(StepResult(1, "导入设备通道 CSV", ok, message=msg))

        # Step 2：粘贴脚本
        self._progress(2, "正在准备 McgsScript 剪贴板并尝试粘贴……")
        ok, msg = self._paste_script()
        self.results.append(StepResult(2, "粘贴 McgsScript", ok, message=msg))

        # Step 3：数据对象（必须手动）
        n = len(self.scada.get("variables", []))
        self.results.append(StepResult(
            3, "数据对象创建", False, manual=True,
            message=f"MCGS 无批量创建数据对象的入口，请对照「变量字典」在实时数据库逐条新建（共 {n} 项）。"))

        return self.results

    # ---------- 临时文件 ----------
    def _add_temp_files(self):
        tmp_dir = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")),
                               "STEP7_AI_MCGS")
        os.makedirs(tmp_dir, exist_ok=True)
        self._csv_path = os.path.join(tmp_dir, "device_channels.csv")
        self._script_path = os.path.join(tmp_dir, "mcgs_script.mcs")
        with open(self._csv_path, "w", encoding="utf-8-sig") as f:
            f.write(self.scada["device_channels_csv"])
        with open(self._script_path, "w", encoding="utf-8") as f:
            f.write(self.scada["script"])

    # ---------- Step 0 ----------
    def _ensure_mcgs_running(self) -> bool:
        hwnd = find_mcgs_setpro_window()
        if hwnd:
            return bring_window_to_front(hwnd)

        if self.mcgs_exe_path and os.path.isfile(self.mcgs_exe_path):
            self._progress(0, f"MCGS 未运行，尝试启动：{self.mcgs_exe_path}")
            try:
                # runas 请求管理员（McgsPro 部分版本写注册表/驱动需要）
                rc = shell32.ShellExecuteW(
                    None, "runas", self.mcgs_exe_path, None,
                    os.path.dirname(self.mcgs_exe_path), 1)
                if rc <= 32:  # ShellExecute 错误码
                    # 不需要管理员时 runas 可能被拒，退回普通启动
                    rc = shell32.ShellExecuteW(
                        None, "open", self.mcgs_exe_path, None,
                        os.path.dirname(self.mcgs_exe_path), 1)
                if rc <= 32:
                    return False
                for _ in range(30):  # 最多等 15 秒
                    time.sleep(0.5)
                    hwnd = find_mcgs_setpro_window()
                    if hwnd:
                        return bring_window_to_front(hwnd)
            except Exception as e:
                self._progress(0, f"启动异常：{e}")
        return False

    # ---------- Step 1 ----------
    def _import_device_channels_csv(self) -> tuple:
        hwnd = find_mcgs_setpro_window()
        if not hwnd:
            return False, "MCGS 主窗口未找到"
        bring_window_to_front(hwnd)
        try:
            # 方案 A：主菜单 设备 > 设备信息导入
            menu = user32.GetMenu(hwnd)
            if menu:
                dev = _find_in_menu(menu, "设备")
                if dev and dev[1]:  # 含子菜单
                    leaf = _find_in_menu(dev[1], "设备信息导入")
                    if leaf:
                        user32.PostMessageW(hwnd, WM_COMMAND, leaf[0], 0)
                        time.sleep(0.6)
                        ok, msg = self._handle_file_dialog(hwnd, self._csv_path)
                        if ok:
                            time.sleep(1.0)
                            return True, "设备通道 CSV 已通过主菜单自动导入"
                        self._progress(1, f"对话框处理：{msg}")

            # 方案 B：设备窗口右键菜单
            self._progress(1, "主菜单未命中，尝试设备窗口右键菜单……")
            return self._device_window_right_menu_import(hwnd)
        except Exception as e:
            return False, f"导入异常：{e}"

    def _device_window_right_menu_import(self, hwnd: int) -> tuple:
        list_views = [c for c in _enum_children(hwnd)
                      if _class_name(c) == "SysListView32"]
        if not list_views:
            return False, (f"未找到设备列表控件，请手动导入：设备窗口右键>设备信息导入>{self._csv_path}")

        lv = list_views[0]
        rect = wintypes.RECT()
        user32.GetWindowRect(lv, ctypes.byref(rect))
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        _mouse_click(cx, cy)
        time.sleep(0.2)
        _mouse_click(cx, cy, right=True)
        time.sleep(0.5)

        # 找弹出菜单并取其 HMENU
        for pop in _enum_windows():
            if not user32.IsWindowVisible(pop) or _class_name(pop) != "#32768":
                continue
            hmenu = user32.SendMessageW(pop, MN_GETHMENU, 0, 0)
            if not hmenu:
                continue
            leaf = _find_in_menu(hmenu, "设备信息导入")
            if leaf:
                user32.PostMessageW(hwnd, WM_COMMAND, leaf[0], 0)
                time.sleep(0.6)
                ok, msg = self._handle_file_dialog(hwnd, self._csv_path)
                if ok:
                    return True, "设备通道 CSV 已通过右键菜单自动导入"
                return False, msg
        return False, f"右键菜单未命中，请手动：设备窗口右键>设备信息导入>{self._csv_path}"

    def _handle_file_dialog(self, owner_hwnd, target_path: str) -> tuple:
        """等待并处理文件选择对话框（#32770）。"""
        dlg = None
        for _ in range(10):  # 最多等 2 秒
            for h in _enum_windows():
                if (user32.IsWindowVisible(h) and _class_name(h) == "#32770"
                        and user32.GetWindow(h, GW_OWNER) == owner_hwnd):
                    dlg = h
                    break
            if dlg:
                break
            time.sleep(0.2)
        if not dlg:
            return False, "未弹出文件选择对话框"

        bring_window_to_front(dlg)
        edit = None
        btn_ok = None
        for child in _enum_children(dlg):
            cls = _class_name(child)
            if cls == "Edit" and edit is None:
                edit = child
            elif cls == "Button":
                t = _window_text(child)
                if ("打开" in t or "确定" in t or t.lower() == "open") and btn_ok is None:
                    btn_ok = child
        if edit:
            user32.SendMessageW(edit, WM_SETTEXT, 0, target_path)
            time.sleep(0.2)
        if btn_ok:
            user32.SendMessageW(btn_ok, BM_CLICK, 0, 0)
            time.sleep(0.8)
            return True, "文件选择对话框已确认"
        # Enter 兜底
        _hotkey(VK_RETURN)
        time.sleep(0.8)
        return True, "文件选择对话框已确认（Enter 兜底）"

    # ---------- Step 2 ----------
    def _paste_script(self) -> tuple:
        """把脚本放入剪贴板，并尝试向当前活动文本框 Ctrl+A/V。

        前提：用户已在 MCGS 中打开脚本编辑器（运行策略/窗口循环脚本/控件事件）。
        若目标未打开，则只完成剪贴板装载并给出明确手动指引。
        """
        hwnd = find_mcgs_setpro_window()
        if not hwnd:
            return False, "MCGS 主窗口未找到"
        script_text = self.scada.get("script", "")
        if not script_text.strip():
            return False, "脚本内容为空"
        try:
            _set_clipboard_text(script_text)
        except OSError as e:
            return False, f"剪贴板写入失败：{e}。请手动打开脚本文件：{self._script_path}"

        bring_window_to_front(hwnd)
        # 尽力粘贴：若当前焦点恰是脚本编辑器即生效
        _hotkey(VK_CONTROL, 0x41)  # Ctrl+A
        time.sleep(0.15)
        _hotkey(VK_CONTROL, 0x56)  # Ctrl+V
        time.sleep(0.3)
        return True, (
            "脚本已装入剪贴板并尝试粘贴到当前活动文本框；"
            "请在 MCGS 打开脚本编辑器（运行策略/窗口循环脚本/控件事件），"
            "若内容未出现，直接 Ctrl+V 即可（脚本文件：%s）" % self._script_path)
