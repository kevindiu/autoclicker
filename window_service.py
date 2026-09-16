import ctypes
import threading
import time

from theme import BASE_WINDOW_TITLE, WINDOW_TITLE
from win32_api import (
    user32,
    WNDENUMPROC,
    force_bring_window_to_front,
    is_window_alive,
)


class WindowService:
    """視窗綁定與目標視窗選擇邏輯的專門服務，與 Tk UI 分離。"""

    def __init__(self, app):
        self.app = app

    def get_window_list(self):
        if not user32:
            return []
        windows = []

        def enum_proc(hwnd, lParam):
            if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
                buff = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
                user32.GetWindowTextW(hwnd, buff, len(buff))
                title = buff.value.strip()
                if title and BASE_WINDOW_TITLE not in title:
                    windows.append((hwnd, title))
            return True

        cb = WNDENUMPROC(enum_proc)
        user32.EnumWindows(cb, 0)
        return windows

    def _resolve_window_index(self, win_list, current_hwnd=None):
        target_idx = 0
        found_target = False
        found_fallback = False
        fallback_idx = 0

        for i, (hwnd, title) in enumerate(win_list):
            if current_hwnd is not None and hwnd == current_hwnd:
                target_idx = i
                found_target = True
            elif not found_fallback and ("水滸" in title or "online" in title.lower()):
                fallback_idx = i
                found_fallback = True

        if found_target:
            return target_idx
        if found_fallback:
            return fallback_idx
        return target_idx

    def bind_target_window(self, hwnd):
        self.app.app_state.target_hwnd = hwnd
        if hwnd:
            self.app.set_status(f"已綁定目標視窗 HWND: {hwnd}")
        return hwnd

    def refresh_window_dropdown(self):
        win_list = self.get_window_list()
        if not win_list:
            self.app.app_state.target_hwnd = None
            self.app.cbo_window["values"] = ["未偵測到任何視窗"]
            self.app.cbo_window.current(0)
            return

        target_idx = self._resolve_window_index(win_list, self.app.app_state.target_hwnd)
        items = [f"[{hwnd}] {title}" for hwnd, title in win_list]
        self.app.cbo_window["values"] = items
        self.app.cbo_window.current(target_idx)
        self.bind_target_window(win_list[target_idx][0])

    def on_window_select(self, event=None):
        val = self.app.var_window.get()
        if not val or not val.startswith("["):
            return
        try:
            hwnd = int(val.split("]")[0].replace("[", ""))
            self.bind_target_window(hwnd)
        except (ValueError, IndexError) as e:
            self.app.app_state.target_hwnd = None
            self.app.append_log("警示", f"視窗綁定解析失敗: {e}")

    def force_bring_window_to_front(self, hwnd):
        force_bring_window_to_front(hwnd)

    def force_bring_self_to_front(self):
        if self.app.is_closing:
            return
        self.app.deiconify()
        self.app.lift()
        self.app.focus_force()
        if user32:
            hwnd_self = user32.FindWindowW(None, WINDOW_TITLE)
            if hwnd_self:
                force_bring_window_to_front(hwnd_self)

    def locate_target_window(self):
        if not self.app.app_state.target_hwnd or not user32:
            return self.app.set_status("未綁定有效視窗，無法定位！")

        hwnd = self.app.app_state.target_hwnd
        try:
            force_bring_window_to_front(hwnd)

            def _flash_worker():
                for _ in range(4):
                    if not self.app.is_closing and is_window_alive(hwnd):
                        try:
                            user32.FlashWindow(hwnd, True)
                        except (OSError, ctypes.ArgumentError):
                            break
                        time.sleep(0.08)
                    else:
                        break

            threading.Thread(target=_flash_worker, daemon=True).start()
            self.app.set_status(f"已定位並閃爍視窗 HWND: {hwnd}")
        except Exception as e:
            self.app.append_log("警示", f"視窗定位失敗: {e}")
