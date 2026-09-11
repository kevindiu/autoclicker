import os
import sys
import json
import time
import copy
import ctypes
from ctypes import wintypes
import threading
import queue
import pyautogui
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from theme import UITheme, resource_path, WINDOW_TITLE, CONFIG_EXT
import state
from state import format_action_summary
from win32_api import (
    IS_WINDOWS,
    user32,
    POINT,
    WNDENUMPROC,
    safe_sleep,
    emergency_release_all,
    execute_click,
    post_bg_key,
    force_bring_window_to_front
)
from widgets import VarTable
import dialogs
import engine

# ==============================================================================
# 全域資料與相容別名 (提供相容性與外部腳本直接存取)
# ==============================================================================
combos = state.combos
steps = state.steps
variables = state.variables
active_steps = state.active_steps
active_combos = state.active_combos
active_variables = state.active_variables
steps_lock = state.steps_lock
stop_event = state.stop_event

# ==============================================================================
# 原生 Tkinter GUI 主應用程式
# ==============================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("1280x750")
        self.minsize(1200, 700)
        self.resizable(True, True)
        self.configure(bg=UITheme.BG_DARK)

        self.is_closing = False
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.apply_app_icon()

        # 全域字體配置 (增強微軟正黑體 UI 顯示效果)
        self.option_add("*Font", UITheme.FONT_NORMAL)
        try:
            style = ttk.Style()
            style.configure("TCombobox", font=UITheme.FONT_NORMAL)
            self.option_add("*TCombobox*Listbox.font", UITheme.FONT_NORMAL)
        except Exception:
            pass

        # 頂部全域設定變數
        self.var_profile_name = tk.StringVar()
        self.var_use_bg = tk.BooleanVar(value=True)
        self.var_use_rel = tk.BooleanVar(value=True)
        self.var_topmost = tk.BooleanVar(value=False)
        self.var_offset_x = tk.StringVar(value="0")
        self.var_offset_y = tk.StringVar(value="0")
        self.var_window = tk.StringVar(value="未偵測到視窗")

        # 執行緒安全的快取設定 (避免子執行緒讀取 Tkinter Variable 引發 Tcl 鎖定或例外)
        self.cached_use_bg = True
        self.cached_use_rel = True
        self.cached_offset_x = 0
        self.cached_offset_y = 0

        self.var_use_bg.trace_add("write", lambda *a: setattr(self, "cached_use_bg", bool(self.var_use_bg.get())))
        self.var_use_rel.trace_add("write", lambda *a: setattr(self, "cached_use_rel", bool(self.var_use_rel.get())))
        def _update_offset(*a):
            try: self.cached_offset_x = int(self.var_offset_x.get() or 0)
            except Exception: self.cached_offset_x = 0
            try: self.cached_offset_y = int(self.var_offset_y.get() or 0)
            except Exception: self.cached_offset_y = 0
        self.var_offset_x.trace_add("write", _update_offset)
        self.var_offset_y.trace_add("write", _update_offset)

        # 組合管理變數
        self.var_combo_name = tk.StringVar(value="新組合")
        self.var_combo_act_key = tk.StringVar(value="f1")
        self.var_combo_act_wait = tk.StringVar(value="0.5")
        self.var_combo_to_call = tk.StringVar()
        self.var_combo_btn = tk.StringVar(value="左鍵")
        self.var_combo_manual_x = tk.StringVar(value="0")
        self.var_combo_manual_y = tk.StringVar(value="0")
        self.var_combo_ref_var = tk.StringVar()

        # 主流程步驟變數
        self.var_step_key = tk.StringVar(value="f1")
        self.var_step_wait = tk.StringVar(value="1.0")
        self.var_step_btn = tk.StringVar(value="左鍵")
        self.var_step_manual_x = tk.StringVar(value="0")
        self.var_step_manual_y = tk.StringVar(value="0")
        self.var_step_combo_to_call = tk.StringVar()
        self.var_step_ref_var = tk.StringVar()

        self.last_active_step_idx = None

        self.grid_columnconfigure(0, weight=6)
        self.grid_columnconfigure(1, weight=5)
        self.grid_rowconfigure(0, weight=1)

        self.build_left_panel()
        self.build_right_panel()
        self.refresh_window_dropdown()
        self.refresh_profiles()
        self.load_config()
        self.refresh_variables_table()
        self.track_mouse_live()

        # 執行緒安全的 UI 通訊佇列
        self.status_queue = queue.Queue()
        self.ui_task_queue = queue.Queue()
        self.poll_ui_queues()

    def apply_app_icon(self, target=None):
        """為指定視窗 (預設為主視窗) 套用應用程式圖示 (支援 Windows .ico 與通用 .png)"""
        win = target or self
        try:
            ico_path = resource_path("app.ico")
            png_path = resource_path("app.png")
            if sys.platform == "win32" and os.path.exists(ico_path):
                win.iconbitmap(ico_path)
            elif os.path.exists(png_path):
                img = tk.PhotoImage(file=png_path)
                win.iconphoto(True, img)
        except Exception:
            pass

    def on_close(self):
        """主視窗關閉事件處理"""
        self.is_closing = True
        state.running = False
        state.stop_event.set()
        emergency_release_all()
        self.destroy()

    def toggle_topmost(self):
        """切換助手視窗置頂狀態"""
        self.attributes("-topmost", self.var_topmost.get())

    def poll_ui_queues(self):
        """定期由主執行緒消費背景執行緒發送的 UI 更新事件 (批次摺疊更新，避免頻繁渲染)"""
        if self.is_closing: return
        last_msg = None
        try:
            while True:
                last_msg = self.status_queue.get_nowait()
        except (queue.Empty, Exception):
            pass
        if last_msg is not None and hasattr(self, "lbl_status") and self.lbl_status.winfo_exists():
            self.lbl_status.config(text=f"● 狀態: {last_msg}")

        while True:
            try:
                fn = self.ui_task_queue.get_nowait()
            except (queue.Empty, Exception):
                break
            try:
                fn()
            except Exception:
                pass
        if not self.is_closing:
            self.after(50, self.poll_ui_queues)

    def set_status(self, msg):
        """執行緒安全地更新狀態列訊息"""
        if not self.is_closing:
            try:
                if threading.current_thread() is threading.main_thread() and hasattr(self, "lbl_status") and self.lbl_status.winfo_exists():
                    self.lbl_status.config(text=f"● 狀態: {msg}")
                else:
                    self.status_queue.put(msg)
            except Exception:
                pass

    def run_on_ui_thread(self, fn):
        """在主執行緒安全執行 UI 變更回調"""
        if not self.is_closing:
            try:
                if threading.current_thread() is threading.main_thread():
                    fn()
                else:
                    self.ui_task_queue.put(fn)
            except Exception:
                pass

    def set_running_ui(self, is_running, is_test=False):
        """執行緒安全地更新啟動/停止按鈕 UI"""
        def _u():
            if self.is_closing: return
            if is_running:
                btn_text = "■ 停止試跑" if is_test else "■ 停止運行"
                self.btn_toggle.config(text=btn_text, bg=UITheme.ACCENT_RED, activebackground=UITheme.ACCENT_RED_HOVER)
            else:
                self.btn_toggle.config(text="▶ 開始循環執行", bg=UITheme.ACCENT_GREEN, activebackground=UITheme.ACCENT_GREEN_HOVER)
                if hasattr(self, "step_listbox") and self.step_listbox.winfo_exists():
                    last_idx = getattr(self, "last_active_step_idx", None)
                    if last_idx is not None and 0 <= last_idx < self.step_listbox.size():
                        try:
                            self.step_listbox.itemconfigure(last_idx, background=UITheme.BG_DARK, foreground=UITheme.TEXT_MAIN)
                        except Exception:
                            pass
                    self.last_active_step_idx = None
        self.run_on_ui_thread(_u)

    def run_in_test_thread(self, task_name, task_fn):
        """統一的非同步試跑安全守衛與執行緒啟動器"""
        if state.running:
            return self.set_status("巨集正在循環執行中，請先停止再試跑！")
        if state.is_testing:
            return self.set_status("已有試跑任務正在執行中，請稍候！")

        def _worker():
            state.is_testing = True
            state.stop_event.clear()
            self.set_running_ui(True, is_test=True)
            try:
                self.set_status(f"正在試跑 {task_name}...")
                task_fn()
                if state.stop_event.is_set():
                    self.set_status(f"{task_name} 試跑已手動中止！")
                else:
                    self.set_status(f"{task_name} 試跑完成！")
            except Exception as e:
                self.set_status(f"{task_name} 試跑異常: {e}")
            finally:
                state.is_testing = False
                emergency_release_all()
                self.set_running_ui(False)

        threading.Thread(target=_worker, daemon=True).start()

    def track_mouse_live(self):
        """實時監控游標坐標並更新 HUD (具備坐標變更感知，無移動不消耗重繪資源)"""
        if self.is_closing:
            return
        try:
            pos = pyautogui.position()
            if IS_WINDOWS and state.target_hwnd and getattr(self, "cached_use_rel", True) and user32:
                pt = POINT(int(pos.x), int(pos.y))
                user32.ScreenToClient(state.target_hwnd, ctypes.byref(pt))
                new_text = f"游標實時坐標(相對): ({pt.x}, {pt.y})"
            else:
                new_text = f"游標實時坐標(螢幕): ({pos.x}, {pos.y})"
            if new_text != getattr(self, "_last_mouse_hud_text", None):
                self._last_mouse_hud_text = new_text
                self.lbl_mouse_hud.config(text=new_text)
        except Exception:
            pass
        if not self.is_closing:
            self.after(150, self.track_mouse_live)

    def force_bring_window_to_front(self, hwnd):
        """強制喚醒並將目標視窗置頂最前"""
        force_bring_window_to_front(hwnd)

    def force_bring_self_to_front(self):
        """將連點器主視窗置頂彈回最前"""
        if self.is_closing: return
        self.deiconify()
        self.lift()
        self.focus_force()
        if IS_WINDOWS and user32:
            hwnd_self = user32.FindWindowW(None, WINDOW_TITLE)
            if hwnd_self:
                force_bring_window_to_front(hwnd_self)

    def locate_target_window(self):
        """定位並閃爍目標遊戲視窗"""
        if not IS_WINDOWS or not state.target_hwnd or not user32:
            return self.set_status("未綁定有效視窗，無法定位！")

        try:
            force_bring_window_to_front(state.target_hwnd)
            for _ in range(4):
                user32.FlashWindow(state.target_hwnd, True)
                time.sleep(0.08)
            self.set_status(f"已定位並閃爍視窗 HWND: {state.target_hwnd}")
        except Exception as e:
            self.set_status(f"定位失敗: {e}")

    # ======================= 取點防重入機制 + 頂部提示 =======================
    def capture_pos_space(self, on_finish, on_cancel=None, btn="left"):
        """無干擾 Hover 取點模式：頂部浮動 HUD，按 Space 確定，按 ESC 取消"""
        if not state.target_hwnd:
            messagebox.showwarning("提示", "尚未綁定目標視窗，請先在上方選擇遊戲視窗！", parent=self)
            if on_cancel: on_cancel()
            return

        btn_cn = "右鍵" if btn == "right" else "左鍵"
        force_bring_window_to_front(state.target_hwnd)
        self.set_status(f"【設定{btn_cn}點擊】遊戲已置頂！請將滑鼠指住目標，按 [SPACE 空白鍵] 確定")

        banner = tk.Toplevel(self)
        banner.overrideredirect(True)
        banner.attributes("-topmost", True)
        banner.configure(bg=UITheme.ACCENT_BLUE)

        sw = self.winfo_screenwidth()
        bw, bh = 780, 46
        bx = max(0, (sw - bw) // 2)
        by = 12
        banner.geometry(f"{bw}x{bh}+{bx}+{by}")

        inner_frame = tk.Frame(banner, bg="#0f172a", padx=10, pady=4)
        inner_frame.pack(fill="both", expand=True, padx=2, pady=2)

        lbl_hud = tk.Label(
            inner_frame,
            text=f"【設定{btn_cn}點擊】將滑鼠指住目標 -> 按 [SPACE 空白鍵] 確定！(按 ESC 取消)",
            bg="#0f172a",
            fg=UITheme.CYAN_TITLE,
            font=UITheme.FONT_TITLE
        )
        lbl_hud.pack(fill="both", expand=True)

        if IS_WINDOWS and user32:
            user32.GetAsyncKeyState(0x20)
            user32.GetAsyncKeyState(0x1B)

        is_handled = [False]

        def poll_keys():
            if not banner.winfo_exists() or is_handled[0]:
                return

            pos = pyautogui.position()
            if IS_WINDOWS and state.target_hwnd and self.var_use_rel.get() and user32:
                pt = POINT(int(pos.x), int(pos.y))
                user32.ScreenToClient(state.target_hwnd, ctypes.byref(pt))
                coord_desc = f"({pt.x}, {pt.y})"
                rx, ry, rel = pt.x, pt.y, True
            else:
                coord_desc = f"({pos.x}, {pos.y})"
                rx, ry, rel = pos.x, pos.y, False

            lbl_hud.config(text=f"【設定{btn_cn}點擊】滑鼠指住目標 -> 按 [SPACE 空白鍵] 確定！(坐標: {coord_desc} | ESC 取消)")

            if IS_WINDOWS and user32:
                if user32.GetAsyncKeyState(0x20) & 0x8000:
                    is_handled[0] = True
                    banner.destroy()
                    self.force_bring_self_to_front()
                    self.set_status(f"已成功設定{btn_cn}位置: ({rx}, {ry})")
                    on_finish(rx, ry, rel)
                    return

                if user32.GetAsyncKeyState(0x1B) & 0x8000:
                    is_handled[0] = True
                    banner.destroy()
                    self.force_bring_self_to_front()
                    self.set_status("已取消設定位置")
                    if on_cancel: on_cancel()
                    return

            banner.after(30, poll_keys)

        self.after(150, poll_keys)

    # ======================= 主畫面執行步驟高亮跟隨 =======================
    def highlight_active_step(self, idx, sub_idx=None):
        """在主畫面清單中以獨立背景色高亮當前執行中的步驟，並根據設定自動滾動，絕不干擾使用者選取"""
        def _hl():
            if self.is_closing: return
            if not hasattr(self, "step_listbox") or not self.step_listbox.winfo_exists():
                return
            lb = self.step_listbox
            lb_sz = lb.size()
            last_idx = getattr(self, "last_active_step_idx", None)
            if last_idx is not None and 0 <= last_idx < lb_sz and last_idx != idx:
                try:
                    lb.itemconfigure(last_idx, background=UITheme.BG_DARK, foreground=UITheme.TEXT_MAIN)
                except Exception:
                    pass

            if 0 <= idx < lb_sz:
                try:
                    lb.itemconfigure(idx, background="#2a4365", foreground="#63b3ed")
                    self.last_active_step_idx = idx
                    lb.see(idx)
                except Exception:
                    pass
        self.run_on_ui_thread(_hl)

    # ======================= 次層級對話框委派 =======================
    def prompt_edit_combo_dialog(self, combo_step, step_idx=None):
        return dialogs.prompt_edit_combo_dialog(self, combo_step, step_idx=step_idx)

    def prompt_edit_action(self, action, available_combos=None, step_idx=None):
        return dialogs.prompt_edit_action(self, action, available_combos=available_combos, step_idx=step_idx)

    def prompt_variable_dialog(self, edit_name=None):
        return dialogs.prompt_variable_dialog(self, edit_name=edit_name)

    # ======================= 左欄佈局 =======================
    def build_left_panel(self):
        f_left = tk.Frame(self, bg=UITheme.BG_PANEL, padx=8, pady=8, highlightbackground=UITheme.BORDER, highlightthickness=1)
        f_left.grid(row=0, column=0, padx=(10, 5), pady=10, sticky="nsew")

        # 1. 設定與視窗綁定
        f_cfg = tk.LabelFrame(f_left, text=" 設定與視窗綁定 ", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_TITLE, padx=6, pady=4)
        f_cfg.pack(fill="x", pady=(0, 4))

        # 第 1 行: 設定檔管理 + 核心功能勾選 (背景掛機、相對坐標、視窗置頂)
        r1 = tk.Frame(f_cfg, bg=UITheme.BG_PANEL)
        r1.pack(fill="x", pady=(1, 2))
        tk.Label(r1, text="設定檔:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left")
        self.cbo_profile = ttk.Combobox(r1, textvariable=self.var_profile_name, width=14, state="readonly")
        self.cbo_profile.pack(side="left", padx=(3, 3))
        tk.Button(r1, text="載入", width=4, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.load_config).pack(side="left", padx=1)
        tk.Button(r1, text="儲存", width=4, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.save_config).pack(side="left", padx=1)
        tk.Button(r1, text="+ 新增", width=5, bg=UITheme.ACCENT_GREEN, fg="#fff", activebackground=UITheme.ACCENT_GREEN_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.create_new_profile).pack(side="left", padx=(1, 8))

        tk.Checkbutton(r1, text="背景掛機", variable=self.var_use_bg, bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, selectcolor=UITheme.BG_PANEL, activebackground=UITheme.BG_PANEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=2)
        tk.Checkbutton(r1, text="相對坐標", variable=self.var_use_rel, bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, selectcolor=UITheme.BG_PANEL, activebackground=UITheme.BG_PANEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=2)
        tk.Checkbutton(r1, text="視窗置頂", variable=self.var_topmost, command=self.toggle_topmost, bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, selectcolor=UITheme.BG_PANEL, activebackground=UITheme.BG_PANEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=2)

        # 第 2 行: 目標視窗綁定 + 重新整理/定位 + 偏差校正 X/Y
        r2 = tk.Frame(f_cfg, bg=UITheme.BG_PANEL)
        r2.pack(fill="x", pady=(2, 1))
        tk.Label(r2, text="目標視窗:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left")
        self.cbo_window = ttk.Combobox(r2, textvariable=self.var_window, width=16, state="readonly")
        self.cbo_window.pack(side="left", padx=(3, 3), fill="x", expand=True)
        self.cbo_window.bind("<<ComboboxSelected>>", self.on_window_select)
        tk.Button(r2, text="↻ 重新整理", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, padx=4, command=self.refresh_window_dropdown).pack(side="left", padx=1)
        tk.Button(r2, text="◎ 定位視窗", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, padx=4, command=self.locate_target_window).pack(side="left", padx=(1, 8))

        tk.Label(r2, text="偏差校正:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left")
        tk.Label(r2, text="X:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_NORMAL).pack(side="left", padx=(3, 1))
        tk.Entry(r2, textvariable=self.var_offset_x, width=3, bg=UITheme.BG_INPUT, fg="#ffffff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=1)
        tk.Label(r2, text="Y:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_NORMAL).pack(side="left", padx=(3, 1))
        tk.Entry(r2, textvariable=self.var_offset_y, width=3, bg=UITheme.BG_INPUT, fg="#ffffff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=1)

        # 2. 常用變數庫
        f_vars = tk.LabelFrame(
            f_left,
            text=" 常用變數庫 ",
            bg=UITheme.BG_PANEL,
            fg=UITheme.CYAN_TITLE,
            font=UITheme.FONT_TITLE,
            padx=6,
            pady=3
        )
        f_vars.pack(fill="x", pady=(0, 4))

        f_vars_row = tk.Frame(f_vars, bg=UITheme.BG_PANEL)
        f_vars_row.pack(fill="x", expand=True)

        self.tree_vars = VarTable(f_vars_row, on_double_click=self.edit_selected_variable)
        self.tree_vars.pack(side="left", fill="both", expand=True, padx=(0, 6))

        col_v_btns = tk.Frame(f_vars_row, bg=UITheme.BG_PANEL)
        col_v_btns.pack(side="right", fill="y")
        col_v_btns.grid_columnconfigure(0, weight=1)
        col_v_btns.grid_columnconfigure(1, weight=1)
        col_v_btns.grid_rowconfigure(0, weight=1)
        col_v_btns.grid_rowconfigure(1, weight=1)

        btn_var_add_main = tk.Button(
            col_v_btns,
            text="➔ 加入掛機流程",
            bg=UITheme.ACCENT_BLUE,
            fg="#fff",
            activebackground=UITheme.ACCENT_BLUE_HOVER,
            font=UITheme.FONT_SMALL_BOLD,
            relief="flat",
            padx=4,
            pady=2,
            command=self.add_variable_to_main_steps
        )
        btn_var_add_main.grid(row=0, column=0, padx=1, pady=1, sticky="nsew")

        tk.Button(
            col_v_btns,
            text="+ 新增變數",
            bg=UITheme.ACCENT_GREEN,
            fg="#fff",
            activebackground=UITheme.ACCENT_GREEN_HOVER,
            font=UITheme.FONT_SMALL_BOLD,
            relief="flat",
            padx=4,
            pady=2,
            command=self.add_variable_dialog
        ).grid(row=0, column=1, padx=1, pady=1, sticky="nsew")

        tk.Button(
            col_v_btns,
            text="✎ 修改變數",
            bg=UITheme.ACCENT_BLUE,
            fg="#fff",
            activebackground=UITheme.ACCENT_BLUE_HOVER,
            font=UITheme.FONT_SMALL_BOLD,
            relief="flat",
            padx=4,
            pady=2,
            command=self.edit_selected_variable
        ).grid(row=1, column=0, padx=1, pady=1, sticky="nsew")

        tk.Button(
            col_v_btns,
            text="✕ 刪除變數",
            bg=UITheme.ACCENT_RED,
            fg="#fff",
            activebackground=UITheme.ACCENT_RED_HOVER,
            font=UITheme.FONT_SMALL_BOLD,
            relief="flat",
            padx=4,
            pady=2,
            command=self.delete_selected_variable
        ).grid(row=1, column=1, padx=1, pady=1, sticky="nsew")

        # 3. 技能組合區塊
        f_combo = tk.LabelFrame(f_left, text=" 技能組合庫 ", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_TITLE, padx=6, pady=4)
        f_combo.pack(fill="both", expand=True)

        f_combo_split = tk.Frame(f_combo, bg=UITheme.BG_PANEL)
        f_combo_split.pack(fill="both", expand=True)
        f_combo_split.grid_columnconfigure(0, weight=3)
        f_combo_split.grid_columnconfigure(1, weight=8)
        f_combo_split.grid_rowconfigure(0, weight=1)

        # 2-A. 組合清單 (支援雙擊加入掛機流程)
        f_cl = tk.Frame(f_combo_split, bg=UITheme.BG_PANEL, padx=4, pady=2)
        f_cl.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        tk.Label(f_cl, text="【組合清單】", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_NORMAL_BOLD).pack(anchor="w")

        tk.Entry(f_cl, textvariable=self.var_combo_name, bg=UITheme.BG_INPUT, fg="#fff", font=UITheme.FONT_NORMAL, relief="flat").pack(fill="x", pady=(2, 2))

        cr_btns = tk.Frame(f_cl, bg=UITheme.BG_PANEL)
        cr_btns.pack(fill="x", pady=(0, 2))
        tk.Button(cr_btns, text="+ 新增", bg=UITheme.ACCENT_GREEN, fg="#fff", activebackground=UITheme.ACCENT_GREEN_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.add_new_combo).pack(side="left", fill="x", expand=True, padx=(0, 1))
        tk.Button(cr_btns, text="✎ 改名", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.rename_selected_combo).pack(side="left", fill="x", expand=True, padx=1)
        tk.Button(cr_btns, text="⎘ 複製", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.duplicate_selected_combo).pack(side="left", fill="x", expand=True, padx=(1, 0))

        cr_act = tk.Frame(f_cl, bg=UITheme.BG_PANEL)
        cr_act.pack(side="bottom", fill="x", pady=(2, 0))
        tk.Button(cr_act, text="➔ 加入掛機流程", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, font=UITheme.FONT_SMALL_BOLD, command=self.add_combo_to_main_steps).pack(side="left", fill="x", expand=True, padx=(0, 2))
        tk.Button(cr_act, text="✕ 刪除", bg=UITheme.ACCENT_RED, fg="#fff", activebackground=UITheme.ACCENT_RED_HOVER, font=UITheme.FONT_SMALL_BOLD, command=self.delete_selected_combo).pack(side="right")

        f_cl_box = tk.Frame(f_cl, bg=UITheme.BG_DARK)
        f_cl_box.pack(side="top", fill="both", expand=True, pady=2)
        self.combo_listbox = tk.Listbox(f_cl_box, height=4, bg=UITheme.BG_DARK, fg=UITheme.TEXT_MAIN, selectbackground=UITheme.ACCENT_BLUE, selectforeground="#fff", bd=0, highlightthickness=0, font=UITheme.FONT_NORMAL, exportselection=False)
        self.combo_listbox.pack(side="left", fill="both", expand=True)
        self.combo_listbox.bind("<<ListboxSelect>>", self.on_combo_select)
        self.combo_listbox.bind("<Double-Button-1>", self.on_combo_double_click_add)
        sc_cl = tk.Scrollbar(f_cl_box, orient="vertical", command=self.combo_listbox.yview)
        sc_cl.pack(side="right", fill="y")
        self.combo_listbox.config(yscrollcommand=sc_cl.set)

        # 2-B. 組合動作 (視覺層次優化：超緊湊卡片 + 超寬敞子動作清單)
        f_cr = tk.Frame(f_combo_split, bg=UITheme.BG_PANEL, padx=6, pady=2, highlightbackground=UITheme.BORDER, highlightthickness=1)
        f_cr.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        f_cr_top = tk.Frame(f_cr, bg=UITheme.BG_PANEL)
        f_cr_top.pack(fill="x", pady=(0, 2))
        self.lbl_combo_editing = tk.Label(f_cr_top, text="【組合動作: 未選取】", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_SUB, font=UITheme.FONT_NORMAL_BOLD)
        self.lbl_combo_editing.pack(side="left")
        tk.Button(f_cr_top, text="▶ 試跑組合", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, font=UITheme.FONT_SMALL_BOLD, relief="flat", padx=6, command=self.test_run_current_combo).pack(side="right")

        # 動作建立面板
        f_action_card = tk.LabelFrame(f_cr, text=" 加入動作 ", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL_BOLD, padx=5, pady=2)
        f_action_card.pack(fill="x", pady=(0, 2))

        # 1. 點擊動作行
        r_click = tk.Frame(f_action_card, bg=UITheme.BG_PANEL)
        r_click.pack(fill="x", pady=1)
        ttk.Combobox(r_click, textvariable=self.var_combo_btn, values=["左鍵", "右鍵"], width=4, state="readonly").pack(side="left", padx=(0, 2))
        btn_combo_add_click = tk.Button(r_click, text="+ 瞄準取點", bg=UITheme.ACCENT_GREEN, fg="#fff", font=UITheme.FONT_NORMAL_BOLD, activebackground=UITheme.ACCENT_GREEN_HOVER, relief="flat", padx=6, command=lambda: self.add_click_action(is_combo=True))
        btn_combo_add_click.pack(side="left", padx=1, fill="x", expand=True)

        tk.Label(r_click, text="X:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL).pack(side="left", padx=(3, 1))
        tk.Entry(r_click, textvariable=self.var_combo_manual_x, width=4, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=1)
        tk.Label(r_click, text="Y:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL).pack(side="left", padx=(1, 1))
        tk.Entry(r_click, textvariable=self.var_combo_manual_y, width=4, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=1)
        tk.Button(r_click, text="+ 手動", width=5, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=lambda: self.add_manual_click(is_combo=True)).pack(side="left", padx=(2, 0))

        # 2. 按鍵與等待行
        r_fast = tk.Frame(f_action_card, bg=UITheme.BG_PANEL)
        r_fast.pack(fill="x", pady=1)

        f_k = tk.Frame(r_fast, bg=UITheme.BG_PANEL)
        f_k.pack(side="left", fill="x", expand=True, padx=(0, 2))
        tk.Entry(f_k, textvariable=self.var_combo_act_key, width=5, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 2))
        tk.Button(f_k, text="+ 按鍵", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", padx=4, font=UITheme.FONT_SMALL_BOLD, command=lambda: self.add_key_action(is_combo=True)).pack(side="left", fill="x", expand=True)

        f_w = tk.Frame(r_fast, bg=UITheme.BG_PANEL)
        f_w.pack(side="left", fill="x", expand=True, padx=(2, 0))
        tk.Entry(f_w, textvariable=self.var_combo_act_wait, width=4, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 2))
        tk.Button(f_w, text="+ 停頓(s)", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", padx=4, font=UITheme.FONT_SMALL_BOLD, command=lambda: self.add_wait_action(is_combo=True)).pack(side="left", fill="x", expand=True)

        # 3. 呼叫組合與引用變數
        r_comb = tk.Frame(f_action_card, bg=UITheme.BG_PANEL)
        r_comb.pack(fill="x", pady=1)

        f_call = tk.Frame(r_comb, bg=UITheme.BG_PANEL)
        f_call.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self.cbo_call_combo = ttk.Combobox(f_call, textvariable=self.var_combo_to_call, width=10, state="readonly")
        self.cbo_call_combo.pack(side="left", fill="x", expand=True, padx=(0, 1))
        tk.Button(f_call, text="+ 呼叫組合", width=7, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.combo_add_call_action).pack(side="left")

        f_var = tk.Frame(r_comb, bg=UITheme.BG_PANEL)
        f_var.pack(side="left", fill="x", expand=True, padx=(2, 0))
        self.cbo_combo_add_var = ttk.Combobox(f_var, textvariable=self.var_combo_ref_var, width=10, state="readonly")
        self.cbo_combo_add_var.pack(side="left", fill="x", expand=True, padx=(0, 1))
        tk.Button(f_var, text="+ 引用變數", width=8, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.combo_add_variable_action).pack(side="left")

        # 底部單層全功能管理工具列 (統一佈局順序：上移/下移/試跑/修改/複製/刪除/清空)
        cr_act_ctrl = tk.Frame(f_cr, bg=UITheme.BG_PANEL)
        cr_act_ctrl.pack(side="bottom", fill="x", pady=(2, 1))
        tk.Button(cr_act_ctrl, text="▲ 上移", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=lambda: self.move_combo_action(-1)).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(cr_act_ctrl, text="▼ 下移", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=lambda: self.move_combo_action(1)).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(cr_act_ctrl, text="▶ 試跑", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.test_run_selected_combo_action).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(cr_act_ctrl, text="✎ 修改", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.edit_selected_combo_action).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(cr_act_ctrl, text="⎘ 複製", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.duplicate_combo_action).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(cr_act_ctrl, text="✕ 刪除", bg=UITheme.ACCENT_RED, fg="#fff", activebackground=UITheme.ACCENT_RED_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.delete_combo_action).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(cr_act_ctrl, text="✕ 清空", bg=UITheme.ACCENT_RED_DARK, fg="#fff", activebackground=UITheme.ACCENT_RED_DARK_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.clear_combo_actions).pack(side="left", padx=1, fill="x", expand=True)

        # 動作清單 (由 side="top", expand=True 自動填補剩餘高度)
        f_cr_box = tk.Frame(f_cr, bg=UITheme.BG_DARK)
        f_cr_box.pack(side="top", fill="both", expand=True, pady=(1, 2))

        self.combo_act_listbox = tk.Listbox(
            f_cr_box,
            height=4,
            bg=UITheme.BG_DARK,
            fg=UITheme.TEXT_MAIN,
            selectbackground=UITheme.ACCENT_BLUE,
            selectforeground="#fff",
            bd=0,
            highlightthickness=0,
            font=UITheme.FONT_NORMAL,
            exportselection=False
        )
        self.combo_act_listbox.pack(side="left", fill="both", expand=True)
        self.combo_act_listbox.bind("<Double-Button-1>", lambda e: self.edit_selected_combo_action())
        sc_cr = tk.Scrollbar(f_cr_box, orient="vertical", command=self.combo_act_listbox.yview)
        sc_cr.pack(side="right", fill="y")
        self.combo_act_listbox.config(yscrollcommand=sc_cr.set)

    # ======================= 右欄佈局 =======================
    def build_right_panel(self):
        f_right = tk.Frame(self, bg=UITheme.BG_PANEL, padx=8, pady=8, highlightbackground=UITheme.BORDER, highlightthickness=1)
        f_right.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="nsew")

        # 1. 單一動作新增
        f_step = tk.LabelFrame(f_right, text=" 單一動作 ", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_TITLE, padx=6, pady=3)
        f_step.pack(fill="x", pady=(0, 4))

        sr_click = tk.Frame(f_step, bg=UITheme.BG_PANEL)
        sr_click.pack(fill="x", pady=1)
        ttk.Combobox(sr_click, textvariable=self.var_step_btn, values=["左鍵", "右鍵"], width=4, state="readonly").pack(side="left", padx=(0, 2))
        btn_step_click = tk.Button(sr_click, text="+ 瞄準取點", bg=UITheme.ACCENT_GREEN, fg="#fff", font=UITheme.FONT_NORMAL_BOLD, activebackground=UITheme.ACCENT_GREEN_HOVER, relief="flat", padx=6, command=lambda: self.add_click_action(is_combo=False))
        btn_step_click.pack(side="left", padx=1, fill="x", expand=True)
        tk.Label(sr_click, text="X:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL).pack(side="left", padx=(4, 1))
        tk.Entry(sr_click, textvariable=self.var_step_manual_x, width=4, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=1)
        tk.Label(sr_click, text="Y:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL).pack(side="left", padx=(1, 1))
        tk.Entry(sr_click, textvariable=self.var_step_manual_y, width=4, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=1)
        tk.Button(sr_click, text="+ 手動", width=5, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=lambda: self.add_manual_click(is_combo=False)).pack(side="left", padx=(2, 0))

        sr = tk.Frame(f_step, bg=UITheme.BG_PANEL)
        sr.pack(fill="x", pady=1)
        f_sk = tk.Frame(sr, bg=UITheme.BG_PANEL)
        f_sk.pack(side="left", fill="x", expand=True, padx=(0, 2))
        tk.Entry(f_sk, textvariable=self.var_step_key, width=5, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 2))
        tk.Button(f_sk, text="+ 按鍵", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", padx=4, font=UITheme.FONT_SMALL_BOLD, command=lambda: self.add_key_action(is_combo=False)).pack(side="left", fill="x", expand=True)

        f_sw = tk.Frame(sr, bg=UITheme.BG_PANEL)
        f_sw.pack(side="left", fill="x", expand=True, padx=(2, 0))
        tk.Entry(f_sw, textvariable=self.var_step_wait, width=4, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 2))
        tk.Button(f_sw, text="+ 停頓(s)", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", padx=4, font=UITheme.FONT_SMALL_BOLD, command=lambda: self.add_wait_action(is_combo=False)).pack(side="left", fill="x", expand=True)

        # 3. 呼叫組合與引用變數
        sr_comb = tk.Frame(f_step, bg=UITheme.BG_PANEL)
        sr_comb.pack(fill="x", pady=1)

        f_scall = tk.Frame(sr_comb, bg=UITheme.BG_PANEL)
        f_scall.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self.cbo_step_call_combo = ttk.Combobox(f_scall, textvariable=self.var_step_combo_to_call, width=10, state="readonly")
        self.cbo_step_call_combo.pack(side="left", fill="x", expand=True, padx=(0, 1))
        tk.Button(f_scall, text="+ 呼叫組合", width=7, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.step_add_call_combo_action).pack(side="left")

        f_svar = tk.Frame(sr_comb, bg=UITheme.BG_PANEL)
        f_svar.pack(side="left", fill="x", expand=True, padx=(2, 0))
        self.cbo_step_add_var = ttk.Combobox(f_svar, textvariable=self.var_step_ref_var, width=10, state="readonly")
        self.cbo_step_add_var.pack(side="left", fill="x", expand=True, padx=(0, 1))
        tk.Button(f_svar, text="+ 引用變數", width=8, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.step_add_variable_action).pack(side="left")

        # 2. 自動循環清單（掛機流程）
        f_seq = tk.LabelFrame(f_right, text=" 掛機流程清單 ", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_TITLE, padx=6, pady=6)
        f_seq.pack(fill="both", expand=True)

        # 頂部控制列 (標題/提示、游標跟隨 與 試跑流程)
        f_seq_hdr = tk.Frame(f_seq, bg=UITheme.BG_PANEL)
        f_seq_hdr.pack(fill="x", pady=(0, 2))
        self.lbl_seq_hint = tk.Label(f_seq_hdr, text="【流程步驟】 (雙擊可修改)", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL)
        self.lbl_seq_hint.pack(side="left")

        self.btn_main_test_all = tk.Button(
            f_seq_hdr,
            text="▶ 試跑流程",
            bg=UITheme.ACCENT_INDIGO,
            fg="#fff",
            activebackground=UITheme.ACCENT_INDIGO_HOVER,
            font=UITheme.FONT_SMALL_BOLD,
            relief="flat",
            padx=6,
            command=self.test_run_execution_flow
        )
        self.btn_main_test_all.pack(side="right")

        # 底部單層全功能管理工具列 (統一佈局順序：上移/下移/試跑/修改/複製/刪除/清空)
        sr2 = tk.Frame(f_seq, bg=UITheme.BG_PANEL)
        sr2.pack(side="bottom", fill="x", pady=(2, 0))
        self.btn_main_up = tk.Button(sr2, text="▲ 上移", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=lambda: self.move_main_step(-1))
        self.btn_main_up.pack(side="left", padx=1, fill="x", expand=True)
        self.btn_main_down = tk.Button(sr2, text="▼ 下移", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=lambda: self.move_main_step(1))
        self.btn_main_down.pack(side="left", padx=1, fill="x", expand=True)
        self.btn_main_test = tk.Button(sr2, text="▶ 試跑步驟", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.test_run_selected_main_step)
        self.btn_main_test.pack(side="left", padx=1, fill="x", expand=True)
        self.btn_main_edit = tk.Button(sr2, text="✎ 修改", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.edit_selected_main_step)
        self.btn_main_edit.pack(side="left", padx=1, fill="x", expand=True)
        self.btn_main_dup = tk.Button(sr2, text="⎘ 複製", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.duplicate_main_step)
        self.btn_main_dup.pack(side="left", padx=1, fill="x", expand=True)
        self.btn_main_del = tk.Button(sr2, text="✕ 刪除", bg=UITheme.ACCENT_RED, fg="#fff", activebackground=UITheme.ACCENT_RED_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.delete_main_step)
        self.btn_main_del.pack(side="left", padx=1, fill="x", expand=True)
        self.btn_main_clear = tk.Button(sr2, text="✕ 清空", bg=UITheme.ACCENT_RED_DARK, fg="#fff", activebackground=UITheme.ACCENT_RED_DARK_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.clear_main_steps)
        self.btn_main_clear.pack(side="left", padx=1, fill="x", expand=True)

        # 流程清單 (由 side="top", expand=True 自動填補剩餘高度)
        f_list_s = tk.Frame(f_seq, bg=UITheme.BG_DARK)
        f_list_s.pack(side="top", fill="both", expand=True, pady=2)

        self.step_listbox = tk.Listbox(
            f_list_s,
            height=4,
            bg=UITheme.BG_DARK,
            fg=UITheme.TEXT_MAIN,
            selectbackground=UITheme.ACCENT_BLUE,
            selectforeground="#fff",
            bd=0,
            highlightthickness=0,
            font=UITheme.FONT_NORMAL,
            exportselection=False
        )
        self.step_listbox.pack(side="left", fill="both", expand=True)
        self.step_listbox.bind("<Double-Button-1>", lambda e: self.edit_selected_main_step())
        sc_step = tk.Scrollbar(f_list_s, orient="vertical", command=self.step_listbox.yview)
        sc_step.pack(side="right", fill="y")
        self.step_listbox.config(yscrollcommand=sc_step.set)

        # 3. HUD 與主開關
        bot = tk.Frame(f_right, bg=UITheme.BG_PANEL)
        bot.pack(fill="x", pady=(2, 0))

        self.lbl_mouse_hud = tk.Label(bot, text="● 游標實時坐標: (0, 0)", anchor="w", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_NORMAL_BOLD)
        self.lbl_mouse_hud.pack(fill="x")

        self.lbl_status = tk.Label(bot, text="● 狀態: 已就緒", anchor="w", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MAIN, font=UITheme.FONT_NORMAL)
        self.lbl_status.pack(fill="x", pady=(0, 3))
        self.btn_toggle = tk.Button(bot, text="▶ 開始循環執行", height=2, bg=UITheme.ACCENT_GREEN, fg="#ffffff", font=UITheme.FONT_BIG_BTN, activebackground=UITheme.ACCENT_GREEN_HOVER, command=self.toggle_run)
        self.btn_toggle.pack(fill="x")

    def on_combo_double_click_add(self, event=None):
        """雙擊組合清單時直接加入掛機流程"""
        self.add_combo_to_main_steps()

    # ======================= 設定檔管理 (附帶 Schema 遷移) =======================
    def get_profile_files(self):
        try:
            return sorted([f[:-len(CONFIG_EXT)] for f in os.listdir(".") if f.endswith(CONFIG_EXT)])
        except Exception:
            return []

    def refresh_profiles(self, select_name=None):
        profiles = self.get_profile_files()
        if not profiles:
            profiles = ["default"]
            if not os.path.exists(f"default{CONFIG_EXT}"):
                try:
                    with open(f"default{CONFIG_EXT}", "w", encoding="utf-8") as f:
                        json.dump({"variables": {}, "combos": [], "steps": []}, f)
                except Exception: pass

        self.cbo_profile["values"] = profiles
        if select_name and select_name in profiles:
            self.cbo_profile.set(select_name)
        elif self.var_profile_name.get() in profiles:
            self.cbo_profile.set(self.var_profile_name.get())
        else:
            self.cbo_profile.current(0)

    def create_new_profile(self):
        if state.running or state.is_testing:
            return self.set_status("巨集正在執行或試跑中，請先停止再新建設定檔！")
        name = simpledialog.askstring("新建設定檔", "請輸入新設定檔名稱 (毋須輸入副檔名):", parent=self)
        if not name or not name.strip(): return
        name = name.strip()
        fn = f"{name}{CONFIG_EXT}"
        if os.path.exists(fn):
            if not messagebox.askyesno("檔案覆蓋確認", f"設定檔「{name}」已存在！\n請問是否確認覆蓋原有設定？", parent=self):
                return
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump({"variables": state.variables, "combos": state.combos, "steps": state.steps}, f, ensure_ascii=False, indent=2)
            self.refresh_profiles(select_name=name)
            self.set_status(f"已新建並儲存至 {fn}")
        except Exception as e:
            self.set_status(f"新建失敗: {e}")

    def save_config(self):
        name = self.var_profile_name.get().strip()
        if not name: return self.set_status("請先選擇或新建設定檔")
        fn = f"{name}{CONFIG_EXT}"
        if os.path.exists(fn):
            if not messagebox.askyesno("檔案覆蓋確認", f"請問是否確認覆蓋「{name}」的原有設定？", parent=self):
                return self.set_status("已取消儲存")
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump({"variables": state.variables, "combos": state.combos, "steps": state.steps}, f, ensure_ascii=False, indent=2)
            self.set_status(f"已成功儲存至 {fn}")
            self.refresh_profiles(select_name=name)
        except Exception as e:
            self.set_status(f"儲存失敗: {e}")

    def load_config(self):
        if state.running or state.is_testing:
            return self.set_status("巨集正在執行或試跑中，請先停止再載入設定檔！")
        name = self.var_profile_name.get().strip()
        if not name: return
        fn = f"{name}{CONFIG_EXT}"
        if not os.path.exists(fn): return self.set_status(f"找不到檔案：{fn}")
        try:
            with open(fn, "r", encoding="utf-8") as f:
                data = json.load(f)

            state.variables.clear()
            state.variables.update(data.get("variables", {}))
            self.refresh_variables_table()

            state.combos.clear()
            state.combos.extend(data.get("combos", []))
            state.steps.clear()
            state.steps.extend(data.get("steps", []))

            self.refresh_combo_list()
            self.refresh_combo_actions_list()
            self.update_step_list()
            self.set_status(f"成功載入設定檔：{name}")
        except Exception as e:
            self.set_status(f"載入失敗: {e}")

    # ======================= 視窗綁定 =======================
    def get_window_list(self):
        if not IS_WINDOWS or not user32:
            return []
        windows = []
        def enum_proc(hwnd, lParam):
            if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
                buff = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
                user32.GetWindowTextW(hwnd, buff, len(buff))
                t = buff.value.strip()
                if t and WINDOW_TITLE not in t:
                    windows.append((hwnd, t))
            return True
        cb = WNDENUMPROC(enum_proc)
        user32.EnumWindows(cb, 0)
        return windows

    def refresh_window_dropdown(self):
        win_list = self.get_window_list()
        items, target_idx = [], 0
        for i, (hwnd, title) in enumerate(win_list):
            items.append(f"[{hwnd}] {title}")
            if "水滸" in title or "online" in title.lower(): target_idx = i

        if not items:
            items, state.target_hwnd = ["未偵測到任何視窗"], None
        else:
            state.target_hwnd = win_list[target_idx][0]

        self.cbo_window["values"] = items
        self.cbo_window.current(target_idx)
        if state.target_hwnd:
            self.set_status(f"已綁定目標視窗 HWND: {state.target_hwnd}")

    def on_window_select(self, event=None):
        val = self.var_window.get()
        if val and val.startswith("["):
            try:
                state.target_hwnd = int(val.split("]")[0].replace("[", ""))
                self.set_status(f"已綁定目標視窗 HWND: {state.target_hwnd}")
            except Exception:
                state.target_hwnd = None

    # ======================= 變數管理邏輯 =======================
    def refresh_variables_table(self):
        """重新整理變數表格一覽與關聯下拉選單"""
        if not hasattr(self, "tree_vars"):
            return
        for item in self.tree_vars.get_children():
            self.tree_vars.delete(item)

        type_display = {"coord": "[坐標]", "key": "[按鍵]", "wait": "[停頓]"}

        for name, data in state.variables.items():
            t_key = data.get("type", "coord")
            t_disp = type_display.get(t_key, t_key)
            val = data.get("value")

            if t_key == "coord":
                if isinstance(val, dict):
                    btn_tag = "右鍵·" if val.get("btn") == "right" else "左鍵·"
                    v_str = f"{btn_tag}({val.get('x', 0)}, {val.get('y', 0)})"
                else:
                    v_str = str(val)
            elif t_key == "key":
                v_str = str(val).upper()
            elif t_key == "wait":
                v_str = f"{val} 秒"
            else:
                v_str = str(val)

            self.tree_vars.insert("", "end", iid=name, values=(name, t_disp, v_str))

        var_names = list(state.variables.keys())
        if hasattr(self, "cbo_combo_add_var"):
            self.cbo_combo_add_var["values"] = var_names
            if var_names:
                if self.var_combo_ref_var.get() not in var_names:
                    self.cbo_combo_add_var.current(0)
            else:
                self.var_combo_ref_var.set("")

        if hasattr(self, "cbo_step_add_var"):
            self.cbo_step_add_var["values"] = var_names
            if var_names:
                if self.var_step_ref_var.get() not in var_names:
                    self.cbo_step_add_var.current(0)
            else:
                self.var_step_ref_var.set("")

    def add_variable_dialog(self):
        """新增變數入口"""
        self.prompt_variable_dialog(None)

    def edit_selected_variable(self):
        """修改所選變數入口"""
        sel = self.tree_vars.selection()
        if not sel:
            return self.set_status("請先在表格中選擇要修改的變數")
        var_name = sel[0]
        self.prompt_variable_dialog(var_name)

    def delete_selected_variable(self):
        """刪除所選變數"""
        sel = self.tree_vars.selection()
        if not sel:
            return self.set_status("請先在表格中選擇要刪除的變數")
        var_name = sel[0]
        if not messagebox.askyesno("刪除變數", f"請問是否確定刪除變數「{var_name}」？\n若已有動作引用此變數，執行時將自動回退至固定值。", parent=self):
            return
        state.variables.pop(var_name, None)
        self.trigger_hot_reload()
        self.refresh_variables_table()
        self.refresh_combo_actions_list()
        self.update_step_list()
        self.set_status(f"已刪除變數: {var_name}")

    def _build_variable_action(self, var_name):
        """根據變數名稱與類型，組裝對應的動作字典與提示描述，若無效則回傳 (None, None)"""
        if not var_name or var_name not in state.variables:
            return None, None
        v_info = state.variables[var_name]
        v_type = v_info.get("type", "coord")
        v_val = v_info.get("value")

        if v_type == "coord":
            px = v_val.get("x", 0) if isinstance(v_val, dict) else 0
            py = v_val.get("y", 0) if isinstance(v_val, dict) else 0
            btn = v_val.get("btn", "left") if isinstance(v_val, dict) else "left"
            btn_cn = "右鍵" if btn == "right" else "左鍵"
            new_act = {
                "type": "click",
                "btn": btn,
                "x": px,
                "y": py,
                "rel": self.var_use_rel.get(),
                "var_name": var_name
            }
            desc = f"【{var_name}】({btn_cn}點擊)"
        elif v_type == "key":
            new_act = {
                "type": "key",
                "key": str(v_val),
                "var_name": var_name
            }
            desc = f"【{var_name}】(按鍵[{str(v_val).upper()}])"
        elif v_type == "wait":
            try: sec = float(v_val)
            except Exception: sec = 1.0
            new_act = {
                "type": "wait",
                "sec": sec,
                "var_name": var_name
            }
            desc = f"【{var_name}】(停頓{sec}s)"
        else:
            return None, None

        return new_act, desc

    def add_variable_to_main_steps(self):
        """將表格中所選定的變數以引用方式直接加入掛機流程"""
        sel = self.tree_vars.selection()
        if not sel:
            return self.set_status("請先在表格中選擇要加入流程的變數！")
        var_name = sel[0]
        new_act, desc = self._build_variable_action(var_name)
        if not new_act:
            return self.set_status("找不到所選變數或變數無效！")
        ins = self.get_main_insert_index()
        self._insert_action_to_target(new_act, is_combo=False, success_msg=f"已將變數{desc} 加入掛機流程 #{ins+1}")

    def combo_add_variable_action(self):
        """將選定的變數以引用方式加入當前選取組合"""
        var_name = self.var_combo_ref_var.get().strip()
        new_act, desc = self._build_variable_action(var_name)
        if not new_act:
            return self.set_status("請先選擇要引用的變數！")
        if self.get_selected_combo_idx() is None:
            return self.set_status("請先在左邊清單選擇要加入動作的組合！")
        self._insert_action_to_target(new_act, is_combo=True, success_msg=f"已在組合加入引用變數{desc}")

    # ======================= 組合管理邏輯 =======================
    def get_selected_combo_idx(self):
        sel = self.combo_listbox.curselection()
        return sel[0] if sel and 0 <= sel[0] < len(state.combos) else None

    def refresh_call_combo_dropdown(self):
        idx = self.get_selected_combo_idx()
        curr_name = state.combos[idx]["name"] if idx is not None else None
        avail = [c["name"] for c in state.combos if c["name"] != curr_name]
        if hasattr(self, "cbo_call_combo"):
            self.cbo_call_combo["values"] = avail
            if avail:
                if self.var_combo_to_call.get() not in avail:
                    self.cbo_call_combo.current(0)
            else:
                self.var_combo_to_call.set("")

        all_combos = [c["name"] for c in state.combos]
        if hasattr(self, "cbo_step_call_combo"):
            self.cbo_step_call_combo["values"] = all_combos
            if all_combos:
                if self.var_step_combo_to_call.get() not in all_combos:
                    self.cbo_step_call_combo.current(0)
            else:
                self.var_step_combo_to_call.set("")

    def refresh_combo_list(self, select_idx=None):
        self.combo_listbox.delete(0, tk.END)
        for i, c in enumerate(state.combos):
            act_count = len(c.get("actions", []))
            self.combo_listbox.insert(tk.END, f"{i+1:02d}. {c['name']} ({act_count}動作)")
        if select_idx is not None and 0 <= select_idx < len(state.combos):
            self.combo_listbox.selection_set(select_idx)
            self.on_combo_select()
        else:
            self.refresh_call_combo_dropdown()

    def on_combo_select(self, event=None):
        idx = self.get_selected_combo_idx()
        if idx is None:
            self.lbl_combo_editing.config(text="【組合動作: 未選取】")
            self.combo_act_listbox.delete(0, tk.END)
            self.refresh_call_combo_dropdown()
            return
        c = state.combos[idx]
        self.var_combo_name.set(c["name"])
        self.lbl_combo_editing.config(text=f"【編輯: {c['name']}】")
        self.refresh_combo_actions_list()
        self.refresh_call_combo_dropdown()

    def add_new_combo(self):
        name = self.var_combo_name.get().strip() or f"組合{len(state.combos)+1}"
        state.combos.append({"name": name, "actions": []})
        self.refresh_combo_list(select_idx=len(state.combos)-1)
        self.set_status(f"已建立新組合: [{name}]")
        self.trigger_hot_reload()

    def duplicate_selected_combo(self):
        idx = self.get_selected_combo_idx()
        if idx is None: return self.set_status("請先在左邊清單點選要複製的組合！")
        orig = state.combos[idx]
        base_name = orig["name"]
        new_name = f"{base_name}_副本"
        count = 1
        while any(c["name"] == new_name for c in state.combos):
            count += 1
            new_name = f"{base_name}_副本{count}"

        state.combos.insert(idx + 1, {"name": new_name, "actions": copy.deepcopy(orig.get("actions", []))})
        self.refresh_combo_list(select_idx=idx + 1)
        self.set_status(f"已複製組合 [{base_name}] 為 [{new_name}]")
        self.trigger_hot_reload()

    def rename_selected_combo(self):
        idx = self.get_selected_combo_idx()
        if idx is None: return self.set_status("請先在左邊點選要改名的組合！")
        new_name = self.var_combo_name.get().strip()
        if not new_name: return
        old_name = state.combos[idx]["name"]
        state.combos[idx]["name"] = new_name

        for c in state.combos:
            for act in c.get("actions", []):
                if act.get("type") == "call_combo" and act.get("target_name") == old_name:
                    act["target_name"] = new_name

        sync_cnt = 0
        for s in state.steps:
            if s.get("type") == "call_combo" and s.get("target_name") == old_name:
                s["target_name"] = new_name
                sync_cnt += 1
            elif s.get("type") == "combo":
                if s.get("name") == old_name:
                    s["name"] = new_name
                    sync_cnt += 1
                for act in s.get("actions", []):
                    if act.get("type") == "call_combo" and act.get("target_name") == old_name:
                        act["target_name"] = new_name

        if sync_cnt > 0: self.update_step_list()
        self.refresh_combo_list(select_idx=idx)
        self.set_status(f"已將組合改名為 [{new_name}]，同步刷新了關聯步驟")
        self.trigger_hot_reload()

    def delete_selected_combo(self):
        idx = self.get_selected_combo_idx()
        if idx is None: return
        name = state.combos[idx]["name"]
        if not messagebox.askyesno("刪除組合確認", f"確定要刪除組合【{name}】嗎？組合內的所有動作將會一併清除！", parent=self):
            return
        del state.combos[idx]
        new_sel = min(idx, len(state.combos) - 1) if state.combos else None
        self.refresh_combo_list(select_idx=new_sel)
        self.on_combo_select()
        self.update_step_list()
        self.set_status(f"已刪除組合 [{name}]")
        self.trigger_hot_reload()

    def add_combo_to_main_steps(self):
        idx = self.get_selected_combo_idx()
        if idx is None: return self.set_status("請先在左邊選擇要加入的組合！")
        c = state.combos[idx]
        if not c.get("actions"): return self.set_status(f"組合 [{c['name']}] 內尚未加入任何動作！")

        ins = self.get_main_insert_index()
        state.steps.insert(ins, {"type": "combo", "name": c["name"], "actions": copy.deepcopy(c["actions"])})
        self.update_step_list(select_idx=ins)
        self.set_status(f"已將組合 [{c['name']}] 加入掛機流程 #{ins+1}")
        self.trigger_hot_reload()

    # ======================= 組合動作邏輯 =======================
    def get_selected_action_idx(self):
        sel = self.combo_act_listbox.curselection()
        return sel[0] if sel else None

    def refresh_combo_actions_list(self, select_idx=None):
        self.combo_act_listbox.delete(0, tk.END)
        idx = self.get_selected_combo_idx()
        if idx is None:
            return
        actions = state.combos[idx].get("actions", [])
        for i, act in enumerate(actions):
            self.combo_act_listbox.insert(tk.END, format_action_summary(act, index=i))
        if select_idx is not None and 0 <= select_idx < len(actions):
            self.combo_act_listbox.selection_set(select_idx)
            self.combo_act_listbox.see(select_idx)

    def sync_combo_actions_to_main_steps(self, combo_name, new_actions):
        sync_cnt = 0
        for s in state.steps:
            if s.get("type") == "combo" and s.get("name") == combo_name:
                s["actions"] = copy.deepcopy(new_actions)
                sync_cnt += 1
        if sync_cnt > 0: self.update_step_list()

    def test_run_selected_combo_action(self):
        c_idx = self.get_selected_combo_idx()
        a_idx = self.get_selected_action_idx()
        if c_idx is None or a_idx is None:
            return self.set_status("請先選擇要試跑的組合動作！")
        act = state.combos[c_idx]["actions"][a_idx]
        self.run_in_test_thread(f"組合動作 #{a_idx+1}", lambda: self.execute_single_action(act, f"組合動作#{a_idx+1}"))

    def test_run_current_combo(self):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None:
            return self.set_status("請先選擇要試跑的組合！")
        c = state.combos[c_idx]
        sub_actions = c.get("actions", [])
        if not sub_actions:
            return self.set_status(f"組合 [{c['name']}] 內無任何動作可試跑！")

        def _run():
            for a_idx, act in enumerate(sub_actions):
                if state.stop_event.is_set(): break
                self.execute_single_action(act, f"[{c['name']}#{a_idx+1}]")

        self.run_in_test_thread(f"組合 [{c['name']}]", _run)

    # ======================= 熱更新同步與清單動作輔助函數 =======================
    def trigger_hot_reload(self):
        """若巨集運行中，同步最新草稿至背景實例快照，並於下一輪自動生效"""
        if state.running:
            with state.steps_lock:
                state.active_steps = copy.deepcopy(state.steps)
                state.active_combos = copy.deepcopy(state.combos)
                state.active_variables = copy.deepcopy(state.variables)
                state.reload_requested = True

    def _move_list_item(self, lst, idx, delta, refresh_cb, item_name="項目"):
        if idx is None:
            return self.set_status(f"請先在清單點選要移動的{item_name}！")
        target = idx + delta
        if 0 <= target < len(lst):
            lst[idx], lst[target] = lst[target], lst[idx]
            refresh_cb(target)
            direction = "上移" if delta < 0 else "下移"
            self.set_status(f"已將{item_name} #{idx+1} {direction}至 #{target+1}")
            self.trigger_hot_reload()
        else:
            self.set_status("已在清單最頂或最底，無法再移動！")

    def _duplicate_list_item(self, lst, idx, refresh_cb, item_name="項目"):
        if idx is None: return self.set_status(f"請先在清單點選要複製的{item_name}！")
        lst.insert(idx + 1, copy.deepcopy(lst[idx]))
        refresh_cb(idx + 1)
        self.set_status(f"已複製{item_name} #{idx+1}")
        self.trigger_hot_reload()

    def _delete_list_item(self, lst, idx, refresh_cb, item_name="項目"):
        if idx is None or not (0 <= idx < len(lst)):
            return self.set_status(f"請先在清單點選要刪除的{item_name}！")
        del lst[idx]
        new_sel = min(idx, len(lst) - 1) if lst else None
        refresh_cb(new_sel)
        self.set_status(f"已刪除{item_name}")
        self.trigger_hot_reload()

    def _clear_list_items(self, lst, confirm_msg, refresh_cb, status_msg):
        if not lst: return self.set_status(f"{status_msg}本來就是空的")
        if messagebox.askyesno("清空確認", confirm_msg, parent=self):
            lst.clear()
            refresh_cb(None)
            self.set_status(f"已清空{status_msg}")
            self.trigger_hot_reload()

    def _insert_action_to_target(self, action_dict, is_combo=False, success_msg=""):
        if is_combo:
            idx = self.get_selected_combo_idx()
            if idx is None: return self.set_status("請先選取一個組合！")
            actions = state.combos[idx].setdefault("actions", [])
            sel = self.get_selected_action_idx()
            ins = sel + 1 if sel is not None else len(actions)
            actions.insert(ins, action_dict)
            self.refresh_combo_actions_list(select_idx=ins)
            self.refresh_combo_list(select_idx=idx)
            self.sync_combo_actions_to_main_steps(state.combos[idx]["name"], actions)
            if success_msg: self.set_status(success_msg)
            self.trigger_hot_reload()
            return ins
        else:
            ins = self.get_main_insert_index()
            state.steps.insert(ins, action_dict)
            self.update_step_list(ins)
            if success_msg: self.set_status(success_msg)
            self.trigger_hot_reload()
            return ins

    def add_click_action(self, is_combo=False):
        if state.running:
            return self.set_status("巨集正在循環執行中，為免干擾滑鼠瞄準，請先停止運行再取點！")
        if is_combo and self.get_selected_combo_idx() is None:
            return self.set_status("請先選取一個組合！")
        btn_var = self.var_combo_btn if is_combo else self.var_step_btn
        target_btn = "right" if btn_var.get() == "右鍵" else "left"
        btn_cn = "右鍵" if target_btn == "right" else "左鍵"

        def cb(x, y, rel):
            if is_combo:
                msg = f"已在組合加入{btn_cn}點擊 ({x},{y})"
            else:
                ins = self.get_main_insert_index()
                msg = f"已成功新增{btn_cn}點擊位置到第 #{ins+1} 步"
            self._insert_action_to_target({"type": "click", "btn": target_btn, "x": x, "y": y, "rel": rel}, is_combo=is_combo, success_msg=msg)

        self.capture_pos_space(cb, btn=target_btn)

    def add_manual_click(self, is_combo=False):
        if is_combo and self.get_selected_combo_idx() is None:
            return self.set_status("請先選取一個組合！")
        var_x = self.var_combo_manual_x if is_combo else self.var_step_manual_x
        var_y = self.var_combo_manual_y if is_combo else self.var_step_manual_y
        try:
            x = int(var_x.get().strip())
            y = int(var_y.get().strip())
        except ValueError:
            return self.set_status("X 和 Y 必須輸入整數！")

        btn_var = self.var_combo_btn if is_combo else self.var_step_btn
        target_btn = "right" if btn_var.get() == "右鍵" else "left"
        btn_cn = "右鍵" if target_btn == "right" else "左鍵"

        if is_combo:
            msg = f"已手動在組合加入{btn_cn}點擊: ({x}, {y})"
        else:
            ins = self.get_main_insert_index()
            msg = f"已手動插入{btn_cn}點擊到掛機流程 #{ins+1}: ({x}, {y})"

        self._insert_action_to_target({"type": "click", "btn": target_btn, "x": x, "y": y, "rel": self.var_use_rel.get()}, is_combo=is_combo, success_msg=msg)

    def edit_selected_combo_action(self):
        c_idx = self.get_selected_combo_idx()
        a_idx = self.get_selected_action_idx()
        if c_idx is None or a_idx is None: return self.set_status("請先選擇組合動作！")

        act = state.combos[c_idx]["actions"][a_idx]
        curr_combo_name = state.combos[c_idx]["name"]
        avail_combos = [c["name"] for c in state.combos if c["name"] != curr_combo_name]

        if self.prompt_edit_action(act, available_combos=avail_combos):
            self.refresh_combo_actions_list(select_idx=a_idx)
            self.sync_combo_actions_to_main_steps(state.combos[c_idx]["name"], state.combos[c_idx]["actions"])
            self.set_status(f"已成功更新組合動作 #{a_idx+1}")
            self.trigger_hot_reload()

    def add_key_action(self, is_combo=False):
        if is_combo and self.get_selected_combo_idx() is None:
            return self.set_status("請先選取一個組合！")
        key_var = self.var_combo_act_key if is_combo else self.var_step_key
        key = key_var.get().strip().lower()
        if not key: return
        if is_combo:
            msg = f"已在組合加入按鍵 [{key.upper()}]"
        else:
            ins = self.get_main_insert_index()
            msg = f"已插入按鍵到掛機流程 #{ins+1}: [{key.upper()}]"
        self._insert_action_to_target({"type": "key", "key": key}, is_combo=is_combo, success_msg=msg)

    def add_wait_action(self, is_combo=False):
        if is_combo and self.get_selected_combo_idx() is None:
            return self.set_status("請先選取一個組合！")
        wait_var = self.var_combo_act_wait if is_combo else self.var_step_wait
        try:
            sec = float(wait_var.get())
            if sec <= 0: raise ValueError
        except ValueError:
            return self.set_status("停頓秒數必須大於0！")
        if is_combo:
            msg = f"已在組合加入停頓 {sec} 秒"
        else:
            ins = self.get_main_insert_index()
            msg = f"已插入等待到掛機流程 #{ins+1}: {sec} 秒"
        self._insert_action_to_target({"type": "wait", "sec": sec}, is_combo=is_combo, success_msg=msg)

    def combo_add_call_action(self):
        idx = self.get_selected_combo_idx()
        if idx is None: return self.set_status("請先選取一個組合！")
        target_name = self.var_combo_to_call.get().strip()
        if not target_name: return self.set_status("請先在下拉選單選擇要呼叫的組合！")
        if target_name == state.combos[idx]["name"]: return self.set_status("不能在組合內呼叫自己！")
        self._insert_action_to_target({"type": "call_combo", "target_name": target_name}, is_combo=True, success_msg=f"已在組合加入呼叫: [{target_name}]")

    def step_add_call_combo_action(self):
        """在掛機流程中加入呼叫組合步驟"""
        target_name = self.var_step_combo_to_call.get().strip()
        if not target_name:
            return self.set_status("請先在下拉選單選擇要呼叫的組合！")
        ins = self.get_main_insert_index()
        self._insert_action_to_target(
            {"type": "call_combo", "target_name": target_name},
            is_combo=False,
            success_msg=f"已插入呼叫組合到掛機流程 #{ins+1}: [{target_name}]"
        )

    def step_add_variable_action(self):
        """在掛機流程中加入引用變數動作"""
        var_name = self.var_step_ref_var.get().strip()
        new_act, desc = self._build_variable_action(var_name)
        if not new_act:
            return self.set_status("請先在下拉選單選擇要引用的變數！")
        ins = self.get_main_insert_index()
        self._insert_action_to_target(new_act, is_combo=False, success_msg=f"已插入引用變數到掛機流程 #{ins+1}: {desc}")

    def move_combo_action(self, delta):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None: return self.set_status("請先在左邊清單選取一個組合！")
        a_idx = self.get_selected_action_idx()
        actions = state.combos[c_idx]["actions"]
        def _refresh(target):
            self.refresh_combo_actions_list(select_idx=target)
            self.sync_combo_actions_to_main_steps(state.combos[c_idx]["name"], actions)
        self._move_list_item(actions, a_idx, delta, _refresh, item_name="組合動作")

    def duplicate_combo_action(self):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None: return self.set_status("請先在左邊清單選取一個組合！")
        a_idx = self.get_selected_action_idx()
        actions = state.combos[c_idx]["actions"]
        def _refresh(target):
            self.refresh_combo_actions_list(select_idx=target)
            self.refresh_combo_list(select_idx=c_idx)
            self.sync_combo_actions_to_main_steps(state.combos[c_idx]["name"], actions)
        self._duplicate_list_item(actions, a_idx, _refresh, item_name="組合動作")

    def delete_combo_action(self):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None: return self.set_status("請先在左邊清單選取一個組合！")
        a_idx = self.get_selected_action_idx()
        actions = state.combos[c_idx]["actions"]
        def _refresh(target):
            self.refresh_combo_actions_list(select_idx=target)
            self.refresh_combo_list(select_idx=c_idx)
            self.sync_combo_actions_to_main_steps(state.combos[c_idx]["name"], actions)
        self._delete_list_item(actions, a_idx, _refresh, item_name="組合動作")

    def clear_combo_actions(self):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None: return
        actions = state.combos[c_idx].get("actions", [])
        def _refresh(_):
            self.refresh_combo_actions_list()
            self.refresh_combo_list(select_idx=c_idx)
            self.sync_combo_actions_to_main_steps(state.combos[c_idx]["name"], [])
        self._clear_list_items(actions, f"請問是否清空組合 [{state.combos[c_idx]['name']}] 的所有動作？", _refresh, "組合所有動作")

    # ======================= 自動循環清單（掛機流程）邏輯 =======================
    def get_main_insert_index(self):
        sel = self.step_listbox.curselection()
        return sel[0] + 1 if sel else len(state.steps)

    def update_step_list(self, select_idx=None):
        self.step_listbox.delete(0, tk.END)
        for i, s in enumerate(state.steps):
            self.step_listbox.insert(tk.END, format_action_summary(s, index=i))
        last_idx = getattr(self, "last_active_step_idx", None)
        if last_idx is not None and 0 <= last_idx < len(state.steps):
            try:
                self.step_listbox.itemconfigure(last_idx, background="#2a4365", foreground="#63b3ed")
            except Exception:
                pass
        if select_idx is not None and 0 <= select_idx < len(state.steps):
            self.step_listbox.selection_set(select_idx)
            self.step_listbox.see(select_idx)

    def test_run_selected_main_step(self):
        sel = self.step_listbox.curselection()
        if not sel:
            return self.set_status("請先在清單中選擇要試跑的主步驟！")
        idx = sel[0]
        s = state.steps[idx]

        def _run():
            if s.get("type") == "combo":
                c_name = s.get("name", "組合")
                sub_actions = s.get("actions", [])
                if not sub_actions:
                    return self.set_status(f"組合 [{c_name}] 內無任何動作！")
                for sub_idx, sub_act in enumerate(sub_actions):
                    if state.stop_event.is_set(): break
                    self.execute_single_action(sub_act, f"[{c_name}#{sub_idx+1}]")
            else:
                self.execute_single_action(s, f"步驟#{idx+1}")

        self.run_in_test_thread(f"步驟 #{idx+1}", _run)

    def test_run_execution_flow(self):
        """一次性試跑整個掛機執行流程（所有主步驟依序執行一輪）"""
        if not state.steps:
            return self.set_status("掛機流程清單內無任何步驟可試跑！")
        self.run_in_test_thread("掛機流程", lambda: engine.test_run_execution_flow_worker(self))

    def edit_selected_main_step(self):
        sel = self.step_listbox.curselection()
        if not sel: return self.set_status("請先在掛機流程選擇步驟！")
        idx = sel[0]
        if self.prompt_edit_action(state.steps[idx], step_idx=idx):
            self.update_step_list(idx)
            self.set_status(f"已成功更新主步驟 #{idx+1}")
            self.trigger_hot_reload()

    def move_main_step(self, delta):
        sel = self.step_listbox.curselection()
        idx = sel[0] if sel else None
        self._move_list_item(state.steps, idx, delta, self.update_step_list, item_name="主步驟")

    def duplicate_main_step(self):
        sel = self.step_listbox.curselection()
        idx = sel[0] if sel else None
        self._duplicate_list_item(state.steps, idx, self.update_step_list, item_name="主步驟")

    def delete_main_step(self):
        sel = self.step_listbox.curselection()
        idx = sel[0] if sel else None
        self._delete_list_item(state.steps, idx, self.update_step_list, item_name="主步驟")

    def clear_main_steps(self):
        self._clear_list_items(state.steps, "請問是否清空整個掛機流程？\n清空後未儲存的內容無法還原！", self.update_step_list, "掛機流程")

    # ======================= 動作執行調度器委派 =======================
    def dispatch_action(self, act, parent_desc, current_vars=None, current_combos=None, depth=0, visited_set=None, is_test=False, round_prefix=""):
        return engine.dispatch_action(
            self,
            act,
            parent_desc,
            current_vars=current_vars,
            current_combos=current_combos,
            depth=depth,
            visited_set=visited_set,
            is_test=is_test,
            round_prefix=round_prefix
        )

    def execute_single_action(self, act, desc):
        engine.execute_single_action(self, act, desc)

    # ======================= 主執行引擎 =======================
    def toggle_run(self):
        if state.running or state.is_testing:
            was_test = state.is_testing
            state.running = False
            state.is_testing = False
            state.stop_event.set()
            emergency_release_all()
            self.set_running_ui(False)
            self.set_status("試跑已手動中止！" if was_test else "已手動停止")
        else:
            if not state.steps: return self.set_status("執行清單是空的，請先加入步驟！")
            with state.steps_lock:
                state.active_steps = copy.deepcopy(state.steps)
                state.active_combos = copy.deepcopy(state.combos)
                state.active_variables = copy.deepcopy(state.variables)
                state.reload_requested = False
            state.stop_event.clear()
            state.running = True
            self.set_running_ui(True)
            self.set_status("循環運作中...")
            threading.Thread(target=self.macro_worker_loop, daemon=True).start()

    def macro_worker_loop(self):
        engine.macro_worker_loop(self)

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("sh.autoclicker.app.1.0")
        except Exception:
            pass
    app = App()
    app.mainloop()