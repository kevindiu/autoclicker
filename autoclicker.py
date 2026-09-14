import os
import sys
import time
import uuid
import copy
import ctypes
import threading
import queue
import pyautogui
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from theme import UITheme, resource_path, WINDOW_TITLE, BASE_WINDOW_TITLE, CONFIG_EXT
import state
from state import format_action_summary
from win32_api import (
    IS_WINDOWS,
    user32,
    POINT,
    WNDENUMPROC,
    emergency_release_all,
    force_bring_window_to_front,
    is_window_alive,
    VK_SPACE,
    VK_ESCAPE,
    KEY_PRESSED_MASK
)
from panels import LeftPanel, RightPanel
import config_manager
import dialogs
import engine

# ==============================================================================
# 全域資料與相容別名動態代理 (解決 L40-47 模組級淺引用在 reset / 重新賦值後斷裂問題)
# ==============================================================================
_STATE_PROXY_ATTRS = (
    "combos", "steps", "variables", "periodic_tasks",
    "active_steps", "active_combos", "active_variables", "active_periodic_tasks",
    "running_lock", "steps_lock", "stop_event", "target_hwnd",
    "is_testing", "reload_requested", "currently_held_keys",
    "currently_held_keys_lock", "periodic_timers", "periodic_timers_lock",
    "running"
)

