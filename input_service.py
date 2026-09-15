import ctypes
import tkinter as tk

from theme import UITheme
from win32_api import (
    VK_SPACE,
    VK_ESCAPE,
    KEY_PRESSED_MASK,
    user32,
    POINT,
    get_cursor_pos,
)


class InputService:
    """處理滑鼠取點、按鍵捕捉與 UI 互動，讓 App 只承擔 UI 協調。"""

    def __init__(self, app):
        self.app = app

    def capture_pos_space(self, on_finish, on_cancel=None, btn="left"):
        app_state = self.app.app_state
        if not app_state.target_hwnd:
            self.app.messagebox.showwarning("提示", "尚未綁定目標視窗，請先在上方選擇遊戲視窗！", parent=self.app)
            if on_cancel:
                on_cancel()
            return

        btn_cn = "右鍵" if btn == "right" else "左鍵"
        self.app.force_bring_window_to_front(app_state.target_hwnd)
        self.app.set_status(f"【設定{btn_cn}點擊】遊戲已置頂！請將滑鼠指住目標，按 [SPACE 空白鍵] 確定")

        banner = tk.Toplevel(self.app)
        banner.overrideredirect(True)
        banner.attributes("-topmost", True)
        banner.configure(bg=UITheme.ACCENT_BLUE)

        sw = self.app.winfo_screenwidth()
        bw, bh = 780, 46
        bx = max(0, (sw - bw) // 2)
        by = 12
        banner.geometry(f"{bw}x{bh}+{bx}+{by}")

        inner_frame = tk.Frame(banner, bg=UITheme.BANNER_BG, padx=10, pady=4)
        inner_frame.pack(fill="both", expand=True, padx=2, pady=2)

        lbl_hud = tk.Label(
            inner_frame,
            text=f"【設定{btn_cn}點擊】將滑鼠指住目標 -> 按 [SPACE 空白鍵] 確定！(按 ESC 取消)",
            bg=UITheme.BANNER_BG,
            fg=UITheme.CYAN_TITLE,
            font=UITheme.FONT_TITLE,
        )
        lbl_hud.pack(fill="both", expand=True)

        if user32:
            user32.GetAsyncKeyState(VK_SPACE)
            user32.GetAsyncKeyState(VK_ESCAPE)

        is_handled = [False]

        def poll_keys():
            if not banner.winfo_exists() or is_handled[0]:
                return

            pos_x, pos_y = get_cursor_pos()
            if app_state.target_hwnd and self.app.var_use_rel.get() and user32:
                pt = POINT(int(pos_x), int(pos_y))
                user32.ScreenToClient(app_state.target_hwnd, ctypes.byref(pt))
                coord_desc = f"({pt.x}, {pt.y})"
                rx, ry, rel = pt.x, pt.y, True
            else:
                coord_desc = f"({pos_x}, {pos_y})"
                rx, ry, rel = pos_x, pos_y, False

            lbl_hud.config(text=f"【設定{btn_cn}點擊】滑鼠指住目標 -> 按 [SPACE 空白鍵] 確定！(坐標: {coord_desc} | ESC 取消)")

            if user32:
                if user32.GetAsyncKeyState(VK_SPACE) & KEY_PRESSED_MASK:
                    is_handled[0] = True
                    banner.destroy()
                    self.app.force_bring_self_to_front()
                    self.app.set_status(f"已成功設定{btn_cn}位置: ({rx}, {ry})")
                    on_finish(rx, ry, rel)
                    return

                if user32.GetAsyncKeyState(VK_ESCAPE) & KEY_PRESSED_MASK:
                    is_handled[0] = True
                    banner.destroy()
                    self.app.force_bring_self_to_front()
                    self.app.set_status("已取消設定位置")
                    if on_cancel:
                        on_cancel()
                    return

            banner.after(30, poll_keys)

        self.app.after(150, poll_keys)
