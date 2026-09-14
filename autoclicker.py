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

from theme import UITheme, LogTag, resource_path, WINDOW_TITLE, BASE_WINDOW_TITLE, CONFIG_EXT
from events import EventBus, AppEvents
import state
from state import format_action_summary
from win32_api import (
    get_cursor_pos,
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
from controllers import (
    BaseController,
    VarController,
    ComboController,
    StepController,
    PeriodicTaskController
)


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

        # 全域字體與深色主題樣式配置 (深色滾動條、深色選單、微軟正黑體 UI)
        self.option_add("*Font", UITheme.FONT_NORMAL)
        from theme import setup_dark_theme
        setup_dark_theme(self)
        try:
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
        state.app_state.use_bg = True
        self.cached_use_rel = True
        state.app_state.offset_x = 0
        state.app_state.offset_y = 0

        self.var_use_bg.trace_add("write", lambda *a: setattr(self, "cached_use_bg", bool(self.var_use_bg.get())))
        self.var_use_rel.trace_add("write", lambda *a: setattr(self, "cached_use_rel", bool(self.var_use_rel.get())))
        def _update_offset(*a):
            try: state.app_state.offset_x = int(self.var_offset_x.get() or 0)
            except (ValueError, TypeError): state.app_state.offset_x = 0
            try: state.app_state.offset_y = int(self.var_offset_y.get() or 0)
            except (ValueError, TypeError): state.app_state.offset_y = 0
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

        # 初始化控制器 (Controllers: 職責解耦)
        self.var_ctrl = VarController(self)
        self.combo_ctrl = ComboController(self)
        self.step_ctrl = StepController(self)
        self.periodic_ctrl = PeriodicTaskController(self)

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

        # EventBus Subscriptions
        EventBus.subscribe(AppEvents.VARS_CHANGED, self._on_vars_changed)
        EventBus.subscribe(AppEvents.COMBOS_CHANGED, self._on_combos_changed)
        EventBus.subscribe(AppEvents.COMBO_ACTIONS_CHANGED, self._on_combo_actions_changed)
        EventBus.subscribe(AppEvents.STEPS_CHANGED, self._on_steps_changed)
        EventBus.subscribe(AppEvents.PERIODIC_TASKS_CHANGED, self._on_periodic_tasks_changed)
        EventBus.subscribe(AppEvents.STATUS_MESSAGE, self.set_status)
        EventBus.subscribe(AppEvents.LOG_MESSAGE, self.append_log)
        EventBus.subscribe(AppEvents.HIGHLIGHT_STEP, self.highlight_active_step)
        EventBus.subscribe(AppEvents.CLEAR_HIGHLIGHT_STEP, self.clear_active_step_highlight)
        EventBus.subscribe(AppEvents.HIGHLIGHT_PENDING_STEP, self.highlight_pending_step)
        EventBus.subscribe(AppEvents.HIGHLIGHT_PERIODIC_TASK, self.highlight_active_periodic_task)
        EventBus.subscribe(AppEvents.CLEAR_HIGHLIGHT_PERIODIC_TASK, self.clear_active_periodic_task_highlight)

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

    def _on_vars_changed(self, select_name=None):
        if not hasattr(self, "tree_vars"):
            return
        for item in self.tree_vars.get_children():
            self.tree_vars.delete(item)

        type_display = {"coord": "[坐標]", "key": "[按鍵]", "wait": "[停頓]"}
        for name, data in state.app_state.variables.items():
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

        var_names = list(state.app_state.variables.keys())
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

    def _on_combos_changed(self, select_idx=None):
        if not hasattr(self, "combo_listbox"):
            return
        self.combo_listbox.delete(0, tk.END)
        for i, c in enumerate(state.app_state.combos):
            act_count = len(c.get("actions", []))
            self.combo_listbox.insert(tk.END, f"{c['name']} ({act_count}動作)")
        if select_idx is not None and 0 <= select_idx < len(state.app_state.combos):
            self.combo_listbox.selection_set(select_idx)
            self.combo_ctrl.on_combo_select()
        else:
            self._refresh_call_combo_dropdown()

    def _refresh_call_combo_dropdown(self):
        idx = self.combo_ctrl.get_selected_combo_idx()
        curr_name = state.app_state.combos[idx]["name"] if idx is not None else None
        avail = [c["name"] for c in state.app_state.combos if c["name"] != curr_name]
        if hasattr(self, "cbo_call_combo"):
            self.cbo_call_combo["values"] = avail
            if avail:
                if self.var_combo_to_call.get() not in avail:
                    self.cbo_call_combo.current(0)
            else:
                self.var_combo_to_call.set("")

        all_combos = [c["name"] for c in state.app_state.combos]
        if hasattr(self, "cbo_step_call_combo"):
            self.cbo_step_call_combo["values"] = all_combos
            if all_combos:
                if self.var_step_combo_to_call.get() not in all_combos:
                    self.cbo_step_call_combo.current(0)
            else:
                self.var_step_combo_to_call.set("")

    def _on_combo_actions_changed(self, select_idx=None):
        if not hasattr(self, "combo_act_listbox"):
            return
        self.combo_act_listbox.delete(0, tk.END)
        idx = self.combo_ctrl.get_selected_combo_idx()
        if idx is None:
            return
        actions = state.app_state.combos[idx].get("actions", [])
        for i, act in enumerate(actions):
            self.combo_act_listbox.insert(tk.END, format_action_summary(act, index=i))
        if select_idx is not None and 0 <= select_idx < len(actions):
            self.combo_act_listbox.selection_set(select_idx)
            self.combo_act_listbox.see(select_idx)

    def _on_steps_changed(self, select_idx=None):
        if not hasattr(self, "step_listbox"):
            return
        self.step_listbox.delete(0, tk.END)
        for i, s in enumerate(state.app_state.steps):
            self.step_listbox.insert(tk.END, format_action_summary(s, index=i))
        last_idx = getattr(self, "last_active_step_idx", None)
        if last_idx is not None and 0 <= last_idx < len(state.app_state.steps):
            try:
                self.step_listbox.itemconfigure(last_idx, background="#2a4365", foreground="#63b3ed")
            except tk.TclError:
                pass
        if select_idx is not None and 0 <= select_idx < len(state.app_state.steps):
            self.step_listbox.selection_set(select_idx)
            self.step_listbox.see(select_idx)

        # 空清單視覺引導 (Empty State Placeholder)
        lbl_empty = getattr(self, "lbl_empty_steps", None)
        if lbl_empty:
            if len(state.app_state.steps) == 0:
                lbl_empty.place(relx=0.5, rely=0.5, anchor="center")
                lbl_empty.lift()
            else:
                lbl_empty.place_forget()

    def _on_periodic_tasks_changed(self, select_idx=None):
        if not hasattr(self, "periodic_listbox"):
            return
        self.periodic_listbox.delete(0, tk.END)
        for pt in state.app_state.periodic_tasks:
            self.periodic_listbox.insert(tk.END, pt)
        if select_idx is not None and 0 <= select_idx < len(state.app_state.periodic_tasks):
            self.periodic_listbox.selection_set(select_idx)
            self.periodic_listbox.see(select_idx)

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
        state.app_state.stop_event.set()
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

        tasks_executed = 0
        while True:
            try:
                fn = self.ui_task_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
                tasks_executed += 1
            except Exception as e:
                self.append_log(LogTag.ALERT, f"UI 任務執行失敗: {e}")

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
                    self.append_log(LogTag.ALERT, f"定時任務倒數更新異常: {e}")

        # 動態輪詢間隔：有活動或運行/試跑時 50ms 高頻響應，空閒時 200ms 節能輪詢
        is_active = bool(log_items) or (tasks_executed > 0) or state.is_running() or state.is_in_testing()
        next_interval = 50 if is_active else 200
        if not self.is_closing:
            self.after(next_interval, self.poll_ui_queues)

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

    def set_status(self, msg, tag=None):
        """將狀態與操作回饋訊息統一寫入執行日誌，支援明確 tag 或智慧關鍵字自動分類"""
        if not self.is_closing and msg:
            s_msg = str(msg).strip()
            if tag is not None:
                final_tag = tag
            elif any(w in s_msg for w in ("失敗", "異常", "錯誤", "請先", "未綁定", "找不到", "無法")):
                final_tag = LogTag.ALERT
            elif "試跑" in s_msg:
                final_tag = LogTag.TEST
            else:
                final_tag = LogTag.INFO
            self.append_log(final_tag, s_msg)
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
                self.clear_active_step_highlight()
                self.clear_active_periodic_task_highlight()
        self.run_on_ui_thread(_u)

    def run_in_test_thread(self, task_name, task_fn):
        """統一的非同步試跑安全守衛與執行緒啟動器 (原子化狀態校驗與切換，杜絕 check-then-act 競態)"""
        ok, reason = state.try_start_testing()
        if not ok:
            if reason == "running":
                return self.set_status("巨集正在循環執行中，請先停止再試跑！")
            else:
                return self.set_status("已有試跑任務正在執行中，請稍候！")

        state.app_state.stop_event.clear()
        self.set_running_ui(True, is_test=True)

        import copy
        state.app_state.test_steps = copy.deepcopy(state.app_state.steps)
        state.app_state.test_combos = copy.deepcopy(state.app_state.combos)
        state.app_state.test_variables = copy.deepcopy(state.app_state.variables)

        def _worker():
            try:
                self.append_log("試跑", f"▶ 正在試跑: {task_name}")
                task_fn()
                if state.app_state.stop_event.is_set():
                    self.append_log("試跑", f"⏹ {task_name} 試跑已手動中止！")
                else:
                    self.append_log("試跑", f"✓ {task_name} 試跑完成！")
            except Exception as e:
                self.append_log("警示", f"✕ {task_name} 試跑異常: {e}")
            finally:
                state.app_state.test_steps.clear()
                state.app_state.test_combos.clear()
                state.app_state.test_variables.clear()
                state.app_state.is_testing = False
                emergency_release_all()
                self.set_running_ui(False)

        threading.Thread(target=_worker, daemon=True).start()

    def track_mouse_live(self):
        """實時監控游標坐標並更新 HUD (具備坐標變更感知與動態休眠，降低系統調用消耗)"""
        if self.is_closing:
            return
        next_interval = 200
        try:
            # 視窗最小化時停止高頻追蹤，進入休眠輪詢
            if hasattr(self, "state") and self.state() == "iconic":
                if not self.is_closing:
                    self.after(1000, self.track_mouse_live)
                return

            pos_x, pos_y = get_cursor_pos()
            cur_raw = (int(pos_x), int(pos_y))
            last_raw = getattr(self, "_last_raw_mouse_pos", None)
            is_moved = (cur_raw != last_raw)
            self._last_raw_mouse_pos = cur_raw

            # 僅在游標位置變更或首度初始化時執行 Win32 ScreenToClient 轉換與 UI 渲染
            if is_moved or not hasattr(self, "_last_mouse_hud_text"):
                if IS_WINDOWS and state.app_state.target_hwnd and getattr(self, "cached_use_rel", True) and user32:
                    pt = POINT(cur_raw[0], cur_raw[1])
                    user32.ScreenToClient(state.app_state.target_hwnd, ctypes.byref(pt))
                    new_text = f"游標實時坐標(相對): ({pt.x}, {pt.y})"
                else:
                    new_text = f"游標實時坐標(螢幕): ({cur_raw[0]}, {cur_raw[1]})"
                if new_text != getattr(self, "_last_mouse_hud_text", None):
                    self._last_mouse_hud_text = new_text
                    self.lbl_mouse_hud.config(text=new_text)

            # 動態輪詢頻率休眠優化：
            # 若巨集穩定掛機中，將更新間隔拉長至 1000ms 節省 CPU 資源；游標移動時 200ms；靜止時 500ms。
            if state.is_running() or state.is_in_testing():
                next_interval = 1000
            elif is_moved:
                next_interval = 200
            else:
                next_interval = 500
        except (tk.TclError, OSError, AttributeError):
            next_interval = 1000

        if not self.is_closing:
            self.after(next_interval, self.track_mouse_live)

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
        if not IS_WINDOWS or not state.app_state.target_hwnd or not user32:
            return self.set_status("未綁定有效視窗，無法定位！")

        hwnd = state.app_state.target_hwnd
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
        if not state.app_state.target_hwnd:
            messagebox.showwarning("提示", "尚未綁定目標視窗，請先在上方選擇遊戲視窗！", parent=self)
            if on_cancel: on_cancel()
            return

        btn_cn = "右鍵" if btn == "right" else "左鍵"
        force_bring_window_to_front(state.app_state.target_hwnd)
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

            pos_x, pos_y = get_cursor_pos()
            if IS_WINDOWS and state.app_state.target_hwnd and self.var_use_rel.get() and user32:
                pt = POINT(int(pos_x), int(pos_y))
                user32.ScreenToClient(state.app_state.target_hwnd, ctypes.byref(pt))
                coord_desc = f"({pt.x}, {pt.y})"
                rx, ry, rel = pt.x, pt.y, True
            else:
                coord_desc = f"({pos_x}, {pos_y})"
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
    def clear_active_step_highlight(self):
        """清除主畫面掛機流程清單中當前步驟的高亮狀態 (例如定時任務插隊執行期間或停止執行時)"""
        def _clear():
            if self.is_closing: return
            if hasattr(self, "step_listbox") and self.step_listbox.winfo_exists():
                last_idx = getattr(self, "last_active_step_idx", None)
                if last_idx is not None and 0 <= last_idx < self.step_listbox.size():
                    try:
                        self.step_listbox.itemconfigure(last_idx, background=UITheme.BG_DARK, foreground=UITheme.TEXT_MAIN)
                    except tk.TclError:
                        pass
                self.last_active_step_idx = None
        self.run_on_ui_thread(_clear)

    def highlight_active_step(self, idx, sub_idx=None):
        """在主畫面清單中以獨立背景色高亮當前執行中的步驟，並根據設定自動滾動，絕不干擾使用者選取"""
        if idx is None:
            return self.clear_active_step_highlight()

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

    def highlight_pending_step(self, idx):
        """在主畫面掛機流程清單中以待命色 (琥珀暖金) 標記即將在定時任務後接續執行的下一動作"""
        def _pending():
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
                    # 採用待命接續樣式：暖金琥珀色 (#451a03 底 + #fbbf24 字)，一眼看清定時任務結束後下一動跑哪一步！
                    lb.itemconfigure(idx, background="#451a03", foreground="#fbbf24")
                    self.last_active_step_idx = idx
                    lb.see(idx)
                except tk.TclError:
                    pass
        self.run_on_ui_thread(_pending)

    def highlight_active_periodic_task(self, idx):
        """在主畫面右側定時任務卡片清單中以專屬執行狀態 (翠綠光暈/深綠底) 高亮當前執行的定時任務"""
        def _hl():
            if self.is_closing: return
            if hasattr(self, "periodic_listbox") and hasattr(self.periodic_listbox, "highlight_active_task"):
                self.periodic_listbox.highlight_active_task(idx)
        self.run_on_ui_thread(_hl)

    def clear_active_periodic_task_highlight(self):
        """清除定時任務卡片的執行高亮狀態"""
        def _clear():
            if self.is_closing: return
            if hasattr(self, "periodic_listbox") and hasattr(self.periodic_listbox, "clear_active_highlight"):
                self.periodic_listbox.clear_active_highlight()
        self.run_on_ui_thread(_clear)

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
        if state.is_running() or state.app_state.is_testing:
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
        if state.is_running() or state.app_state.is_testing:
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
        current_hwnd = state.app_state.target_hwnd
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
            items, state.app_state.target_hwnd = ["未偵測到任何視窗"], None
        else:
            state.app_state.target_hwnd = win_list[target_idx][0]

        self.cbo_window["values"] = items
        self.cbo_window.current(target_idx)
        if state.app_state.target_hwnd:
            self.set_status(f"已綁定目標視窗 HWND: {state.app_state.target_hwnd}")

    def on_window_select(self, event=None):
        val = self.var_window.get()
        if val and val.startswith("["):
            try:
                state.app_state.target_hwnd = int(val.split("]")[0].replace("[", ""))
                self.set_status(f"已綁定目標視窗 HWND: {state.app_state.target_hwnd}")
            except (ValueError, IndexError) as e:
                state.app_state.target_hwnd = None
                self.append_log("警示", f"視窗綁定解析失敗: {e}")

    # ==========================================================================
    # 控制器方法委派 (Controller Delegation - 100% 向後相容)
    # ==========================================================================

    # --- 常用變數管理 (VarController) ---
    def refresh_variables_table(self, select_name=None):
        EventBus.emit(AppEvents.VARS_CHANGED, select_name)

    def add_variable_dialog(self):
        return self.var_ctrl.add_variable_dialog()

    def edit_selected_variable(self):
        return self.var_ctrl.edit_selected_variable()

    def delete_selected_variable(self):
        return self.var_ctrl.delete_selected_variable()

    def move_variable(self, delta):
        return self.var_ctrl.move_variable(delta)

    def _build_variable_action(self, var_name):
        return self.var_ctrl._build_variable_action(var_name)

    def add_variable_to_main_steps(self):
        return self.var_ctrl.add_variable_to_main_steps()

    def combo_add_variable_action(self):
        return self.var_ctrl.combo_add_variable_action()

    # --- 技能組合管理 (ComboController) ---
    def get_selected_combo_idx(self):
        return self.combo_ctrl.get_selected_combo_idx()

    def refresh_call_combo_dropdown(self):
        self._refresh_call_combo_dropdown()

    def refresh_combo_list(self, select_idx=None):
        EventBus.emit(AppEvents.COMBOS_CHANGED, select_idx)

    def on_combo_select(self, event=None):
        return self.combo_ctrl.on_combo_select(event)

    def add_new_combo(self):
        return self.combo_ctrl.add_new_combo()

    def duplicate_selected_combo(self):
        return self.combo_ctrl.duplicate_selected_combo()

    def rename_selected_combo(self):
        return self.combo_ctrl.rename_selected_combo()

    def delete_selected_combo(self):
        return self.combo_ctrl.delete_selected_combo()

    def add_combo_to_main_steps(self):
        return self.combo_ctrl.add_combo_to_main_steps()

    def move_combo(self, delta):
        return self.combo_ctrl.move_combo(delta)

    def get_selected_action_idx(self):
        return self.combo_ctrl.get_selected_action_idx()

    def refresh_combo_actions_list(self, select_idx=None):
        EventBus.emit(AppEvents.COMBO_ACTIONS_CHANGED, select_idx)

    def sync_combo_actions_to_main_steps(self, combo_name, new_actions):
        return self.combo_ctrl.sync_combo_actions_to_main_steps(combo_name, new_actions)

    def test_run_selected_combo_action(self):
        return self.combo_ctrl.test_run_selected_combo_action()

    def test_run_current_combo(self):
        return self.combo_ctrl.test_run_current_combo()

    def edit_selected_combo_action(self):
        return self.combo_ctrl.edit_selected_combo_action()

    def move_combo_action(self, delta):
        return self.combo_ctrl.move_combo_action(delta)

    def duplicate_combo_action(self):
        return self.combo_ctrl.duplicate_combo_action()

    def delete_combo_action(self):
        return self.combo_ctrl.delete_combo_action()

    def clear_combo_actions(self):
        return self.combo_ctrl.clear_combo_actions()

    def combo_add_call_action(self):
        return self.combo_ctrl.combo_add_call_action()

    # --- 熱更新與清單通用操作 ---
    def trigger_hot_reload(self):
        return self.step_ctrl.trigger_hot_reload()

    def _move_list_item(self, lst, idx, delta, refresh_cb, item_name="項目"):
        return self.step_ctrl._move_list_item(lst, idx, delta, refresh_cb, item_name=item_name)

    def _duplicate_list_item(self, lst, idx, refresh_cb, item_name="項目"):
        return self.step_ctrl._duplicate_list_item(lst, idx, refresh_cb, item_name=item_name)

    def _delete_list_item(self, lst, idx, refresh_cb, item_name="項目"):
        return self.step_ctrl._delete_list_item(lst, idx, refresh_cb, item_name=item_name)

    def _clear_list_items(self, lst, confirm_msg, refresh_cb, status_msg):
        return self.step_ctrl._clear_list_items(lst, confirm_msg, refresh_cb, status_msg)

    def _insert_action_to_target(self, action_dict, is_combo=False, success_msg=""):
        return self.step_ctrl._insert_action_to_target(action_dict, is_combo=is_combo, success_msg=success_msg)

    # --- 掛機主步驟管理 (StepController) ---
    def get_main_insert_index(self):
        return self.step_ctrl.get_main_insert_index()

    def update_step_list(self, select_idx=None):
        EventBus.emit(AppEvents.STEPS_CHANGED, select_idx)

    def add_click_action(self, is_combo=False):
        return self.step_ctrl.add_click_action(is_combo=is_combo)

    def add_manual_click(self, is_combo=False):
        return self.step_ctrl.add_manual_click(is_combo=is_combo)

    def add_key_action(self, is_combo=False):
        return self.step_ctrl.add_key_action(is_combo=is_combo)

    def add_wait_action(self, is_combo=False):
        return self.step_ctrl.add_wait_action(is_combo=is_combo)

    def step_add_call_combo_action(self):
        return self.step_ctrl.step_add_call_combo_action()

    def step_add_variable_action(self):
        return self.step_ctrl.step_add_variable_action()

    def test_run_selected_main_step(self):
        return self.step_ctrl.test_run_selected_main_step()

    def test_run_execution_flow(self):
        return self.step_ctrl.test_run_execution_flow()

    def edit_selected_main_step(self):
        return self.step_ctrl.edit_selected_main_step()

    def move_main_step(self, delta):
        return self.step_ctrl.move_main_step(delta)

    def duplicate_main_step(self):
        return self.step_ctrl.duplicate_main_step()

    def delete_main_step(self):
        return self.step_ctrl.delete_main_step()

    def clear_main_steps(self):
        return self.step_ctrl.clear_main_steps()

    # --- 定時週期任務管理 (PeriodicTaskController) ---
    def update_periodic_list(self, select_idx=None):
        EventBus.emit(AppEvents.PERIODIC_TASKS_CHANGED, select_idx)

    def add_new_periodic_task(self):
        return self.periodic_ctrl.add_new_periodic_task()

    def edit_selected_periodic_task(self):
        return self.periodic_ctrl.edit_selected_periodic_task()

    def toggle_selected_periodic_task(self):
        return self.periodic_ctrl.toggle_selected_periodic_task()

    def duplicate_selected_periodic_task(self):
        return self.periodic_ctrl.duplicate_selected_periodic_task()

    def delete_selected_periodic_task(self):
        return self.periodic_ctrl.delete_selected_periodic_task()

    def test_run_selected_periodic_task(self):
        return self.periodic_ctrl.test_run_selected_periodic_task()

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
        engine.execute_single_action(act, desc)

    # ======================= 主執行引擎 =======================
    def toggle_run(self):
        with state.running_lock:
            is_active = state.is_running() or state.app_state.is_testing
            was_test = state.app_state.is_testing
            if is_active:
                state.set_running(False)
                state.app_state.is_testing = False

        if is_active:
            state.app_state.stop_event.set()
            emergency_release_all()
            self.set_running_ui(False)
            msg = "試跑已手動中止！" if was_test else "已手動停止"
            self.set_status(msg)
            self.append_log("系統", f"⏹ 巨集{msg}")
        else:
            has_enabled_periodic = any(pt.get("enabled", True) for pt in state.app_state.periodic_tasks)
            if not state.app_state.steps and not has_enabled_periodic:
                return self.set_status("掛機流程清單與定時任務均為空，請先加入步驟或定時任務！")
            state.get_state().snapshot_active(reload_requested=False)
            state.app_state.stop_event.clear()
            state.set_running(True)
            self.set_running_ui(True)
            self.set_status("循環運作中...")
            win_title = self.var_window.get() if hasattr(self, "var_window") else ""
            mode_str = "後台模式" if state.app_state.use_bg else "前台模式"
            self.append_log("系統", f"▶ 巨集啟動 ({mode_str} | 目標: {win_title})")
            threading.Thread(target=self.macro_worker_loop, daemon=True).start()

    def macro_worker_loop(self):
        engine.macro_worker_loop()


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("sh.autoclicker.app.1.0")
        except (AttributeError, OSError):
            pass
    app = App()
    app.mainloop()