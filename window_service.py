import ctypes

from theme import BASE_WINDOW_TITLE
from win32_api import user32, WNDENUMPROC


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

    def refresh_window_dropdown(self):
        win_list = self.get_window_list()
        items, target_idx = [], 0
        current_hwnd = self.app.app_state.target_hwnd
        found_target = False
        found_fallback = False
        fallback_idx = 0

        for i, (hwnd, title) in enumerate(win_list):
            items.append(f"[{hwnd}] {title}")
            if current_hwnd is not None and hwnd == current_hwnd:
                target_idx = i
                found_target = True
            elif not found_fallback and ("水滸" in title or "online" in title.lower()):
                fallback_idx = i
                found_fallback = True

        if not found_target and found_fallback:
            target_idx = fallback_idx

        if not items:
            items, self.app.app_state.target_hwnd = ["未偵測到任何視窗"], None
        else:
            self.app.app_state.target_hwnd = win_list[target_idx][0]

        self.app.cbo_window["values"] = items
        self.app.cbo_window.current(target_idx)
        if self.app.app_state.target_hwnd:
            self.app.set_status(f"已綁定目標視窗 HWND: {self.app.app_state.target_hwnd}")

    def on_window_select(self, event=None):
        val = self.app.var_window.get()
        if val and val.startswith("["):
            try:
                self.app.app_state.target_hwnd = int(val.split("]")[0].replace("[", ""))
                self.app.set_status(f"已綁定目標視窗 HWND: {self.app.app_state.target_hwnd}")
            except (ValueError, IndexError) as e:
                self.app.app_state.target_hwnd = None
                self.app.append_log("警示", f"視窗綁定解析失敗: {e}")
