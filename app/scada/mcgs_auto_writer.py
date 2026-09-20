# -*- coding: utf-8 -*-
"""MCGS UI 自动化写入。

利用 McgsPro（McgsSetPro.exe）使用 MFC 标准 Win32 控件（SysListView32 / Button /
ToolbarWindow32 / ComboBox / Menu）的特性，通过纯 win32gui + ctypes 模拟用户操作，
将 AI 生成的组态素材自动写入 MCGS 工程。

支持的自动化步骤：
1. 启动/激活 McgsSetPro 主窗口
2. 自动导入设备通道 CSV（右键设备窗口 → 设备信息导入 → 选文件）
3. 自动粘贴 McgsScript 到脚本编辑器
4. 数据对象（变量）创建 — MCGS 无批量接口，**无法自动化**，需引导手动完成

设计原则：
- 每步都有 try/except + 超时，失败时优雅回退，不阻塞
- 通过回调 on_progress(step, message) 报告进度
- 返回 StepResult 列表，标注每步成功/失败/需手动
- 依赖：pywin32（win32gui/win32con），已随 snap7 安装
"""
import os
import sys
import time
import ctypes
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Optional

try:
    import win32gui
    import win32con
    import win32api
    import win32clipboard
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


# ---------------- 结果类型 ----------------

@dataclass
class StepResult:
    step: int          # 步骤序号
    name: str          # 步骤名称
    success: bool      # 是否成功
    manual: bool = False  # 是否需要手动完成（非自动化能力范围）
    message: str = ""  # 结果/错误/引导信息


# ---------------- MCGS 窗口识别 ----------------

MCGS_MAIN_TITLE_KEYWORDS = ("mcgspro组态环境", "mcgs组态环境", "mcgspro", "mcgset")


def find_mcgs_setpro_window() -> Optional[int]:
    """找到 McgsSetPro 主窗口 hwnd。"""
    if not HAS_WIN32:
        return None
    target = None

    def cb(h, _):
        nonlocal target
        if not win32gui.IsWindowVisible(h):
            return
        title = win32gui.GetWindowText(h).lower()
        if any(k in title for k in MCGS_MAIN_TITLE_KEYWORDS):
            target = h
            return True

    win32gui.EnumWindows(cb, None)
    return target


def bring_window_to_front(hwnd: int) -> bool:
    """把窗口置顶并激活。"""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        return True
    except Exception:
        return False


# ---------------- MCGS 自动化写入器 ----------------