def __getattr__(name):
    """PEP 562 模組層級動態屬性委派：始終即時指向 state 的當前資料，避免 reset / 重新賦值淺引用斷裂"""
    if name in _STATE_PROXY_ATTRS or hasattr(state, name):
        return getattr(state, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

def __dir__():
    return sorted(set(globals().keys()) | set(_STATE_PROXY_ATTRS) | set(dir(state)))

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
        except tk.TclError:
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
            except (ValueError, TypeError): self.cached_offset_x = 0
            try: self.cached_offset_y = int(self.var_offset_y.get() or 0)
            except (ValueError, TypeError): self.cached_offset_y = 0
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

        # 執行日誌控制變數與佇列
        self.var_log_autoscroll = tk.BooleanVar(value=True)
        self.log_queue = queue.Queue()
        self.log_count = 0

        self.last_active_step_idx = None

        self.grid_columnconfigure(0, weight=1, uniform="main_cols")
        self.grid_columnconfigure(1, weight=1, uniform="main_cols")
        self.grid_rowconfigure(0, weight=1)

        self.build_left_panel()
        self.build_right_panel()
        self.refresh_window_dropdown()
        self.refresh_profiles()
        self.load_config()
        self.last_saved_snapshot = self.get_current_data_snapshot()
        self.refresh_variables_table()
        self.update_periodic_list()
        self.track_mouse_live()

        # 執行緒安全的 UI 通訊佇列
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
        except (tk.TclError, OSError):
            pass

    def get_current_data_snapshot(self):
        """獲取當前設定資料的序列化字串，用於精確對比是否有未儲存的變更"""
        return state.get_data_snapshot()

    def has_unsaved_changes(self):
        """檢查當前記憶體中的設定相較於最後儲存狀態是否有更新"""
        if not hasattr(self, "last_saved_snapshot") or not self.last_saved_snapshot:
            return False
        return state.has_unsaved_changes(self.last_saved_snapshot)

    def on_close(self):
        """主視窗關閉事件處理 (若有未儲存之變更則提示使用者儲存)"""
        if self.has_unsaved_changes():
            curr_profile = self.var_profile_name.get().strip() or "default"
            ans = messagebox.askyesnocancel(
                "儲存確認",
                f"檢測到設定已修改，請問是否儲存至「{curr_profile}」？\n\n- 是(Yes)：儲存變更並退出\n- 否(No)：不儲存並直接退出\n- 取消(Cancel)：返回程式",
                parent=self
            )
            if ans is None:
                return
            elif ans is True:
                try:
                    config_manager.save_profile_file(curr_profile, state, CONFIG_EXT)
                except Exception as e:
                    if not messagebox.askyesno("儲存失敗", f"儲存失敗 ({e})，是否仍要強制退出？", parent=self):
                        return

        self.is_closing = True
        state.set_running(False)
        state.stop_event.set()
        emergency_release_all()
        self.destroy()

    def toggle_topmost(self):
        """切換助手視窗置頂狀態"""
        self.attributes("-topmost", self.var_topmost.get())

    def poll_ui_queues(self):
        """定期由主執行緒消費背景執行緒發送的 UI 更新事件 (批次摺疊更新，避免頻繁渲染)"""
        if self.is_closing: return

        # 批次消費執行日誌佇列 (嚴格維持最新 200 筆)
        log_items = []
        try:
            while True:
                log_items.append(self.log_queue.get_nowait())
        except queue.Empty:
            pass

        if log_items and hasattr(self, "txt_log") and self.txt_log.winfo_exists():
            try:
                self.txt_log.config(state="normal")
                for t_str, tag, text in log_items:
                    self.txt_log.insert(tk.END, f"[{t_str}] ", "time")
                    self.txt_log.insert(tk.END, f"[{tag}] ", f"tag_{tag}")
                    self.txt_log.insert(tk.END, f"{text}\n", f"text_{tag}")
                    if self.log_count >= 200:
                        self.txt_log.delete("1.0", "2.0")
                    else:
                        self.log_count += 1

                if self.var_log_autoscroll.get():
                    self.txt_log.see(tk.END)
                self.txt_log.config(state="disabled")
            except tk.TclError:
                pass

        while True:
            try:
                fn = self.ui_task_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception as e:
                self.append_log("警示", f"UI 任務執行失敗: {e}")

        # 定時週期任務即時倒數與設定值更新 (每 200ms 刷新一次)
        now_ts = time.time()
        if now_ts - getattr(self, "_last_timer_ui_update", 0) >= 0.2:
            self._last_timer_ui_update = now_ts
            if hasattr(self, "periodic_listbox") and hasattr(self.periodic_listbox, "update_countdowns"):
                try:
                    self.periodic_listbox.update_countdowns()
                except tk.TclError:
                    pass
                except Exception as e:
                    self.append_log("警示", f"定時任務倒數更新異常: {e}")

        if not self.is_closing:
            self.after(50, self.poll_ui_queues)

    def append_log(self, tag, text):
        """線程安全地推送一筆格式化日誌至執行日誌佇列"""
        if not self.is_closing:
            try:
                t_str = time.strftime("%H:%M:%S")
                self.log_queue.put((t_str, tag, str(text).strip()))
            except (queue.Full, AttributeError):
                pass

    def clear_logs(self):
        """清空日誌視窗與緩衝計數"""
        if hasattr(self, "txt_log") and self.txt_log.winfo_exists():
            try:
                self.txt_log.config(state="normal")
                self.txt_log.delete("1.0", tk.END)
                self.txt_log.config(state="disabled")
                self.log_count = 0
            except tk.TclError:
                pass

    def set_status(self, msg):
        """將狀態與操作回饋訊息統一寫入執行日誌，杜絕訊息被靜默丟棄"""
        if not self.is_closing and msg:
            s_msg = str(msg).strip()
            if any(w in s_msg for w in ("失敗", "異常", "錯誤", "請先", "未綁定", "找不到", "無法")):
                tag = "警示"
            elif "試跑" in s_msg:
                tag = "試跑"
            else:
                tag = "系統"
            self.append_log(tag, s_msg)
        return msg

    def run_on_ui_thread(self, fn):
        """在主執行緒安全執行 UI 變更回調"""
        if not self.is_closing:
            try:
                if threading.current_thread() is threading.main_thread():
                    fn()
                else:
                    self.ui_task_queue.put(fn)
            except Exception as e:
                self.append_log("警示", f"UI 任務派遣失敗: {e}")

    def set_running_ui(self, is_running, is_test=False):
        """執行緒安全地更新啟動/停止按鈕 UI"""
        def _u():
            if self.is_closing: return
            if is_running:
                btn_text = "■ 停止試跑" if is_test else "■ 停止運行"
                self.btn_toggle.config(text=btn_text, bg=UITheme.ACCENT_RED, activebackground=UITheme.ACCENT_RED_HOVER)
            else:
                self.btn_toggle.config(text="▶ 開始循環執行", bg=UITheme.ACCENT_GREEN, activebackground=UITheme.ACCENT_GREEN_HOVER)
                if hasattr(self, "periodic_listbox") and hasattr(self.periodic_listbox, "update_countdowns"):
                    try:
                        self.periodic_listbox.update_countdowns()
                    except (tk.TclError, AttributeError):
                        pass
                if hasattr(self, "step_listbox") and self.step_listbox.winfo_exists():
                    last_idx = getattr(self, "last_active_step_idx", None)
                    if last_idx is not None and 0 <= last_idx < self.step_listbox.size():
                        try:
                            self.step_listbox.itemconfigure(last_idx, background=UITheme.BG_DARK, foreground=UITheme.TEXT_MAIN)
                        except tk.TclError:
                            pass
                    self.last_active_step_idx = None
        self.run_on_ui_thread(_u)

    def run_in_test_thread(self, task_name, task_fn):
        """統一的非同步試跑安全守衛與執行緒啟動器"""
        if state.is_running():
            return self.set_status("巨集正在循環執行中，請先停止再試跑！")
        if state.is_testing:
            return self.set_status("已有試跑任務正在執行中，請稍候！")

        state.is_testing = True
        state.stop_event.clear()
        self.set_running_ui(True, is_test=True)

        def _worker():
            try:
                self.append_log("試跑", f"▶ 正在試跑: {task_name}")
                task_fn()
                if state.stop_event.is_set():
                    self.append_log("試跑", f"⏹ {task_name} 試跑已手動中止！")
                else:
                    self.append_log("試跑", f"✓ {task_name} 試跑完成！")
            except Exception as e:
                self.append_log("警示", f"✕ {task_name} 試跑異常: {e}")
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
        except (tk.TclError, OSError, AttributeError):
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
        """定位並閃爍目標遊戲視窗 (非同步背景閃爍，杜絕 UI 主執行緒凍結)"""
        if not IS_WINDOWS or not state.target_hwnd or not user32:
            return self.set_status("未綁定有效視窗，無法定位！")

        hwnd = state.target_hwnd
        try:
            force_bring_window_to_front(hwnd)
            def _flash_worker():
                for _ in range(4):
                    if not is_window_alive(hwnd):
                        break
                    try:
                        user32.FlashWindow(hwnd, True)
                    except (OSError, ctypes.ArgumentError):
                        break
                    time.sleep(0.08)
            threading.Thread(target=_flash_worker, daemon=True).start()
            self.set_status(f"已定位並閃爍視窗 HWND: {hwnd}")
        except Exception as e:
            self.append_log("警示", f"視窗定位失敗: {e}")

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
            user32.GetAsyncKeyState(VK_SPACE)
            user32.GetAsyncKeyState(VK_ESCAPE)

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
                if user32.GetAsyncKeyState(VK_SPACE) & KEY_PRESSED_MASK:
                    is_handled[0] = True
                    banner.destroy()
                    self.force_bring_self_to_front()
                    self.set_status(f"已成功設定{btn_cn}位置: ({rx}, {ry})")
                    on_finish(rx, ry, rel)
                    return

                if user32.GetAsyncKeyState(VK_ESCAPE) & KEY_PRESSED_MASK:
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
                except tk.TclError:
                    pass

            if 0 <= idx < lb_sz:
                try:
                    lb.itemconfigure(idx, background="#2a4365", foreground="#63b3ed")
                    self.last_active_step_idx = idx
                    lb.see(idx)
                except tk.TclError:
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
        self.left_panel = LeftPanel(self, app=self)
        self.left_panel.grid(row=0, column=0, padx=(10, 5), pady=10, sticky="nsew")

    # ======================= 右欄佈局 =======================
    def build_right_panel(self):
        self.right_panel = RightPanel(self, app=self)
        self.right_panel.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="nsew")

    def on_combo_double_click_add(self, event=None):
        """雙擊組合清單時直接加入掛機流程"""
        self.add_combo_to_main_steps()

    # ======================= 設定檔管理 (附帶 Schema 遷移) =======================
    def get_profile_files(self):
        return config_manager.get_profile_files(CONFIG_EXT)

    def refresh_profiles(self, select_name=None):
        config_manager.ensure_default_profile(CONFIG_EXT)
        profiles = self.get_profile_files()
        if not profiles:
            profiles = ["default"]

        self.cbo_profile["values"] = profiles
        if select_name and select_name in profiles:
            self.cbo_profile.set(select_name)
        elif self.var_profile_name.get() in profiles:
            self.cbo_profile.set(self.var_profile_name.get())
        else:
            self.cbo_profile.current(0)

    def create_new_profile(self):
        if state.is_running() or state.is_testing:
            return self.set_status("巨集正在執行或試跑中，請先停止再新建設定檔！")
        name = simpledialog.askstring("新建設定檔", "請輸入新設定檔名稱 (毋須輸入副檔名):", parent=self)
        if not name or not name.strip(): return
        name = name.strip()
        fn = f"{name}{CONFIG_EXT}"
        if os.path.exists(fn):
            if not messagebox.askyesno("檔案覆蓋確認", f"設定檔「{name}」已存在！\n請問是否確認覆蓋原有設定？", parent=self):
                return
        try:
            config_manager.save_profile_file(name, state, CONFIG_EXT)
            self.refresh_profiles(select_name=name)
            self.last_saved_snapshot = self.get_current_data_snapshot()
            self.set_status(f"已新建並儲存至 {fn}")
        except Exception as e:
            self.set_status(f"新建失敗: {e}")
            self.append_log("警示", f"新建設定檔失敗: {e}")

    def save_config(self):
        name = self.var_profile_name.get().strip()
        if not name: return self.set_status("請先選擇或新建設定檔")
        fn = f"{name}{CONFIG_EXT}"
        if os.path.exists(fn):
            if not messagebox.askyesno("檔案覆蓋確認", f"請問是否確認覆蓋「{name}」的原有設定？", parent=self):
                return self.set_status("已取消儲存")
        try:
            config_manager.save_profile_file(name, state, CONFIG_EXT)
            self.set_status(f"已成功儲存至 {fn}")
            self.refresh_profiles(select_name=name)
            self.last_saved_snapshot = self.get_current_data_snapshot()
        except Exception as e:
            self.set_status(f"儲存失敗: {e}")
            self.append_log("警示", f"儲存設定檔失敗: {e}")

    def load_config(self):
        if state.is_running() or state.is_testing:
            return self.set_status("巨集正在執行或試跑中，請先停止再載入設定檔！")
        name = self.var_profile_name.get().strip()
        if not name: return
        fn = f"{name}{CONFIG_EXT}"
        if not os.path.exists(fn): return self.set_status(f"找不到檔案：{fn}")
        try:
            config_manager.load_profile_file(name, state, CONFIG_EXT)
            self.refresh_variables_table()
            self.refresh_combo_list()
            self.refresh_combo_actions_list()
            self.update_step_list()
            self.update_periodic_list()
            self.last_saved_snapshot = self.get_current_data_snapshot()
            self.set_status(f"成功載入設定檔：{name}")
        except Exception as e:
            self.set_status(f"載入失敗: {e}")
            self.append_log("警示", f"載入設定檔失敗: {e}")

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
                if t and BASE_WINDOW_TITLE not in t:
                    windows.append((hwnd, t))
            return True
        cb = WNDENUMPROC(enum_proc)
        user32.EnumWindows(cb, 0)
        return windows

    def refresh_window_dropdown(self):
        win_list = self.get_window_list()
        items, target_idx = [], 0
        current_hwnd = state.target_hwnd
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
            except (ValueError, IndexError) as e:
                state.target_hwnd = None
                self.append_log("警示", f"視窗綁定解析失敗: {e}")

    # ======================= 變數管理邏輯 =======================
    def refresh_variables_table(self, select_name=None):
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

        if select_name and hasattr(self.tree_vars, "select"):
            self.tree_vars.select(select_name)

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
        self.append_log("系統", f"🗑 已刪除變數：【{var_name}】")

    def move_variable(self, delta):
        sel = self.tree_vars.selection()
        if not sel:
            return self.set_status("請先在常用變數庫點選要移動的變數！")
        sel_name = sel[0]
        keys = list(state.variables.keys())
        if sel_name not in keys:
            return
        idx = keys.index(sel_name)
        target = idx + delta
        if 0 <= target < len(keys):
            keys[idx], keys[target] = keys[target], keys[idx]
            new_vars = {k: state.variables[k] for k in keys}
            state.variables.clear()
            state.variables.update(new_vars)
            with state.steps_lock:
                state.active_variables = copy.deepcopy(state.variables)
                state.reload_requested = True
            self.refresh_variables_table(select_name=sel_name)
            direction = "上移" if delta < 0 else "下移"
            self.set_status(f"已將變數【{sel_name}】{direction}至 #{target+1}")
            self.trigger_hot_reload()
        else:
            self.set_status("已在變數清單最頂或最底，無法再移動！")

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
            except (ValueError, TypeError): sec = 1.0
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
            self.combo_listbox.insert(tk.END, f"{c['name']} ({act_count}動作)")
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
        name = self.var_combo_name.get().strip()
        if not name:
            count = len(state.combos) + 1
            name = f"組合{count}"
            while any(c["name"] == name for c in state.combos):
                count += 1
                name = f"組合{count}"
        elif any(c["name"] == name for c in state.combos):
            messagebox.showwarning("名稱重覆", f"組合名稱「{name}」已存在！請使用其他名稱。", parent=self)
            return

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
        if not new_name:
            messagebox.showwarning("名稱錯誤", "組合名稱不能為空！", parent=self)
            return
        old_name = state.combos[idx]["name"]
        if new_name == old_name:
            self.set_status(f"組合名稱未變更: [{old_name}]")
            return
        if any(c["name"] == new_name for c in state.combos):
            messagebox.showwarning("名稱重覆", f"組合名稱「{new_name}」已存在！請使用其他名稱。", parent=self)
            return

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
        act_cnt = len(state.combos[idx].get("actions", []))
        if not messagebox.askyesno("刪除組合確認", f"確定要刪除組合【{name}】嗎？組合內的所有動作將會一併清除！", parent=self):
            return
        del state.combos[idx]
        new_sel = min(idx, len(state.combos) - 1) if state.combos else None
        self.refresh_combo_list(select_idx=new_sel)
        self.on_combo_select()
        self.update_step_list()
        self.append_log("系統", f"🗑 已刪除技能組合【{name}】（內含 {act_cnt} 個動作）")
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

    def move_combo(self, delta):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None:
            return self.set_status("請先在組合清單點選要移動的組合！")
        def _refresh(target):
            self.refresh_combo_list(select_idx=target)
        self._move_list_item(state.combos, c_idx, delta, _refresh, item_name="技能組合")

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
        if state.is_running():
            with state.steps_lock:
                state.active_steps = copy.deepcopy(state.steps)
                state.active_combos = copy.deepcopy(state.combos)
                state.active_variables = copy.deepcopy(state.variables)
                state.active_periodic_tasks = copy.deepcopy(state.periodic_tasks)
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
        removed_item = lst[idx]
        del lst[idx]
        new_sel = min(idx, len(lst) - 1) if lst else None
        refresh_cb(new_sel)

        item_desc = ""
        if isinstance(removed_item, dict):
            item_desc = f": {format_action_summary(removed_item)}"

        self.append_log("系統", f"🗑 已移除{item_name} #{idx+1}{item_desc}")
        self.trigger_hot_reload()

    def _clear_list_items(self, lst, confirm_msg, refresh_cb, status_msg):
        if not lst: return self.set_status(f"{status_msg}本來就是空的")
        if messagebox.askyesno("清空確認", confirm_msg, parent=self):
            cnt = len(lst)
            lst.clear()
            refresh_cb(None)
            self.append_log("系統", f"🗑 已清空{status_msg}（共移除 {cnt} 個步驟/動作）")
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
        if state.is_running():
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
            except tk.TclError:
                pass
        if select_idx is not None and 0 <= select_idx < len(state.steps):
            self.step_listbox.selection_set(select_idx)
            self.step_listbox.see(select_idx)

        # 空清單視覺引導 (Empty State Placeholder)
        lbl_empty = getattr(self, "lbl_empty_steps", None)
        if lbl_empty:
            if len(state.steps) == 0:
                lbl_empty.place(relx=0.5, rely=0.5, anchor="center")
                lbl_empty.lift()
            else:
                lbl_empty.place_forget()

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

    # ======================= 定時週期任務管理邏輯 =======================
    def update_periodic_list(self, select_idx=None):
        if not hasattr(self, "periodic_listbox"):
            return
        self.periodic_listbox.delete(0, tk.END)
        for pt in state.periodic_tasks:
            self.periodic_listbox.insert(tk.END, pt)
        if select_idx is not None and 0 <= select_idx < len(state.periodic_tasks):
            self.periodic_listbox.selection_set(select_idx)
            self.periodic_listbox.see(select_idx)

    def add_new_periodic_task(self):
        new_pt = dialogs.prompt_edit_periodic_task(self, task=None)
        if new_pt:
            state.periodic_tasks.append(new_pt)
            new_idx = len(state.periodic_tasks) - 1
            self.update_periodic_list(new_idx)
            self.set_status(f"已新增定時任務：【{new_pt.get('name')}】(每 {new_pt.get('interval')} 秒)")
            self.trigger_hot_reload()

    def edit_selected_periodic_task(self):
        sel = self.periodic_listbox.curselection()
        if not sel:
            return self.set_status("請先在定時任務清單中選擇任務！")
        idx = sel[0]
        updated_pt = dialogs.prompt_edit_periodic_task(self, task=state.periodic_tasks[idx])
        if updated_pt:
            state.periodic_tasks[idx] = updated_pt
            self.update_periodic_list(idx)
            self.set_status(f"已更新定時任務 #{idx+1}：【{updated_pt.get('name')}】")
            self.trigger_hot_reload()

    def toggle_selected_periodic_task(self):
        sel = self.periodic_listbox.curselection()
        if not sel:
            return self.set_status("請先在定時任務清單中選擇要開關的任務！")
        idx = sel[0]
        pt = state.periodic_tasks[idx]
        pt["enabled"] = not pt.get("enabled", True)
        st_text = "啟用" if pt["enabled"] else "停用"
        self.update_periodic_list(idx)
        self.set_status(f"已將定時任務【{pt.get('name')}】切換為 [{st_text}]")
        self.trigger_hot_reload()

    def duplicate_selected_periodic_task(self):
        sel = self.periodic_listbox.curselection()
        if not sel:
            return self.set_status("請先在定時任務清單中選擇要複製的任務！")
        idx = sel[0]
        copied_pt = copy.deepcopy(state.periodic_tasks[idx])
        copied_pt["id"] = f"pt_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
        copied_pt["name"] = f"{copied_pt.get('name', '任務')}_副本"
        state.periodic_tasks.insert(idx + 1, copied_pt)
        self.update_periodic_list(idx + 1)
        self.set_status(f"已複製定時任務至 #{idx+2}")
        self.trigger_hot_reload()

    def delete_selected_periodic_task(self):
        sel = self.periodic_listbox.curselection()
        if not sel:
            return self.set_status("請先在定時任務清單中選擇要刪除的任務！")
        idx = sel[0]
        name = state.periodic_tasks[idx].get("name", "未命名")
        if not messagebox.askyesno("刪除定時任務確認", f"確定要刪除定時任務【{name}】嗎？\n刪除後無法還原！", parent=self):
            return
        del state.periodic_tasks[idx]
        new_sel = min(idx, len(state.periodic_tasks) - 1) if state.periodic_tasks else None
        self.update_periodic_list(new_sel)
        self.append_log("系統", f"🗑 已刪除定時任務 #{idx+1}：【{name}】")
        self.trigger_hot_reload()

    def test_run_selected_periodic_task(self):
        sel = self.periodic_listbox.curselection()
        if not sel:
            return self.set_status("請先在定時任務清單中選擇要試跑的任務！")
        idx = sel[0]
        pt = state.periodic_tasks[idx]
        t_name = pt.get("name", "定時任務")
        act = pt.get("action", {})
        self.run_in_test_thread(f"定時任務【{t_name}】", lambda: self.execute_single_action(act, f"[定時試跑: {t_name}]"))

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
        if state.is_running() or state.is_testing:
            was_test = state.is_testing
            state.set_running(False)
            state.is_testing = False
            state.stop_event.set()
            emergency_release_all()
            self.set_running_ui(False)
            msg = "試跑已手動中止！" if was_test else "已手動停止"
            self.set_status(msg)
            self.append_log("系統", f"⏹ 巨集{msg}")
        else:
            has_enabled_periodic = any(pt.get("enabled", True) for pt in state.periodic_tasks)
            if not state.steps and not has_enabled_periodic:
                return self.set_status("掛機流程清單與定時任務均為空，請先加入步驟或定時任務！")
            with state.steps_lock:
                state.active_steps = copy.deepcopy(state.steps)
                state.active_combos = copy.deepcopy(state.combos)
                state.active_variables = copy.deepcopy(state.variables)
                state.active_periodic_tasks = copy.deepcopy(state.periodic_tasks)
                state.reload_requested = False
            state.stop_event.clear()
            state.set_running(True)
            self.set_running_ui(True)
            self.set_status("循環運作中...")
            win_title = self.var_window.get() if hasattr(self, "var_window") else ""
            mode_str = "後台模式" if self.cached_use_bg else "前台模式"
            self.append_log("系統", f"▶ 巨集啟動 ({mode_str} | 目標: {win_title})")
            threading.Thread(target=self.macro_worker_loop, daemon=True).start()

    def macro_worker_loop(self):
        engine.macro_worker_loop(self)

# ==============================================================================
# 模組類別包裝 (保證 autoclicker 屬性讀寫均動態委派至 state，杜絕淺引用斷裂)
# ==============================================================================
class _AutoclickerModule(sys.modules[__name__].__class__):
    """自訂模組類別，攔截模組屬性讀寫，保證別名與 state 保持 100% 雙向動態同步"""
    def __getattr__(self, name):
        if name in _STATE_PROXY_ATTRS or hasattr(state, name):
            return getattr(state, name)
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    def __setattr__(self, name, value):
        if name in _STATE_PROXY_ATTRS or (hasattr(state, name) and name not in ("__class__",)):
            setattr(state, name, value)
        else:
            super().__setattr__(name, value)

    def __dir__(self):
        return sorted(set(super().__dir__()) | set(_STATE_PROXY_ATTRS) | set(dir(state)))

sys.modules[__name__].__class__ = _AutoclickerModule

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("sh.autoclicker.app.1.0")
        except (AttributeError, OSError):
            pass
    app = App()
    app.mainloop()