class MCGSAutoWriter:
    """MCGS 组态自动写入器。

    用 win32gui 模拟用户操作，将 AI 生成的素材自动写入 MCGS 工程。
    每步独立执行，失败不阻塞后续步骤。

    使用：
        writer = MCGSAutoWriter(scada, mcgs_exe_path)
        results = writer.run(on_progress=lambda step, msg: print(f"[{step}] {msg}"))
        # results 是 StepResult 列表
    """

    STEPS = [
        (0, "启动/激活 MCGS"),
        (1, "自动导入设备通道 CSV"),
        (2, "自动粘贴 McgsScript 脚本"),
        (3, "数据对象（变量）创建 — 需手动完成"),
    ]

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

        if not HAS_WIN32:
            self.results.append(StepResult(0, "环境检查", False, message="缺少 pywin32（win32gui），无法进行 UI 自动化"))
            return self.results

        # Step 0: 启动/激活 MCGS
        self._progress(0, "正在启动/激活 MCGS 组态环境……")
        ok = self._ensure_mcgs_running()
        self.results.append(StepResult(0, "启动/激活 MCGS", ok, message="ok" if ok else "MCGS 未启动且无法自动启动"))

        if not ok:
            # MCGS 没起来，后续步骤也做不了
            self._add_temp_files()  # 至少确保 CSV 和脚本文件存在
            self._progress(0, "MCGS 未就绪，后续步骤跳过。请手动启动 MCGS 后重试。")
            return self.results + [
                StepResult(1, "导入 CSV", False, message="MCGS 未就绪"),
                StepResult(2, "粘贴脚本", False, message="MCGS 未就绪"),
                StepResult(3, "数据对象", False, manual=True, message="需手动创建"),
            ]

        # Step 1: 导入设备通道 CSV
        self._progress(1, "正在自动导入设备通道 CSV……")
        self._add_temp_files()
        ok, msg = self._import_device_channels_csv()
        self.results.append(StepResult(1, "导入设备通道 CSV", ok, message=msg))

        # Step 2: 粘贴脚本
        self._progress(2, "正在自动粘贴 McgsScript……")
        ok, msg = self._paste_script()
        self.results.append(StepResult(2, "粘贴 McgsScript", ok, message=msg))

        # Step 3: 数据对象（必须手动）
        self._progress(3, "数据对象需手动创建……")
        self.results.append(StepResult(3, "数据对象创建", False, manual=True,
            message="MCGS 无批量创建数据对象的 API/UI 入口，请对照变量字典在实时数据库中逐条新建。\n"
                    "变量数：{}，详见导出包的「变量字典.csv」。".format(len(self.scada["variables"]))))

        # 清理临时文件（保留 CSV 和脚本，方便用户手动导入）
        # self._cleanup_temp_files()  # 先不清理，让用户可以手动导入

        return self.results

    # ---------- 准备临时文件 ----------
    def _add_temp_files(self):
        """把 CSV 和脚本保存到临时目录，供 MCGS 文件选择对话框导入。"""
        tmp_dir = os.path.join(os.environ.get("TEMP", ""), "STEP7_AI_MCGS")
        os.makedirs(tmp_dir, exist_ok=True)
        self._csv_path = os.path.join(tmp_dir, "device_channels.csv")
        self._script_path = os.path.join(tmp_dir, "mcgs_script.mcs")
        with open(self._csv_path, "w", encoding="utf-8-sig") as f:
            f.write(self.scada["device_channels_csv"])
        with open(self._script_path, "w", encoding="utf-8") as f:
            f.write(self.scada["script"])

    # ---------- Step 0: 启动/激活 MCGS ----------
    def _ensure_mcgs_running(self) -> bool:
        hwnd = find_mcgs_setpro_window()
        if hwnd:
            return bring_window_to_front(hwnd)

        # 尝试启动（需要管理员权限）
        if self.mcgs_exe_path and os.path.isfile(self.mcgs_exe_path):
            self._progress(0, f"MCGS 未运行，尝试启动：{self.mcgs_exe_path}")
            try:
                # ShellExecuteW "runas" 请求 UAC 提升
                ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", self.mcgs_exe_path, None,
                    os.path.dirname(self.mcgs_exe_path), 1
                )
                # 等待窗口出现
                for _ in range(30):  # 最多等 15 秒
                    time.sleep(0.5)
                    hwnd = find_mcgs_setpro_window()
                    if hwnd:
                        return bring_window_to_front(hwnd)
            except Exception as e:
                self._progress(0, f"启动失败：{e}")

        return False

    # ---------- Step 1: 导入设备通道 CSV ----------
    def _import_device_channels_csv(self) -> tuple:
        """在 MCGS 设备窗口右键 → 设备信息导入 → 选 CSV 文件。

        返回 (success: bool, message: str)。
        """
        hwnd = find_mcgs_setpro_window()
        if not hwnd:
            return False, "MCGS 主窗口未找到"
        bring_window_to_front(hwnd)

        try:
            # 方案 A：通过 MCGS 菜单触发导入
            # McgsSetPro 的主菜单是标准 MFC 菜单
            if self._menu_select_by_text(hwnd, ["设备", "设备信息导入"]):
                time.sleep(0.5)
                # 弹出文件选择对话框
                ok, msg = self._handle_file_dialog(self._csv_path)
                if ok:
                    time.sleep(1.0)  # 等待导入完成
                    return True, "设备通道 CSV 已自动导入"
                return False, f"文件选择对话框处理失败：{msg}"

            # 方案 B：右键设备窗口区域 → 设备信息导入
            self._progress(1, "菜单未找到，尝试右键菜单方式……")
            ok, msg = self._device_window_right_menu_import(hwnd)
            return ok, msg

        except Exception as e:
            return False, f"导入异常：{e}"

    def _menu_select_by_text(self, hwnd: int, menu_path: list) -> bool:
        """通过主菜单栏选择菜单项（MFC 标准菜单）。"""
        try:
            hmenu = win32gui.GetMenu(hwnd)
            if not hmenu:
                return False

            # 递归查找子菜单
            def find_menu_item(hmenu, text, depth=0):
                count = win32gui.GetMenuItemCount(hmenu)
                for i in range(count):
                    try:
                        info = win32gui.GetMenuItemInfo(hmenu, i, True)
                        item_text = info.get('text', '') if isinstance(info, dict) else ''
                        if text in item_text:
                            return hmenu, i, info
                        # 递归子菜单
                        if info.get('fType', 0) & win32con.MFT_STRING:
                            sub = win32gui.GetSubMenu(hmenu, i)
                            if sub:
                                result = find_menu_item(sub, text, depth + 1)
                                if result:
                                    return result
                    except Exception:
                        continue
                return None

            # 逐级选择菜单项
            current_hmenu = hmenu
            parent_hwnd = hwnd
            for i, text in enumerate(menu_path):
                result = find_menu_item(current_hmenu, text)
                if not result:
                    return False
                target_menu, target_idx, target_info = result
                if i == len(menu_path) - 1:
                    # 最后一级，执行
                    win32gui.PostMessage(parent_hwnd, win32con.WM_COMMAND,
                                        win32con.MAKEWPARAM(target_idx, 0), target_menu)
                    return True
                else:
                    # 展开子菜单（通常 MFC 会自动显示，这里先尝试直接 PostMessage）
                    win32gui.PostMessage(parent_hwnd, win32con.WM_COMMAND,
                                        win32con.MAKEWPARAM(target_idx, 0), target_menu)
                    time.sleep(0.3)
                    # 获取新的活动菜单
                    current_hmenu = win32gui.GetMenu(parent_hwnd)

            return False
        except Exception:
            return False

    def _device_window_right_menu_import(self, hwnd: int) -> tuple:
        """在设备窗口列表区域右键 → 选设备信息导入。"""
        # 找 McgsSetPro 主窗口内的 SysListView32（设备/变量列表）
        list_views = []
        def find_lv(child, _):
            cls = win32gui.GetClassName(child)
            if cls == "SysListView32":
                list_views.append(child)
        win32gui.EnumChildWindows(hwnd, find_lv, None)

        if not list_views:
            return False, "未找到设备窗口列表控件"

        # 在第一个 SysListView32 上右键
        lv = list_views[0]
        rect = win32gui.GetWindowRect(lv)
        click_x = (rect[0] + rect[2]) // 2
        click_y = (rect[1] + rect[3]) // 2

        # 模拟点击 → 选中 → 右键
        self._click(click_x, click_y)
        time.sleep(0.2)
        self._click(click_x, click_y, button="right")
        time.sleep(0.5)

        # 找弹出的菜单窗口
        popup_hwnd = None
        def find_popup(h, _):
            nonlocal popup_hwnd
            cls = win32gui.GetClassName(h)
            if cls == "#32768":  # 弹出菜单类名
                popup_hwnd = h
        win32gui.EnumWindows(find_popup, None)

        if popup_hwnd:
            # 扫描菜单项找"设备信息导入"
            import ctypes
            buf = ctypes.create_unicode_buffer(256)
            for i in range(20):  # 最多 20 项
                try:
                    win32gui.GetMenuString(popup_hwnd, i, buf, 256, 0x0004)  # MENU_STRING
                    if "导入" in buf.value or "设备" in buf.value:
                        # 执行该项
                        win32gui.PostMessage(hwnd, win32con.WM_COMMAND,
                                             win32con.MAKEWPARAM(i, 0), popup_hwnd)
                        time.sleep(0.5)
                        ok, msg = self._handle_file_dialog(self._csv_path)
                        if ok:
                            return True, "设备通道 CSV 已自动导入（右键方式）"
                        return False, msg
                except Exception:
                    break

        # 兜底：用键盘 Alt+E 打开编辑菜单，然后搜"导入"
        return False, "自动导入失败，请手动：设备窗口 → 右键 → 设备信息导入 → 选择 CSV 文件"

    def _handle_file_dialog(self, target_path: str) -> tuple:
        """处理 MCGS 弹出的文件选择对话框。

        尝试：先找标准 Windows 文件对话框（#32770），然后在文件名框粘贴路径。
        """
        time.sleep(1.0)

        # 找文件对话框
        dlg = None
        def find_dlg(h, _):
            nonlocal dlg
            cls = win32gui.GetClassName(h)
            if cls == "#32770" and win32gui.IsWindowVisible(h):
                dlg = h
        win32gui.EnumWindows(find_dlg, None)

        if not dlg:
            # 可能没有弹对话框（菜单路径不对）
            return False, "未弹出文件选择对话框"

        # 激活对话框
        bring_window_to_front(dlg)
        time.sleep(0.3)

        # 在 Edit 控件里输入文件路径（文件名输入框）
        edit_ctrls = []
        def find_edit(child, _):
            cls = win32gui.GetClassName(child)
            if cls == "Edit":
                edit_ctrls.append(child)
        win32gui.EnumChildWindows(dlg, find_edit, None)

        if edit_ctrls:
            edit = edit_ctrls[0]
            # 清空 + 粘贴完整路径
            win32gui.SendMessage(edit, win32con.WM_SETTEXT, 0, target_path)
            time.sleep(0.2)

        # 点击「打开」按钮
        buttons = []
        def find_btn(child, _):
            cls = win32gui.GetClassName(child)
            title = win32gui.GetWindowText(child)
            if cls == "Button" and ("打开" in title or "Open" in title or "确定" in title):
                buttons.append(child)
        win32gui.EnumChildWindows(dlg, find_btn, None)

        if buttons:
            win32gui.SendMessage(buttons[0], win32con.BM_CLICK, 0, 0)
            time.sleep(1.0)
            return True, "文件选择对话框已处理"

        # 兜底：按 Enter
        win32api.keybd_event(0x0D, 0, 0, 0)
        win32api.keybd_event(0x0D, 0, 2, 0)  # KEYEVENTF_KEYUP
        time.sleep(1.0)
        return True, "文件选择对话框已处理（Enter 兜底）"

    # ---------- Step 2: 粘贴脚本 ----------
    def _paste_script(self) -> tuple:
        """把 McgsScript 粘贴到 MCGS 脚本编辑器。

        脚本编辑器可能在：
        - 运行策略 → 策略属性 → 脚本编辑
        - 窗口属性 → 循环脚本
        - 控件事件 → 事件脚本

        这里采取**剪贴板 + 快捷键**的通用方式：用户打开脚本编辑器后，
        我们把脚本放入剪贴板并发送 Ctrl+A（全选）+ Ctrl+V（粘贴）。
        """
        hwnd = find_mcgs_setpro_window()
        if not hwnd:
            return False, "MCGS 主窗口未找到"
        bring_window_to_front(hwnd)

        try:
            # 把脚本放入剪贴板
            script_text = self.scada.get("script", "")
            if not script_text.strip():
                return False, "脚本内容为空"

            script_bytes = script_text.encode("utf-16-le")
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, script_bytes)
            win32clipboard.CloseClipboard()

            # 发送 Ctrl+A（全选）然后 Ctrl+V（粘贴）
            self._send_hotkey([0x11, 0x41])  # Ctrl+A
            time.sleep(0.2)
            self._send_hotkey([0x11, 0x56])  # Ctrl+V
            time.sleep(0.3)

            return True, "脚本已粘贴到当前活动的文本框（请在 MCGS 中打开脚本编辑器后重试粘贴，或手动 Ctrl+V）"

        except Exception as e:
            return False, f"粘贴失败：{e}。请手动打开脚本编辑器，然后 Ctrl+V 粘贴。脚本已在剪贴板。"

    # ---------- 辅助：鼠标/键盘 ----------
    def _click(self, x: int, y: int, button: str = "left"):
        """模拟鼠标点击。"""
        MOUSEEVENTF_MOVE = 0x0001
        MOUSEEVENTF_ABSOLUTE = 0x8000
        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004
        MOUSEEVENTF_RIGHTDOWN = 0x0008
        MOUSEEVENTF_RIGHTUP = 0x0010

        # 移动到绝对坐标
        screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        screen_h = ctypes.windll.user32.GetSystemMetrics(1)
        abs_x = int(x * 65535 / screen_w)
        abs_y = int(y * 65535 / screen_h)

        ctypes.windll.user32.SetCursorPos(x, y)
        time.sleep(0.05)

        if button == "right":
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, abs_x, abs_y, 0, 0)
            time.sleep(0.05)
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTUP, abs_x, abs_y, 0, 0)
        else:
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, abs_x, abs_y, 0, 0)
            time.sleep(0.05)
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, abs_x, abs_y, 0, 0)

    def _send_hotkey(self, vkeys: list):
        """发送组合键（如 [Ctrl, A]）。"""
        # 按下所有键
        for vk in vkeys:
            win32api.keybd_event(vk, 0, 0, 0)
            time.sleep(0.02)
        # 松开（逆序）
        for vk in reversed(vkeys):
            win32api.keybd_event(vk, 0, 2, 0)
            time.sleep(0.02)
