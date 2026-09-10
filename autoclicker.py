import os
import json
import time
import copy
import ctypes
from ctypes import wintypes
import threading
import pyautogui
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

WINDOW_TITLE = "水滸歷險 巨集助手"
CONFIG_EXT = ".shm"

# ==============================================================================
# UI 色彩與樣式主題配置 (保持原有配色一致性)
# ==============================================================================
class UITheme:
    BG_DARK = "#15171c"          # 主背景底色 / 列表底色
    BG_PANEL = "#1c1f26"         # 卡片、側欄、對話框背景
    BG_INPUT = "#2d333b"         # 輸入框底色
    BORDER = "#2d333b"           # 面板邊框
    
    TEXT_MAIN = "#f1f5f9"        # 主文字 (白色系)
    TEXT_MUTED = "#94a3b8"       # 次要/輔助文字 (灰色)
    TEXT_LABEL = "#cbd5e1"       # 標籤文字 (淡灰)
    TEXT_DISABLED = "#64748b"    # 停用步驟文字 (暗灰)
    
    ACCENT_GREEN = "#16a34a"     # 翠綠 (啟動、新增、瞄準點擊)
    ACCENT_GREEN_HOVER = "#15803d"
    
    ACCENT_BLUE = "#2563eb"      # 海軍藍 (載入、儲存、選取、修改)
    ACCENT_BLUE_HOVER = "#1d4ed8"
    
    ACCENT_INDIGO = "#4f46e5"    # 紫青 (試跑、定位視窗)
    ACCENT_INDIGO_HOVER = "#4338ca"
    
    ACCENT_RED = "#dc2626"       # 深紅 (停止、刪除)
    ACCENT_RED_HOVER = "#b91c1c"
    ACCENT_RED_DARK = "#991b1b"  # 暗紅 (清空)
    ACCENT_RED_DARK_HOVER = "#7f1d1d"
    
    BTN_GRAY = "#334155"         # 鐵灰 (輔助按鍵、上移下移、停頓)
    BTN_GRAY_HOVER = "#475569"
    
    CYAN_TITLE = "#38bdf8"       # 天藍標題
    CYAN_SUB = "#7dd3fc"         # 淺天藍副標

# ==============================================================================
# 全域資料狀態與執行緒同步物件
# ==============================================================================
combos = []
steps = []           # 主 UI 編輯器草稿 (Draft)
active_steps = []    # 背景運行實例快照 (Active Snapshot)
active_combos = []   # 背景組合運行實例快照 (Active Combo Snapshot)

running = False
is_testing = False
reload_requested = False
steps_lock = threading.Lock() # 保護 active_steps 與 active_combos
stop_event = threading.Event()
target_hwnd = None
currently_held_keys = set()   # 追蹤當前被按下的按鍵，格式: ("bg", hwnd, vk) 或 ("fg", key_str)
currently_held_keys_lock = threading.Lock()

# ==============================================================================
# Win32 底層 API 封裝與溢位防護
# ==============================================================================
IS_WINDOWS = hasattr(ctypes, "windll")

def to_lparam(val):
    """安全轉換整數為 C 語言 signed LPARAM 範圍，防止 32-bit / 64-bit ctypes 溢位"""
    val = int(val) & 0xFFFFFFFF
    return val if val < 0x80000000 else val - 0x100000000

HWND_TOPMOST = ctypes.c_void_p(-1)
HWND_NOTOPMOST = ctypes.c_void_p(-2)

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

if IS_WINDOWS:
    for fn in (lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2), lambda: ctypes.windll.user32.SetProcessDPIAware()):
        try: fn(); break
        except Exception: pass

    user32 = ctypes.windll.user32
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.FlashWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.SetWindowPos.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]

VK_MAP = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "tab": 0x09, "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
    **{str(i): 0x30 + i for i in range(10)},
    **{chr(c): 0x41 + (c - ord('a')) for c in range(ord('a'), ord('z') + 1)}
}

# ==============================================================================
# 動作執行與安全輔助函數
# ==============================================================================
def safe_sleep(seconds):
    """具備中止感知的安全等待"""
    end = time.time() + float(seconds)
    while time.time() < end:
        if stop_event.is_set():
            return False
        if not is_testing and (not running or reload_requested):
            return False
        time.sleep(0.02)
    return True

def emergency_release_all():
    """全面釋放背景與前台的所有可能卡住的滑鼠與鍵盤狀態"""
    # 1. 釋放背景滑鼠
    if IS_WINDOWS and target_hwnd:
        try:
            user32.PostMessageW(target_hwnd, 0x0202, 0, 0)
            user32.PostMessageW(target_hwnd, 0x0205, 0, 0)
        except Exception:
            pass

    # 2. 釋放登記中的背景與前台按鍵
    with currently_held_keys_lock:
        for item in list(currently_held_keys):
            try:
                if item[0] == "bg" and IS_WINDOWS:
                    _, h, vk = item
                    user32.PostMessageW(h, 0x0101, vk, to_lparam(0xC0000001))
                elif item[0] == "fg":
                    _, k = item
                    pyautogui.keyUp(k)
            except Exception:
                pass
        currently_held_keys.clear()

    # 3. 前台滑鼠防禦性釋放
    try:
        pyautogui.mouseUp(button="left")
        pyautogui.mouseUp(button="right")
    except Exception:
        pass

def post_bg_click(hwnd, client_x, client_y, offset_x=0, offset_y=0, btn="left"):
    """向指定視窗背景發送點擊訊息"""
    if not IS_WINDOWS or not hwnd:
        pyautogui.click(client_x, client_y, button=btn)
        return int(client_x), int(client_y)
    cx, cy = int(client_x) + offset_x, int(client_y) + offset_y
    lparam = to_lparam(((int(cy) & 0xFFFF) << 16) | (int(cx) & 0xFFFF))
    user32.PostMessageW(hwnd, 0x0200, 0, lparam)
    if safe_sleep(0.02):
        try:
            if btn == "right":
                user32.PostMessageW(hwnd, 0x0204, 0x0002, lparam)
            else:
                user32.PostMessageW(hwnd, 0x0201, 0x0001, lparam)
            safe_sleep(0.08)
        finally:
            if btn == "right":
                user32.PostMessageW(hwnd, 0x0205, 0, lparam)
            else:
                user32.PostMessageW(hwnd, 0x0202, 0, lparam)
    return cx, cy

def post_bg_key(hwnd, key_str):
    """向指定視窗背景發送按鍵按下與放開訊息"""
    if not IS_WINDOWS or not hwnd:
        with currently_held_keys_lock:
            currently_held_keys.add(("fg", key_str))
        try:
            pyautogui.keyDown(key_str)
            safe_sleep(0.06)
        finally:
            try: pyautogui.keyUp(key_str)
            except Exception: pass
            with currently_held_keys_lock:
                currently_held_keys.discard(("fg", key_str))
        return
    vk = VK_MAP.get(key_str.lower()) or (ord(key_str.upper()) if len(key_str) == 1 else None)
    if vk is not None:
        with currently_held_keys_lock:
            currently_held_keys.add(("bg", hwnd, vk))
        try:
            user32.PostMessageW(hwnd, 0x0100, vk, 0)
            safe_sleep(0.06)
        finally:
            user32.PostMessageW(hwnd, 0x0101, vk, to_lparam(0xC0000001))
            with currently_held_keys_lock:
                currently_held_keys.discard(("bg", hwnd, vk))

def execute_click(x, y, is_rel, use_bg, off_x, off_y, btn="left"):
    """統一派發前台或背景點擊"""
    btn_cn = "右鍵" if btn == "right" else "左鍵"
    if use_bg:
        if not is_rel:
            pt = POINT(int(x), int(y))
            user32.ScreenToClient(target_hwnd, ctypes.byref(pt))
            x, y = pt.x, pt.y
        cx, cy = post_bg_click(target_hwnd, x, y, off_x, off_y, btn=btn)
        return f"後台{btn_cn}相對:({cx},{cy})"
    else:
        if is_rel and IS_WINDOWS and target_hwnd:
            pt = POINT(int(x), int(y))
            user32.ClientToScreen(target_hwnd, ctypes.byref(pt))
            pyautogui.click(pt.x, pt.y, button=btn)
            return f"前台追蹤{btn_cn} ({pt.x},{pt.y})"
        pyautogui.click(x, y, button=btn)
        return f"前台{btn_cn} ({x},{y})"

def format_action_summary(act, index=None, with_checkbox_tag=False):
    """統一格式化動作或步驟的文字描述，100% 保持原有顯示規則"""
    atype = act.get("type", "")
    tag = ""
    if with_checkbox_tag:
        tag = "[✓] " if act.get("enabled", True) else "[✗] "

    idx_prefix = f"#{index+1:02d} " if index is not None else ""

    if atype == "click":
        prefix = "相對:" if act.get("rel") else "絕對:"
        btn_tag = "右鍵" if act.get("btn") == "right" else "左鍵"
        body = f"[{btn_tag}] -> {prefix}({act.get('x', 0)},{act.get('y', 0)})"
    elif atype == "key":
        key_str = str(act.get("key", "")).upper()
        body = f"[按鍵] -> [ {key_str} ]"
    elif atype == "wait":
        body = f"[停頓] -> {act.get('sec', 0)} 秒"
    elif atype == "call_combo":
        body = f"[呼叫] -> 組合:【{act.get('target_name', '')}】"
    elif atype == "combo":
        c_name = act.get("name", "組合")
        act_cnt = len(act.get("actions", []))
        body = f"[組合: {c_name}] ({act_cnt}個動作)"
    else:
        body = f"[{atype}]"

    return f"{tag}{idx_prefix}{body}"

# ==============================================================================
# 自訂組件：帶右側真實 Checkbox 的滾動清單 (CheckList)
# ==============================================================================
class CheckList(tk.Frame):
    def __init__(self, parent, bg=UITheme.BG_DARK, select_bg=UITheme.ACCENT_BLUE, on_select=None, on_double_click=None, on_toggle=None):
        super().__init__(parent, bg=bg)
        self.bg = bg
        self.select_bg = select_bg
        self.on_select = on_select
        self.on_double_click = on_double_click
        self.on_toggle = on_toggle

        self.canvas = tk.Canvas(self, bg=bg, bd=0, highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg=bg)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width))

        self.bind_mousewheel(self)
        self.bind_mousewheel(self.canvas)
        self.bind_mousewheel(self.scrollable_frame)

        self.rows = []
        self.selected_idx = None

    def bind_mousewheel(self, widget):
        widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
        widget.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"), add="+")
        widget.bind("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"), add="+")

    def _on_mousewheel(self, event):
        if event.delta:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def set_items(self, items, select_idx=None):
        for r in self.rows:
            r['frame'].destroy()
        self.rows.clear()

        for i, (text, is_enabled) in enumerate(items):
            rf = tk.Frame(self.scrollable_frame, bg=self.bg, pady=2, padx=4)
            rf.pack(fill="x", expand=True)

            fg_color = UITheme.TEXT_MAIN if is_enabled else UITheme.TEXT_DISABLED
            lbl = tk.Label(rf, text=text, bg=self.bg, fg=fg_color, font=("Segoe UI", 9), anchor="w")
            lbl.pack(side="left", fill="both", expand=True)

            var = tk.BooleanVar(value=is_enabled)
            chk = tk.Checkbutton(
                rf,
                variable=var,
                bg=self.bg,
                activebackground=self.bg,
                selectcolor=UITheme.BG_PANEL,
                highlightthickness=0,
                bd=0,
                cursor="hand2",
                command=lambda idx=i, v=var: self._on_chk_toggle(idx, v)
            )
            chk.pack(side="right", padx=(2, 6))

            for w in (rf, lbl):
                w.bind("<Button-1>", lambda e, idx=i: self._select_row(idx))
                w.bind("<Double-Button-1>", lambda e, idx=i: self._double_click_row(idx))
                self.bind_mousewheel(w)
            self.bind_mousewheel(chk)

            self.rows.append({'frame': rf, 'label': lbl, 'chk': chk, 'var': var, 'enabled': is_enabled})

        if select_idx is not None and 0 <= select_idx < len(self.rows):
            self._select_row(select_idx, trigger_callback=False)
        elif self.selected_idx is not None and self.selected_idx < len(self.rows):
            self._select_row(self.selected_idx, trigger_callback=False)
        else:
            self.selected_idx = None

    def _select_row(self, idx, trigger_callback=True):
        if not (0 <= idx < len(self.rows)):
            return
        if self.selected_idx is not None and self.selected_idx < len(self.rows):
            old = self.rows[self.selected_idx]
            old['frame'].configure(bg=self.bg)
            old['label'].configure(bg=self.bg)
            old['chk'].configure(bg=self.bg, activebackground=self.bg)

        self.selected_idx = idx
        curr = self.rows[idx]
        curr['frame'].configure(bg=self.select_bg)
        curr['label'].configure(bg=self.select_bg)
        curr['chk'].configure(bg=self.select_bg, activebackground=self.select_bg)

        if trigger_callback and self.on_select:
            self.on_select(idx)

    def _double_click_row(self, idx):
        self._select_row(idx)
        if self.on_double_click:
            self.on_double_click(idx)

    def _on_chk_toggle(self, idx, var):
        val = var.get()
        self.rows[idx]['enabled'] = val
        self.rows[idx]['label'].configure(fg=UITheme.TEXT_MAIN if val else UITheme.TEXT_DISABLED)
        self._select_row(idx, trigger_callback=False)
        if self.on_toggle:
            self.on_toggle(idx, val)

    def curselection(self):
        return (self.selected_idx,) if self.selected_idx is not None else ()

    def selection_set(self, idx):
        self._select_row(idx, trigger_callback=False)

    def selection_clear(self, first=None, last=None):
        if self.selected_idx is not None and self.selected_idx < len(self.rows):
            old = self.rows[self.selected_idx]
            old['frame'].configure(bg=self.bg)
            old['label'].configure(bg=self.bg)
            old['chk'].configure(bg=self.bg, activebackground=self.bg)
        self.selected_idx = None

    def size(self):
        return len(self.rows)

    def see(self, idx):
        if 0 <= idx < len(self.rows):
            self.canvas.update_idletasks()
            rf = self.rows[idx]['frame']
            y1 = rf.winfo_y()
            total_h = self.scrollable_frame.winfo_height()
            if total_h > 0:
                self.canvas.yview_moveto(max(0.0, (y1 - 20) / total_h))

    def delete(self, first, last=None):
        for r in self.rows:
            r['frame'].destroy()
        self.rows.clear()
        self.selected_idx = None

# ==============================================================================
# 原生 Tkinter GUI 主應用程式
# ==============================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("1240x670")
        self.resizable(False, False)
        self.configure(bg=UITheme.BG_DARK)

        self.is_closing = False
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # 頂部全域設定變數
        self.var_profile_name = tk.StringVar()
        self.var_use_bg = tk.BooleanVar(value=True)
        self.var_use_rel = tk.BooleanVar(value=True)
        self.var_topmost = tk.BooleanVar(value=False)
        self.var_offset_x = tk.StringVar(value="0")
        self.var_offset_y = tk.StringVar(value="0")
        self.var_window = tk.StringVar(value="未偵測到視窗")

        # 組合管理變數
        self.var_combo_name = tk.StringVar(value="新組合")
        self.var_combo_act_key = tk.StringVar(value="f1")
        self.var_combo_act_wait = tk.StringVar(value="0.5")
        self.var_combo_to_call = tk.StringVar()
        self.var_combo_btn = tk.StringVar(value="左鍵")
        self.var_combo_manual_x = tk.StringVar(value="0")
        self.var_combo_manual_y = tk.StringVar(value="0")

        # 主流程步驟變數
        self.var_step_key = tk.StringVar(value="f1")
        self.var_step_wait = tk.StringVar(value="1.0")
        self.var_step_btn = tk.StringVar(value="左鍵")
        self.var_step_manual_x = tk.StringVar(value="0")
        self.var_step_manual_y = tk.StringVar(value="0")

        self.active_dlg = None
        self.active_lb = None
        self.var_active_dlg_topmost = tk.BooleanVar(value=True)
        self.active_step_line_map = {}

        self.grid_columnconfigure(0, weight=6)
        self.grid_columnconfigure(1, weight=5)
        self.grid_rowconfigure(0, weight=1)

        self.build_left_panel()
        self.build_right_panel()
        self.refresh_window_dropdown()
        self.refresh_profiles()
        self.track_mouse_live()

    def on_close(self):
        """主視窗關閉事件處理"""
        self.is_closing = True
        global running
        running = False
        stop_event.set()
        emergency_release_all()
        self.destroy()

    def toggle_topmost(self):
        """切換助手視窗置頂狀態"""
        self.attributes("-topmost", self.var_topmost.get())

    def set_status(self, msg):
        """執行緒安全地更新狀態列訊息"""
        if not self.is_closing:
            self.after(0, lambda: self.lbl_status.config(text=f"狀態: {msg}"))

    def set_running_ui(self, is_running):
        """執行緒安全地更新啟動/停止按鈕 UI 與熱更新欄位"""
        def _u():
            if self.is_closing: return
            if is_running:
                self.btn_toggle.config(text="停止執行", bg=UITheme.ACCENT_RED, activebackground=UITheme.ACCENT_RED_HOVER)
                self.f_hot.pack(fill="x", pady=(6, 2))
            else:
                self.btn_toggle.config(text="開始循環執行", bg=UITheme.ACCENT_GREEN, activebackground=UITheme.ACCENT_GREEN_HOVER)
                self.f_hot.pack_forget()
                self.close_active_dlg()
        self.after(0, _u)

    def run_in_test_thread(self, task_name, task_fn):
        """統一的非同步試跑安全守衛與執行緒啟動器"""
        if running:
            return self.set_status("巨集正在循環執行中，請先停止再試跑！")

        def _worker():
            global is_testing
            is_testing = True
            try:
                self.set_status(f"正在試跑 {task_name}...")
                task_fn()
                self.set_status(f"{task_name} 試跑完成！")
            finally:
                is_testing = False

        threading.Thread(target=_worker, daemon=True).start()

    def track_mouse_live(self):
        """實時監控游標坐標並更新 HUD"""
        if self.is_closing:
            return
        try:
            pos = pyautogui.position()
            if IS_WINDOWS and target_hwnd and self.var_use_rel.get():
                pt = POINT(int(pos.x), int(pos.y))
                user32.ScreenToClient(target_hwnd, ctypes.byref(pt))
                self.lbl_mouse_hud.config(text=f"游標實時坐標(相對): ({pt.x}, {pt.y})")
            else:
                self.lbl_mouse_hud.config(text=f"游標實時坐標(螢幕): ({pos.x}, {pos.y})")
        except Exception:
            pass
        self.after(150, self.track_mouse_live)

    def force_bring_window_to_front(self, hwnd):
        """強制喚醒並將目標視窗置頂最前"""
        if not IS_WINDOWS or not hwnd:
            return
        try:
            user32.ShowWindow(hwnd, 9)
            SWP_FLAGS = 0x0001 | 0x0002 | 0x0040
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_FLAGS)
            user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_FLAGS)

            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 2, 0)

            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
        except Exception:
            pass

    def force_bring_self_to_front(self):
        """將連點器主視窗置頂彈回最前"""
        if self.is_closing: return
        self.deiconify()
        self.lift()
        self.focus_force()
        if IS_WINDOWS:
            hwnd_self = user32.FindWindowW(None, WINDOW_TITLE)
            if hwnd_self:
                self.force_bring_window_to_front(hwnd_self)

    def locate_target_window(self):
        """定位並閃爍目標遊戲視窗"""
        global target_hwnd
        if not IS_WINDOWS or not target_hwnd:
            return self.set_status("未綁定有效視窗，無法定位！")

        try:
            self.force_bring_window_to_front(target_hwnd)
            for _ in range(4):
                user32.FlashWindow(target_hwnd, True)
                time.sleep(0.08)
            self.set_status(f"已定位並閃爍視窗 HWND: {target_hwnd}")
        except Exception as e:
            self.set_status(f"定位失敗: {e}")

    # ======================= 取點防重入機制 + 頂部提示 =======================
    def capture_pos_space(self, on_finish, on_cancel=None, btn="left"):
        """無干擾 Hover 取點模式：頂部浮動 HUD，按 Space 確定，按 ESC 取消"""
        global target_hwnd
        val = self.var_window.get()
        if val and val.startswith("["):
            try:
                target_hwnd = int(val.split("]")[0].replace("[", ""))
            except Exception:
                pass

        if not target_hwnd:
            messagebox.showwarning("提示", "尚未綁定目標視窗，請先在上方選擇遊戲視窗！", parent=self)
            if on_cancel: on_cancel()
            return

        btn_cn = "右鍵" if btn == "right" else "左鍵"
        self.force_bring_window_to_front(target_hwnd)
        self.set_status(f"【設定{btn_cn}點擊】遊戲已置頂！請將滑鼠指住目標，按 [SPACE 空白鍵] 確定")

        banner = tk.Toplevel(self)
        banner.overrideredirect(True)
        banner.attributes("-topmost", True)
        banner.configure(bg=UITheme.ACCENT_BLUE)

        sw = self.winfo_screenwidth()
        bw, bh = 760, 44
        bx = max(0, (sw - bw) // 2)
        by = 12
        banner.geometry(f"{bw}x{bh}+{bx}+{by}")

        inner_frame = tk.Frame(banner, bg="#0f172a", padx=10, pady=4)
        inner_frame.pack(fill="both", expand=True, padx=2, pady=2)

        lbl_hud = tk.Label(
            inner_frame,
            text=f"【設定{btn_cn}點擊】將滑鼠指住目標 ➜ 按 [SPACE 空白鍵] 確定！(按 ESC 取消)",
            bg="#0f172a",
            fg=UITheme.CYAN_TITLE,
            font=("Segoe UI", 10, "bold")
        )
        lbl_hud.pack(fill="both", expand=True)

        if IS_WINDOWS:
            user32.GetAsyncKeyState(0x20)
            user32.GetAsyncKeyState(0x1B)

        is_handled = [False]

        def poll_keys():
            if not banner.winfo_exists() or is_handled[0]:
                return

            pos = pyautogui.position()
            if IS_WINDOWS and target_hwnd and self.var_use_rel.get():
                pt = POINT(int(pos.x), int(pos.y))
                user32.ScreenToClient(target_hwnd, ctypes.byref(pt))
                coord_desc = f"({pt.x}, {pt.y})"
                rx, ry, rel = pt.x, pt.y, True
            else:
                coord_desc = f"({pos.x}, {pos.y})"
                rx, ry, rel = pos.x, pos.y, False

            lbl_hud.config(text=f"【設定{btn_cn}點擊】滑鼠指住目標 ➜ 按 [SPACE 空白鍵] 確定！(坐標: {coord_desc} | ESC 取消)")

            if IS_WINDOWS:
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

    # ======================= 彈窗內部高亮與熱更新邏輯 =======================
    def toggle_active_dlg_topmost(self):
        """切換掛機進度監控視窗的置頂狀態"""
        if self.active_dlg and self.active_dlg.winfo_exists():
            self.active_dlg.attributes("-topmost", self.var_active_dlg_topmost.get())

    def highlight_active_step(self, idx, sub_idx=None):
        """在掛機進度監控彈窗中高亮當前執行中的步驟或 Combo 子步驟"""
        def _hl():
            if self.active_lb and self.active_dlg and self.active_dlg.winfo_exists():
                line = self.active_step_line_map.get((idx, sub_idx))
                if line is None and sub_idx is not None:
                    line = self.active_step_line_map.get((idx, None))
                if line is None and sub_idx is None:
                    line = idx
                if line is not None and 0 <= line < self.active_lb.size():
                    self.active_lb.selection_clear(0, tk.END)
                    self.active_lb.selection_set(line)
                    self.active_lb.see(line)
        self.after(0, _hl)

    def refresh_active_dlg_items(self):
        """刷新進度監控彈窗的執行實例清單（支援展開 Combo 內部子動作）"""
        if not self.active_lb or not self.active_dlg or not self.active_dlg.winfo_exists():
            return
        self.active_lb.delete(0, tk.END)
        self.active_step_line_map.clear()
        line_idx = 0

        with steps_lock:
            for i, s in enumerate(active_steps):
                self.active_step_line_map[(i, None)] = line_idx
                text = format_action_summary(s, index=i, with_checkbox_tag=True)
                self.active_lb.insert(tk.END, text)
                line_idx += 1

                if s.get("type") == "combo":
                    for a_idx, sub_act in enumerate(s.get("actions", [])):
                        self.active_step_line_map[(i, a_idx)] = line_idx
                        sub_text = f"   ↳ {format_action_summary(sub_act, index=a_idx, with_checkbox_tag=True)}"
                        self.active_lb.insert(tk.END, sub_text)
                        line_idx += 1

    def update_active_dlg_geometry(self, reset_position=False):
        """根據清單內容行數動態設定/調整監控視窗尺寸，並居中或保留位置"""
        if not self.active_dlg or not self.active_dlg.winfo_exists() or not self.active_lb:
            return

        total_lines = self.active_lb.size()
        # 頂部標題列與按鈕區約 120px，每行清單約佔 22px
        target_h = max(240, min(650, 120 + total_lines * 22))
        target_w = 460

        self.update_idletasks()

        if reset_position:
            parent_x = self.winfo_x()
            parent_y = self.winfo_y()
            parent_w = self.winfo_width()
            parent_h = self.winfo_height()
            pos_x = parent_x + max(0, (parent_w - target_w) // 2)
            pos_y = parent_y + max(0, (parent_h - target_h) // 2)
            self.active_dlg.geometry(f"{target_w}x{target_h}+{pos_x}+{pos_y}")
        else:
            cur_x = self.active_dlg.winfo_x()
            cur_y = self.active_dlg.winfo_y()
            self.active_dlg.geometry(f"{target_w}x{target_h}+{cur_x}+{cur_y}")

        self.active_dlg.minsize(380, 220)

    def apply_hot_reload_from_popup(self):
        """即時套用修改 (Hot-Reload)：在運行中即時同步草稿到背景運行實例"""
        global active_steps, active_combos, reload_requested
        if not running:
            return self.set_status("巨集尚未執行，儲存設定即可生效")
        if not steps:
            return self.set_status("步驟清單是空的，無法套用")

        with steps_lock:
            active_steps = copy.deepcopy(steps)
            active_combos = copy.deepcopy(combos)
            reload_requested = True

        self.refresh_active_dlg_items()
        self.update_active_dlg_geometry(reset_position=False)
        self.set_status("已套用最新清單！背景將於當前動作結束後自動切換")

    def close_active_dlg(self):
        """關閉進度監控彈窗並清理狀態"""
        if self.active_dlg and self.active_dlg.winfo_exists():
            self.active_dlg.destroy()
        self.active_dlg = None
        self.active_lb = None
        self.active_step_line_map.clear()

    def view_active_steps(self):
        """開啟或聚焦掛機進度監控彈窗"""
        if not running:
            return

        if self.active_dlg and self.active_dlg.winfo_exists():
            self.active_dlg.deiconify()
            self.active_dlg.lift()
            self.refresh_active_dlg_items()
            self.update_active_dlg_geometry(reset_position=False)
            return

        self.active_dlg = tk.Toplevel(self)
        self.active_dlg.withdraw()  # 先隱藏，避免初次計算尺寸時閃爍
        self.active_dlg.title("當前掛機進度監控")
        self.active_dlg.configure(bg=UITheme.BG_PANEL)
        self.active_dlg.attributes("-topmost", self.var_active_dlg_topmost.get())
        self.active_dlg.transient(self)
        self.active_dlg.resizable(True, True)
        self.active_dlg.protocol("WM_DELETE_WINDOW", self.close_active_dlg)

        # 頂部標題列與置頂 Checkbox
        f_top = tk.Frame(self.active_dlg, bg=UITheme.BG_PANEL)
        f_top.pack(fill="x", padx=10, pady=(8, 4))

        tk.Label(
            f_top,
            text="⚡ 當前掛機進度監控",
            bg=UITheme.BG_PANEL,
            fg=UITheme.CYAN_TITLE,
            font=("Segoe UI", 10, "bold")
        ).pack(side="left")

        chk_top = tk.Checkbutton(
            f_top,
            text="視窗置頂",
            variable=self.var_active_dlg_topmost,
            bg=UITheme.BG_PANEL,
            fg=UITheme.TEXT_MAIN,
            selectcolor=UITheme.BG_DARK,
            activebackground=UITheme.BG_PANEL,
            activeforeground=UITheme.TEXT_MAIN,
            font=("Segoe UI", 9),
            command=self.toggle_active_dlg_topmost
        )
        chk_top.pack(side="right")

        f_box = tk.Frame(self.active_dlg, bg=UITheme.BG_DARK)
        f_box.pack(fill="both", expand=True, padx=10, pady=4)

        self.active_lb = tk.Listbox(
            f_box,
            bg=UITheme.BG_DARK,
            fg=UITheme.TEXT_MAIN,
            selectbackground=UITheme.ACCENT_BLUE,
            selectforeground="#fff",
            bd=0,
            highlightthickness=0,
            font=("Segoe UI", 9)
        )
        self.active_lb.pack(side="left", fill="both", expand=True)

        sc = tk.Scrollbar(f_box, orient="vertical", command=self.active_lb.yview)
        sc.pack(side="right", fill="y")
        self.active_lb.config(yscrollcommand=sc.set)

        self.refresh_active_dlg_items()

        f_ctrl = tk.Frame(self.active_dlg, bg=UITheme.BG_PANEL)
        f_ctrl.pack(fill="x", padx=10, pady=(6, 8))

        tk.Button(
            f_ctrl,
            text="即時套用修改（不用重開）",
            bg=UITheme.ACCENT_BLUE,
            fg="#ffffff",
            font=("Segoe UI", 9, "bold"),
            activebackground=UITheme.ACCENT_BLUE_HOVER,
            command=self.apply_hot_reload_from_popup
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        tk.Button(
            f_ctrl,
            text="關閉視窗",
            width=8,
            bg=UITheme.BTN_GRAY,
            fg="#fff",
            activebackground=UITheme.BTN_GRAY_HOVER,
            command=self.close_active_dlg
        ).pack(side="right")

        self.update_active_dlg_geometry(reset_position=True)
        self.active_dlg.deiconify()

    # ======================= 全功能動作編輯彈窗 =======================
    def prompt_edit_action(self, action, available_combos=None):
        """彈出針對各動作型別的編輯對話框"""
        atype = action.get("type")
        if not atype: return False

        dialog = tk.Toplevel(self)
        dialog.configure(bg=UITheme.BG_PANEL)
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.transient(self)
        dialog.grab_set()

        w, h = 330, 225
        self.update_idletasks()
        pos_x = self.winfo_x() + max(0, (self.winfo_width() - w) // 2)
        pos_y = self.winfo_y() + max(0, (self.winfo_height() - h) // 2)
        dialog.geometry(f"{w}x{h}+{pos_x}+{pos_y}")

        modified = [False]
        f = tk.Frame(dialog, bg=UITheme.BG_PANEL, pady=10)
        f.pack()

        if atype == "click":
            dialog.title("修改點擊動作")
            var_x = tk.StringVar(value=str(action.get("x", 0)))
            var_y = tk.StringVar(value=str(action.get("y", 0)))
            curr_btn = "右鍵" if action.get("btn") == "right" else "左鍵"
            var_btn = tk.StringVar(value=curr_btn)

            tk.Label(f, text="按鍵類型:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=0, column=0, padx=6, pady=3, sticky="e")
            cbo_btn = ttk.Combobox(f, textvariable=var_btn, values=["左鍵", "右鍵"], width=8, state="readonly")
            cbo_btn.grid(row=0, column=1, padx=6, pady=3, sticky="w")

            tk.Label(f, text="X 坐標:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=1, column=0, padx=6, pady=3, sticky="e")
            e_x = tk.Entry(f, textvariable=var_x, width=10, bg=UITheme.BG_INPUT, fg="#fff")
            e_x.grid(row=1, column=1, padx=6, pady=3, sticky="w")

            tk.Label(f, text="Y 坐標:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=2, column=0, padx=6, pady=3, sticky="e")
            e_y = tk.Entry(f, textvariable=var_y, width=10, bg=UITheme.BG_INPUT, fg="#fff")
            e_y.grid(row=2, column=1, padx=6, pady=3, sticky="w")

            btn_rec = tk.Button(f, text="重新瞄準目標 (按 Space 確定)", width=24, bg=UITheme.ACCENT_GREEN, fg="#fff", activebackground=UITheme.ACCENT_GREEN_HOVER, font=("Segoe UI", 9, "bold"))
            btn_rec.grid(row=3, column=0, columnspan=2, pady=(8, 2))

            def do_rec():
                dialog.grab_release()
                dialog.withdraw()

                def on_finish_space(rx, ry, rel):
                    dialog.deiconify()
                    dialog.lift()
                    dialog.focus_force()
                    dialog.grab_set()
                    var_x.set(str(rx))
                    var_y.set(str(ry))
                    self.set_status(f"已更新點擊位置: ({rx}, {ry})")

                def on_cancel_space():
                    dialog.deiconify()
                    dialog.lift()
                    dialog.focus_force()
                    dialog.grab_set()

                target_btn = "right" if var_btn.get() == "右鍵" else "left"
                self.capture_pos_space(on_finish_space, on_cancel_space, btn=target_btn)

            btn_rec.config(command=do_rec)
            e_x.focus_set()

            def on_ok():
                try:
                    action["x"] = int(var_x.get().strip())
                    action["y"] = int(var_y.get().strip())
                    action["btn"] = "right" if var_btn.get() == "右鍵" else "left"
                    modified[0] = True
                    dialog.destroy()
                except ValueError:
                    messagebox.showerror("錯誤", "X 和 Y 必須輸入整數！", parent=dialog)

        elif atype == "key":
            dialog.title("修改按鍵")
            var_k = tk.StringVar(value=str(action.get("key", "f1")))
            tk.Label(f, text="按鍵名稱:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=0, column=0, padx=6, pady=10, sticky="e")
            e_k = tk.Entry(f, textvariable=var_k, width=12, bg=UITheme.BG_INPUT, fg="#fff")
            e_k.grid(row=0, column=1, padx=6, pady=10)
            e_k.focus_set()

            def on_ok():
                k = var_k.get().strip().lower()
                if not k:
                    messagebox.showerror("錯誤", "按鍵名稱不可為空！", parent=dialog)
                    return
                action["key"] = k
                modified[0] = True
                dialog.destroy()

        elif atype == "wait":
            dialog.title("修改停頓時間")
            var_w = tk.StringVar(value=str(action.get("sec", 1.0)))
            tk.Label(f, text="等待秒數:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=0, column=0, padx=6, pady=10, sticky="e")
            e_w = tk.Entry(f, textvariable=var_w, width=10, bg=UITheme.BG_INPUT, fg="#fff")
            e_w.grid(row=0, column=1, padx=6, pady=10)
            e_w.focus_set()

            def on_ok():
                try:
                    sec = float(var_w.get().strip())
                    if sec <= 0: raise ValueError
                    action["sec"] = sec
                    modified[0] = True
                    dialog.destroy()
                except ValueError:
                    messagebox.showerror("錯誤", "停頓時間必須輸入大於 0 的數字！", parent=dialog)

        elif atype == "call_combo":
            dialog.title("修改呼叫目標組合")
            curr_tgt = action.get("target_name", "")
            var_c = tk.StringVar(value=curr_tgt)
            combos_list = available_combos or [c["name"] for c in combos]
            tk.Label(f, text="目標組合:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=0, column=0, padx=6, pady=10, sticky="e")
            cbo = ttk.Combobox(f, textvariable=var_c, values=combos_list, width=14, state="readonly")
            cbo.grid(row=0, column=1, padx=6, pady=10)
            if curr_tgt in combos_list: cbo.set(curr_tgt)
            elif combos_list: cbo.current(0)

            def on_ok():
                tgt = var_c.get().strip()
                if not tgt:
                    messagebox.showerror("錯誤", "請先選擇有效的組合名稱！", parent=dialog)
                    return
                action["target_name"] = tgt
                modified[0] = True
                dialog.destroy()

        elif atype == "combo":
            dialog.title("切換執行組合")
            curr_c = action.get("name", "")
            var_mc = tk.StringVar(value=curr_c)
            combos_list = [c["name"] for c in combos]
            tk.Label(f, text="切換組合:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=0, column=0, padx=6, pady=10, sticky="e")
            cbo = ttk.Combobox(f, textvariable=var_mc, values=combos_list, width=14, state="readonly")
            cbo.grid(row=0, column=1, padx=6, pady=10)
            if curr_c in combos_list: cbo.set(curr_c)
            elif combos_list: cbo.current(0)

            def on_ok():
                chosen = var_mc.get().strip()
                match = next((c for c in combos if c["name"] == chosen), None)
                if match:
                    action["name"] = match["name"]
                    action["actions"] = copy.deepcopy(match.get("actions", []))
                    modified[0] = True
                dialog.destroy()

        bf = tk.Frame(dialog, bg=UITheme.BG_PANEL)
        bf.pack(pady=4)
        tk.Button(bf, text="確定", width=8, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, command=on_ok).pack(side="left", padx=5)
        tk.Button(bf, text="取消", width=8, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, command=dialog.destroy).pack(side="left", padx=5)

        dialog.bind("<Return>", lambda e: on_ok())
        dialog.bind("<Escape>", lambda e: dialog.destroy())

        self.wait_window(dialog)
        return modified[0]

    # ======================= 左欄佈局 =======================
    def build_left_panel(self):
        f_left = tk.Frame(self, bg=UITheme.BG_PANEL, padx=8, pady=8, highlightbackground=UITheme.BORDER, highlightthickness=1)
        f_left.grid(row=0, column=0, padx=(10, 5), pady=10, sticky="nsew")

        # 1. 設定與視窗綁定
        f_cfg = tk.LabelFrame(f_left, text=" 設定與視窗綁定 ", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=("Segoe UI", 10, "bold"), padx=6, pady=6)
        f_cfg.pack(fill="x", pady=(0, 6))

        r1 = tk.Frame(f_cfg, bg=UITheme.BG_PANEL)
        r1.pack(fill="x", pady=2)
        tk.Label(r1, text="設定檔:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).pack(side="left")
        self.cbo_profile = ttk.Combobox(r1, textvariable=self.var_profile_name, width=18, state="readonly")
        self.cbo_profile.pack(side="left", padx=4)
        tk.Button(r1, text="載入", width=5, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, command=self.load_config).pack(side="left", padx=2)
        tk.Button(r1, text="儲存", width=5, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, command=self.save_config).pack(side="left", padx=2)
        tk.Button(r1, text="新建", width=5, bg=UITheme.ACCENT_GREEN, fg="#fff", activebackground=UITheme.ACCENT_GREEN_HOVER, command=self.create_new_profile).pack(side="left", padx=2)

        r2 = tk.Frame(f_cfg, bg=UITheme.BG_PANEL)
        r2.pack(fill="x", pady=4)
        tk.Checkbutton(r2, text="背景掛機", variable=self.var_use_bg, bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, selectcolor=UITheme.BG_PANEL, activebackground=UITheme.BG_PANEL).pack(side="left")
        tk.Checkbutton(r2, text="相對坐標", variable=self.var_use_rel, bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, selectcolor=UITheme.BG_PANEL, activebackground=UITheme.BG_PANEL).pack(side="left", padx=4)
        tk.Checkbutton(r2, text="視窗置頂", variable=self.var_topmost, command=self.toggle_topmost, bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, selectcolor=UITheme.BG_PANEL, activebackground=UITheme.BG_PANEL).pack(side="left", padx=4)

        r2_sub = tk.Frame(f_cfg, bg=UITheme.BG_PANEL)
        r2_sub.pack(fill="x", pady=2)
        tk.Label(r2_sub, text="點擊偏差校正 (X/Y):", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).pack(side="left")
        tk.Label(r2_sub, text="X:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED).pack(side="left", padx=(4, 1))
        tk.Entry(r2_sub, textvariable=self.var_offset_x, width=4, bg=UITheme.BG_INPUT, fg="#ffffff").pack(side="left", padx=1)
        tk.Label(r2_sub, text="Y:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED).pack(side="left", padx=(4, 1))
        tk.Entry(r2_sub, textvariable=self.var_offset_y, width=4, bg=UITheme.BG_INPUT, fg="#ffffff").pack(side="left", padx=1)

        r3 = tk.Frame(f_cfg, bg=UITheme.BG_PANEL)
        r3.pack(fill="x", pady=2)
        tk.Label(r3, text="目標視窗:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).pack(side="left")
        self.cbo_window = ttk.Combobox(r3, textvariable=self.var_window, width=28, state="readonly")
        self.cbo_window.pack(side="left", padx=4)
        self.cbo_window.bind("<<ComboboxSelected>>", self.on_window_select)
        tk.Button(r3, text="重新整理", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, command=self.refresh_window_dropdown).pack(side="left", padx=2)
        tk.Button(r3, text="定位視窗", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, command=self.locate_target_window).pack(side="left", padx=2)

        # 2. 技能組合區塊
        f_combo = tk.LabelFrame(f_left, text=" 技能組合庫 (右側真實 Checkbox: 啟用/停用 | 雙擊: 加入掛機流程) ", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=("Segoe UI", 10, "bold"), padx=6, pady=6)
        f_combo.pack(fill="both", expand=True)

        f_combo_split = tk.Frame(f_combo, bg=UITheme.BG_PANEL)
        f_combo_split.pack(fill="both", expand=True)
        f_combo_split.grid_columnconfigure(0, weight=4)
        f_combo_split.grid_columnconfigure(1, weight=6)
        f_combo_split.grid_rowconfigure(0, weight=1)

        # 2-A. 組合清單 (支援雙擊加入掛機流程)
        f_cl = tk.Frame(f_combo_split, bg=UITheme.BG_PANEL, padx=4, pady=2)
        f_cl.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        tk.Label(f_cl, text="【組合清單 (雙擊加入)】", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=("Segoe UI", 9, "bold")).pack(anchor="w")

        cr_name = tk.Frame(f_cl, bg=UITheme.BG_PANEL)
        cr_name.pack(fill="x", pady=2)
        tk.Entry(cr_name, textvariable=self.var_combo_name, width=10, bg=UITheme.BG_INPUT, fg="#fff").pack(side="left", fill="x", expand=True, padx=(0, 2))
        tk.Button(cr_name, text="新增", width=4, bg=UITheme.ACCENT_GREEN, fg="#fff", activebackground=UITheme.ACCENT_GREEN_HOVER, command=self.add_new_combo).pack(side="left", padx=1)
        tk.Button(cr_name, text="改名", width=4, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, command=self.rename_selected_combo).pack(side="left", padx=1)
        tk.Button(cr_name, text="複製", width=4, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, command=self.duplicate_selected_combo).pack(side="left", padx=1)

        f_cl_box = tk.Frame(f_cl, bg=UITheme.BG_DARK)
        f_cl_box.pack(fill="both", expand=True, pady=4)
        self.combo_listbox = tk.Listbox(f_cl_box, bg=UITheme.BG_DARK, fg=UITheme.TEXT_MAIN, selectbackground=UITheme.ACCENT_BLUE, selectforeground="#fff", bd=0, highlightthickness=0, font=("Segoe UI", 10), exportselection=False)
        self.combo_listbox.pack(side="left", fill="both", expand=True)
        self.combo_listbox.bind("<<ListboxSelect>>", self.on_combo_select)
        self.combo_listbox.bind("<Double-Button-1>", self.on_combo_double_click_add) # 雙擊加入掛機流程
        sc_cl = tk.Scrollbar(f_cl_box, orient="vertical", command=self.combo_listbox.yview)
        sc_cl.pack(side="right", fill="y")
        self.combo_listbox.config(yscrollcommand=sc_cl.set)

        cr_act = tk.Frame(f_cl, bg=UITheme.BG_PANEL)
        cr_act.pack(fill="x", pady=(2, 0))
        tk.Button(cr_act, text="加入掛機流程 ->", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, font=("Segoe UI", 9, "bold"), command=self.add_combo_to_main_steps).pack(side="left", fill="x", expand=True, padx=(0, 2))
        tk.Button(cr_act, text="刪除組合", width=8, bg=UITheme.ACCENT_RED, fg="#fff", activebackground=UITheme.ACCENT_RED_HOVER, command=self.delete_selected_combo).pack(side="right")

        # 2-B. 組合動作 (視覺層次優化：卡片式分組 + 雙層寬鬆工具列)
        f_cr = tk.Frame(f_combo_split, bg=UITheme.BG_PANEL, padx=6, pady=3, highlightbackground=UITheme.BORDER, highlightthickness=1)
        f_cr.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        f_cr_top = tk.Frame(f_cr, bg=UITheme.BG_PANEL)
        f_cr_top.pack(fill="x", pady=(0, 4))
        self.lbl_combo_editing = tk.Label(f_cr_top, text="【組合動作: 未選取】", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_SUB, font=("Segoe UI", 9, "bold"))
        self.lbl_combo_editing.pack(side="left")
        tk.Button(f_cr_top, text="▶ 試跑組合", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, font=("Segoe UI", 8, "bold"), relief="flat", padx=6, command=self.test_run_current_combo).pack(side="right")

        # 動作建立面板 (卡片分組)
        f_action_card = tk.LabelFrame(f_cr, text=" 加入動作到所選組合 ", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=("Segoe UI", 8, "bold"), padx=5, pady=3)
        f_action_card.pack(fill="x", pady=(0, 4))

        # 1. 點擊動作行 (突出主要瞄準點擊)
        r_click = tk.Frame(f_action_card, bg=UITheme.BG_PANEL)
        r_click.pack(fill="x", pady=2)
        ttk.Combobox(r_click, textvariable=self.var_combo_btn, values=["左鍵", "右鍵"], width=4, state="readonly").pack(side="left", padx=(0, 3))
        self.btn_combo_add_click = tk.Button(r_click, text="瞄準點擊", bg=UITheme.ACCENT_GREEN, fg="#fff", font=("Segoe UI", 9, "bold"), activebackground=UITheme.ACCENT_GREEN_HOVER, relief="flat", padx=6, command=self.combo_add_click_action)
        self.btn_combo_add_click.pack(side="left", padx=1, fill="x", expand=True)

        tk.Label(r_click, text="X:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=("Segoe UI", 8)).pack(side="left", padx=(3, 1))
        tk.Entry(r_click, textvariable=self.var_combo_manual_x, width=4, bg=UITheme.BG_INPUT, fg="#fff", relief="flat").pack(side="left", padx=1)
        tk.Label(r_click, text="Y:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=("Segoe UI", 8)).pack(side="left", padx=(1, 1))
        tk.Entry(r_click, textvariable=self.var_combo_manual_y, width=4, bg=UITheme.BG_INPUT, fg="#fff", relief="flat").pack(side="left", padx=1)
        tk.Button(r_click, text="+手動", width=4, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", command=self.combo_add_manual_click).pack(side="left", padx=(2, 0))

        # 2. 按鍵與等待行 (等寬對齊)
        r_fast = tk.Frame(f_action_card, bg=UITheme.BG_PANEL)
        r_fast.pack(fill="x", pady=2)

        f_k = tk.Frame(r_fast, bg=UITheme.BG_PANEL)
        f_k.pack(side="left", fill="x", expand=True, padx=(0, 2))
        tk.Entry(f_k, textvariable=self.var_combo_act_key, width=5, bg=UITheme.BG_INPUT, fg="#fff", relief="flat").pack(side="left", padx=(0, 2))
        tk.Button(f_k, text="+加按鍵", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", padx=4, command=self.combo_add_key_action).pack(side="left", fill="x", expand=True)

        f_w = tk.Frame(r_fast, bg=UITheme.BG_PANEL)
        f_w.pack(side="left", fill="x", expand=True, padx=(2, 0))
        tk.Entry(f_w, textvariable=self.var_combo_act_wait, width=4, bg=UITheme.BG_INPUT, fg="#fff", relief="flat").pack(side="left", padx=(0, 2))
        tk.Button(f_w, text="+加停頓(s)", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", padx=4, command=self.combo_add_wait_action).pack(side="left", fill="x", expand=True)

        # 3. 呼叫組合行
        r_call = tk.Frame(f_action_card, bg=UITheme.BG_PANEL)
        r_call.pack(fill="x", pady=2)
        tk.Label(r_call, text="呼叫組合:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=("Segoe UI", 8)).pack(side="left", padx=(0, 2))
        self.cbo_call_combo = ttk.Combobox(r_call, textvariable=self.var_combo_to_call, width=12, state="readonly")
        self.cbo_call_combo.pack(side="left", padx=2, fill="x", expand=True)
        tk.Button(r_call, text="+呼叫", width=6, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=("Segoe UI", 8, "bold"), command=self.combo_add_call_action).pack(side="left", padx=(2, 0))

        # 動作清單
        f_cr_box = tk.Frame(f_cr, bg=UITheme.BG_DARK)
        f_cr_box.pack(fill="both", expand=True, pady=3)

        self.combo_act_listbox = CheckList(
            f_cr_box,
            bg=UITheme.BG_DARK,
            select_bg=UITheme.ACCENT_BLUE,
            on_double_click=lambda idx: self.edit_selected_combo_action(),
            on_toggle=self.on_combo_action_chk_toggle
        )
        self.combo_act_listbox.pack(fill="both", expand=True)

        # 底部雙層管理工具列 (避免按鈕擠在同一行造成文字裁切)
        cr_act_ctrl1 = tk.Frame(f_cr, bg=UITheme.BG_PANEL)
        cr_act_ctrl1.pack(fill="x", pady=(2, 1))
        tk.Button(cr_act_ctrl1, text="上移", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", command=lambda: self.move_combo_action(-1)).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(cr_act_ctrl1, text="下移", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", command=lambda: self.move_combo_action(1)).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(cr_act_ctrl1, text="修改動作", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", command=self.edit_selected_combo_action).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(cr_act_ctrl1, text="▶ 試跑動作", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, relief="flat", font=("Segoe UI", 8, "bold"), command=self.test_run_selected_combo_action).pack(side="left", padx=1, fill="x", expand=True)

        cr_act_ctrl2 = tk.Frame(f_cr, bg=UITheme.BG_PANEL)
        cr_act_ctrl2.pack(fill="x", pady=(1, 1))
        tk.Button(cr_act_ctrl2, text="複製動作", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", command=self.duplicate_combo_action).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(cr_act_ctrl2, text="刪除動作", bg=UITheme.ACCENT_RED, fg="#fff", activebackground=UITheme.ACCENT_RED_HOVER, relief="flat", command=self.delete_combo_action).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(cr_act_ctrl2, text="清空動作", bg=UITheme.ACCENT_RED_DARK, fg="#fff", activebackground=UITheme.ACCENT_RED_DARK_HOVER, relief="flat", command=self.clear_combo_actions).pack(side="left", padx=1, fill="x", expand=True)

    # ======================= 右欄佈局 =======================
    def build_right_panel(self):
        f_right = tk.Frame(self, bg=UITheme.BG_PANEL, padx=8, pady=8, highlightbackground=UITheme.BORDER, highlightthickness=1)
        f_right.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="nsew")

        # 1. 單一動作新增
        f_step = tk.LabelFrame(f_right, text=" 單一動作（單次點擊 / 單鍵） ", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=("Segoe UI", 10, "bold"), padx=6, pady=6)
        f_step.pack(fill="x", pady=(0, 6))

        sr_click = tk.Frame(f_step, bg=UITheme.BG_PANEL)
        sr_click.pack(fill="x", pady=2)
        ttk.Combobox(sr_click, textvariable=self.var_step_btn, values=["左鍵", "右鍵"], width=4, state="readonly").pack(side="left", padx=(0, 2))
        self.btn_step_click = tk.Button(sr_click, text="瞄準目標新增點擊", width=16, bg=UITheme.ACCENT_GREEN, fg="#fff", font=("Segoe UI", 9, "bold"), activebackground=UITheme.ACCENT_GREEN_HOVER, command=self.add_main_click_step)
        self.btn_step_click.pack(side="left", padx=2)
        tk.Label(sr_click, text="手動X:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=("Segoe UI", 8)).pack(side="left", padx=(4, 1))
        tk.Entry(sr_click, textvariable=self.var_step_manual_x, width=4, bg=UITheme.BG_INPUT, fg="#fff").pack(side="left", padx=1)
        tk.Label(sr_click, text="Y:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=("Segoe UI", 8)).pack(side="left", padx=1)
        tk.Entry(sr_click, textvariable=self.var_step_manual_y, width=4, bg=UITheme.BG_INPUT, fg="#fff").pack(side="left", padx=1)
        tk.Button(sr_click, text="+手動", width=5, bg=UITheme.ACCENT_GREEN, fg="#fff", activebackground=UITheme.ACCENT_GREEN_HOVER, command=self.add_main_manual_click).pack(side="left", padx=2)

        sr = tk.Frame(f_step, bg=UITheme.BG_PANEL)
        sr.pack(fill="x", pady=2)
        tk.Label(sr, text="按鍵:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).pack(side="left")
        tk.Entry(sr, textvariable=self.var_step_key, width=5, bg=UITheme.BG_INPUT, fg="#fff").pack(side="left", padx=3)
        tk.Button(sr, text="加按鍵", width=7, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, command=self.add_main_key_step).pack(side="left", padx=2)

        tk.Label(sr, text="停頓:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).pack(side="left", padx=(8, 0))
        tk.Entry(sr, textvariable=self.var_step_wait, width=4, bg=UITheme.BG_INPUT, fg="#fff").pack(side="left", padx=3)
        tk.Button(sr, text="加停頓", width=7, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, command=self.add_main_wait_step).pack(side="left", padx=2)

        # 2. 自動循環清單（掛機流程）
        f_seq = tk.LabelFrame(f_right, text=" 自動循環清單（掛機流程） ", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=("Segoe UI", 10, "bold"), padx=6, pady=6)
        f_seq.pack(fill="both", expand=True)

        f_list_s = tk.Frame(f_seq, bg=UITheme.BG_DARK)
        f_list_s.pack(fill="both", expand=True, pady=4)

        self.step_listbox = CheckList(
            f_list_s,
            bg=UITheme.BG_DARK,
            select_bg=UITheme.ACCENT_BLUE,
            on_double_click=lambda idx: self.edit_selected_main_step(),
            on_toggle=self.on_main_step_chk_toggle
        )
        self.step_listbox.pack(fill="both", expand=True)

        sr2 = tk.Frame(f_seq, bg=UITheme.BG_PANEL)
        sr2.pack(fill="x", pady=(2, 0))
        tk.Button(sr2, text="上移", width=5, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, command=lambda: self.move_main_step(-1)).pack(side="left", padx=1)
        tk.Button(sr2, text="下移", width=5, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, command=lambda: self.move_main_step(1)).pack(side="left", padx=1)
        tk.Button(sr2, text="▶ 試跑單步", width=8, bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, command=self.test_run_selected_main_step).pack(side="left", padx=1)
        tk.Button(sr2, text="複製", width=4, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, command=self.duplicate_main_step).pack(side="left", padx=1)
        tk.Button(sr2, text="修改動作", width=8, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, command=self.edit_selected_main_step).pack(side="left", padx=1)
        tk.Button(sr2, text="刪除", width=5, bg=UITheme.ACCENT_RED, fg="#fff", activebackground=UITheme.ACCENT_RED_HOVER, command=self.delete_main_step).pack(side="left", padx=1)
        tk.Button(sr2, text="清空", width=5, bg=UITheme.ACCENT_RED, fg="#fff", activebackground=UITheme.ACCENT_RED_HOVER, command=self.clear_main_steps).pack(side="right", padx=1)

        # 檢視彈窗啟動列
        self.f_hot = tk.Frame(f_right, bg=UITheme.BG_PANEL)
        self.btn_view_active = tk.Button(
            self.f_hot,
            text="檢視當前掛機進度監控",
            bg=UITheme.ACCENT_BLUE,
            fg="#ffffff",
            font=("Segoe UI", 9, "bold"),
            activebackground=UITheme.ACCENT_BLUE_HOVER,
            command=self.view_active_steps
        )
        self.btn_view_active.pack(fill="x", padx=2)

        # 3. HUD 與主開關
        bot = tk.Frame(f_right, bg=UITheme.BG_PANEL)
        bot.pack(fill="x", pady=(2, 0))

        self.lbl_mouse_hud = tk.Label(bot, text="游標實時坐標: (0, 0)", anchor="w", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=("Segoe UI", 9, "bold"))
        self.lbl_mouse_hud.pack(fill="x")

        self.lbl_status = tk.Label(bot, text="狀態: 已就緒", anchor="w", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MAIN, font=("Segoe UI", 9))
        self.lbl_status.pack(fill="x", pady=(0, 3))
        self.btn_toggle = tk.Button(bot, text="開始循環執行", height=2, bg=UITheme.ACCENT_GREEN, fg="#ffffff", font=("Segoe UI", 11, "bold"), activebackground=UITheme.ACCENT_GREEN_HOVER, command=self.toggle_run)
        self.btn_toggle.pack(fill="x")

    def on_combo_double_click_add(self, event):
        """雙擊組合清單時直接加入掛機流程"""
        sel = self.combo_listbox.curselection()
        if not sel: return
        idx = sel[0]
        if not (0 <= idx < len(combos)): return
        c = combos[idx]
        if not c.get("actions"):
            return self.set_status(f"組合 [{c['name']}] 內尚未加入任何動作！")

        ins = self.get_main_insert_index()
        steps.insert(ins, {"type": "combo", "name": c["name"], "actions": copy.deepcopy(c["actions"]), "enabled": True})
        self.update_step_list(select_idx=ins)
        self.set_status(f"已透過雙擊將組合 [{c['name']}] 加入掛機流程 #{ins+1}")

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
                        json.dump({"combos": [], "steps": []}, f)
                except Exception: pass

        self.cbo_profile["values"] = profiles
        if select_name and select_name in profiles:
            self.cbo_profile.set(select_name)
        elif self.var_profile_name.get() in profiles:
            self.cbo_profile.set(self.var_profile_name.get())
        else:
            self.cbo_profile.current(0)

    def create_new_profile(self):
        name = simpledialog.askstring("新建設定檔", "請輸入新設定檔名稱 (毋須輸入副檔名):", parent=self)
        if not name or not name.strip(): return
        name = name.strip()
        fn = f"{name}{CONFIG_EXT}"
        if os.path.exists(fn):
            if not messagebox.askyesno("檔案覆蓋確認", f"設定檔「{name}」已存在！\n請問是否確認覆蓋原有設定？", parent=self):
                return
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump({"combos": combos, "steps": steps}, f, ensure_ascii=False, indent=2)
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
                json.dump({"combos": combos, "steps": steps}, f, ensure_ascii=False, indent=2)
            self.set_status(f"已成功儲存至 {fn}")
            self.refresh_profiles(select_name=name)
        except Exception as e:
            self.set_status(f"儲存失敗: {e}")

    def load_config(self):
        name = self.var_profile_name.get().strip()
        if not name: return
        fn = f"{name}{CONFIG_EXT}"
        if not os.path.exists(fn): return self.set_status(f"找不到檔案：{fn}")
        try:
            with open(fn, "r", encoding="utf-8") as f:
                data = json.load(f)

            for c in data.get("combos", []):
                for act in c.get("actions", []):
                    if act.get("type") == "click" and "btn" not in act:
                        act["btn"] = "left"
            for s in data.get("steps", []):
                if s.get("type") == "click" and "btn" not in s:
                    s["btn"] = "left"
                if s.get("type") == "combo":
                    for act in s.get("actions", []):
                        if act.get("type") == "click" and "btn" not in act:
                            act["btn"] = "left"

            combos.clear()
            combos.extend(data.get("combos", []))
            steps.clear()
            steps.extend(data.get("steps", []))

            self.refresh_combo_list()
            self.refresh_combo_actions_list()
            self.update_step_list()
            self.set_status(f"成功載入設定檔：{name}")
        except Exception as e:
            self.set_status(f"載入失敗: {e}")

    # ======================= 視窗綁定 =======================
    def get_window_list(self):
        if not IS_WINDOWS:
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
        user32.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(enum_proc), 0)
        return windows

    def refresh_window_dropdown(self):
        global target_hwnd
        win_list = self.get_window_list()
        items, target_idx = [], 0
        for i, (hwnd, title) in enumerate(win_list):
            items.append(f"[{hwnd}] {title}")
            if "水滸" in title or "online" in title.lower(): target_idx = i

        if not items:
            items, target_hwnd = ["未偵測到任何視窗"], None
        else:
            target_hwnd = win_list[target_idx][0]

        self.cbo_window["values"] = items
        self.cbo_window.current(target_idx)
        if target_hwnd:
            self.set_status(f"已綁定目標視窗 HWND: {target_hwnd}")

    def on_window_select(self, event=None):
        global target_hwnd
        val = self.var_window.get()
        if val and val.startswith("["):
            try:
                target_hwnd = int(val.split("]")[0].replace("[", ""))
                self.set_status(f"已綁定目標視窗 HWND: {target_hwnd}")
            except Exception:
                target_hwnd = None

    # ======================= 組合管理邏輯 =======================
    def get_selected_combo_idx(self):
        sel = self.combo_listbox.curselection()
        return sel[0] if sel and 0 <= sel[0] < len(combos) else None

    def refresh_call_combo_dropdown(self):
        idx = self.get_selected_combo_idx()
        curr_name = combos[idx]["name"] if idx is not None else None
        avail = [c["name"] for c in combos if c["name"] != curr_name]
        self.cbo_call_combo["values"] = avail
        if avail:
            if self.var_combo_to_call.get() not in avail:
                self.cbo_call_combo.current(0)
        else:
            self.var_combo_to_call.set("")

    def refresh_combo_list(self, select_idx=None):
        self.combo_listbox.delete(0, tk.END)
        for i, c in enumerate(combos):
            act_count = len(c.get("actions", []))
            self.combo_listbox.insert(tk.END, f"{i+1:02d}. {c['name']} ({act_count}動作)")
        if select_idx is not None and 0 <= select_idx < len(combos):
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
        c = combos[idx]
        self.var_combo_name.set(c["name"])
        self.lbl_combo_editing.config(text=f"【編輯: {c['name']}】")
        self.refresh_combo_actions_list()
        self.refresh_call_combo_dropdown()

    def add_new_combo(self):
        name = self.var_combo_name.get().strip() or f"組合{len(combos)+1}"
        combos.append({"name": name, "actions": []})
        self.refresh_combo_list(select_idx=len(combos)-1)
        self.set_status(f"已建立新組合: [{name}]")

    def duplicate_selected_combo(self):
        idx = self.get_selected_combo_idx()
        if idx is None: return self.set_status("請先在左邊清單點選要複製的組合！")
        orig = combos[idx]
        base_name = orig["name"]
        new_name = f"{base_name}_副本"
        count = 1
        while any(c["name"] == new_name for c in combos):
            count += 1
            new_name = f"{base_name}_副本{count}"

        combos.insert(idx + 1, {"name": new_name, "actions": copy.deepcopy(orig.get("actions", []))})
        self.refresh_combo_list(select_idx=idx + 1)
        self.set_status(f"已複製組合 [{base_name}] 為 [{new_name}]")

    def rename_selected_combo(self):
        idx = self.get_selected_combo_idx()
        if idx is None: return self.set_status("請先在左邊點選要改名的組合！")
        new_name = self.var_combo_name.get().strip()
        if not new_name: return
        old_name = combos[idx]["name"]
        combos[idx]["name"] = new_name

        for c in combos:
            for act in c.get("actions", []):
                if act.get("type") == "call_combo" and act.get("target_name") == old_name:
                    act["target_name"] = new_name

        sync_cnt = 0
        for s in steps:
            if s.get("type") == "combo":
                if s.get("name") == old_name:
                    s["name"] = new_name
                    sync_cnt += 1
                for act in s.get("actions", []):
                    if act.get("type") == "call_combo" and act.get("target_name") == old_name:
                        act["target_name"] = new_name

        if sync_cnt > 0: self.update_step_list()
        self.refresh_combo_list(select_idx=idx)
        self.set_status(f"已將組合改名為 [{new_name}]，同步刷新了關聯步驟")

    def delete_selected_combo(self):
        idx = self.get_selected_combo_idx()
        if idx is None: return
        name = combos[idx]["name"]
        del combos[idx]
        new_sel = min(idx, len(combos) - 1) if combos else None
        self.refresh_combo_list(select_idx=new_sel)
        self.on_combo_select()
        self.set_status(f"已刪除組合 [{name}]")

    def add_combo_to_main_steps(self):
        idx = self.get_selected_combo_idx()
        if idx is None: return self.set_status("請先在左邊選擇要加入的組合！")
        c = combos[idx]
        if not c.get("actions"): return self.set_status(f"組合 [{c['name']}] 內尚未加入任何動作！")

        ins = self.get_main_insert_index()
        steps.insert(ins, {"type": "combo", "name": c["name"], "actions": copy.deepcopy(c["actions"]), "enabled": True})
        self.update_step_list(select_idx=ins)
        self.set_status(f"已將組合 [{c['name']}] 加入掛機流程 #{ins+1}")

    # ======================= 組合動作邏輯 =======================
    def get_selected_action_idx(self):
        sel = self.combo_act_listbox.curselection()
        return sel[0] if sel else None

    def refresh_combo_actions_list(self, select_idx=None):
        idx = self.get_selected_combo_idx()
        if idx is None:
            self.combo_act_listbox.delete(0, tk.END)
            return
        actions = combos[idx].get("actions", [])
        items = [(format_action_summary(act, index=i), act.get("enabled", True)) for i, act in enumerate(actions)]
        self.combo_act_listbox.set_items(items, select_idx=select_idx)

    def on_combo_action_chk_toggle(self, idx, is_enabled):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None: return
        actions = combos[c_idx]["actions"]
        if 0 <= idx < len(actions):
            actions[idx]["enabled"] = is_enabled
            self.sync_combo_actions_to_main_steps(combos[c_idx]["name"], actions)
            state_str = "啟用" if is_enabled else "停用"
            self.set_status(f"已將動作 #{idx+1} 切換為: {state_str}")

    def sync_combo_actions_to_main_steps(self, combo_name, new_actions):
        sync_cnt = 0
        for s in steps:
            if s.get("type") == "combo" and s.get("name") == combo_name:
                s["actions"] = copy.deepcopy(new_actions)
                sync_cnt += 1
        if sync_cnt > 0: self.update_step_list()

    def test_run_selected_combo_action(self):
        c_idx = self.get_selected_combo_idx()
        a_idx = self.get_selected_action_idx()
        if c_idx is None or a_idx is None:
            return self.set_status("請先選擇要試跑的組合動作！")
        act = combos[c_idx]["actions"][a_idx]
        self.run_in_test_thread("所選組合動作", lambda: self.execute_single_action(act, "組合動作試跑"))

    def test_run_current_combo(self):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None:
            return self.set_status("請先選擇要試跑的組合！")
        c = combos[c_idx]

        def _run():
            for a_idx, act in enumerate(c.get("actions", [])):
                if not act.get("enabled", True): continue
                self.execute_single_action(act, f"[{c['name']}#{a_idx+1}]")

        self.run_in_test_thread(f"組合 [{c['name']}]", _run)

    def combo_add_click_action(self):
        idx = self.get_selected_combo_idx()
        if idx is None: return self.set_status("請先選取一個組合！")
        target_btn = "right" if self.var_combo_btn.get() == "右鍵" else "left"

        def cb(x, y, rel):
            actions = combos[idx].setdefault("actions", [])
            ins = self.get_selected_action_idx()
            ins = ins + 1 if ins is not None else len(actions)
            actions.insert(ins, {"type": "click", "btn": target_btn, "x": x, "y": y, "rel": rel, "enabled": True})
            self.refresh_combo_actions_list(select_idx=ins)
            self.refresh_combo_list(select_idx=idx)
            self.sync_combo_actions_to_main_steps(combos[idx]["name"], actions)
            btn_cn = "右鍵" if target_btn == "right" else "左鍵"
            self.set_status(f"已在組合加入{btn_cn}點擊 ({x},{y})")

        self.capture_pos_space(cb, btn=target_btn)

    def combo_add_manual_click(self):
        idx = self.get_selected_combo_idx()
        if idx is None: return self.set_status("請先選取一個組合！")
        try:
            x = int(self.var_combo_manual_x.get().strip())
            y = int(self.var_combo_manual_y.get().strip())
        except ValueError:
            return self.set_status("X 和 Y 必須輸入整數！")

        target_btn = "right" if self.var_combo_btn.get() == "右鍵" else "left"
        actions = combos[idx].setdefault("actions", [])
        ins = self.get_selected_action_idx()
        ins = ins + 1 if ins is not None else len(actions)
        rel = self.var_use_rel.get()
        actions.insert(ins, {"type": "click", "btn": target_btn, "x": x, "y": y, "rel": rel, "enabled": True})
        self.refresh_combo_actions_list(select_idx=ins)
        self.refresh_combo_list(select_idx=idx)
        self.sync_combo_actions_to_main_steps(combos[idx]["name"], actions)
        btn_cn = "右鍵" if target_btn == "right" else "左鍵"
        self.set_status(f"已手動在組合加入{btn_cn}點擊: ({x}, {y})")

    def edit_selected_combo_action(self):
        c_idx = self.get_selected_combo_idx()
        a_idx = self.get_selected_action_idx()
        if c_idx is None or a_idx is None: return self.set_status("請先選擇組合動作！")

        act = combos[c_idx]["actions"][a_idx]
        curr_combo_name = combos[c_idx]["name"]
        avail_combos = [c["name"] for c in combos if c["name"] != curr_combo_name]

        if self.prompt_edit_action(act, available_combos=avail_combos):
            self.refresh_combo_actions_list(select_idx=a_idx)
            self.sync_combo_actions_to_main_steps(combos[c_idx]["name"], combos[c_idx]["actions"])
            self.set_status(f"已成功更新組合動作 #{a_idx+1}")

    def combo_add_key_action(self):
        idx = self.get_selected_combo_idx()
        if idx is None: return self.set_status("請先選取一個組合！")
        key = self.var_combo_act_key.get().strip().lower()
        if not key: return
        actions = combos[idx].setdefault("actions", [])
        ins = self.get_selected_action_idx()
        ins = ins + 1 if ins is not None else len(actions)
        actions.insert(ins, {"type": "key", "key": key, "enabled": True})
        self.refresh_combo_actions_list(select_idx=ins)
        self.refresh_combo_list(select_idx=idx)
        self.sync_combo_actions_to_main_steps(combos[idx]["name"], actions)
        self.set_status(f"已在組合加入按鍵 [{key.upper()}]")

    def combo_add_wait_action(self):
        idx = self.get_selected_combo_idx()
        if idx is None: return self.set_status("請先選取一個組合！")
        try:
            sec = float(self.var_combo_act_wait.get())
            if sec <= 0: raise ValueError
        except ValueError: return self.set_status("停頓秒數必須大於0！")
        actions = combos[idx].setdefault("actions", [])
        ins = self.get_selected_action_idx()
        ins = ins + 1 if ins is not None else len(actions)
        actions.insert(ins, {"type": "wait", "sec": sec, "enabled": True})
        self.refresh_combo_actions_list(select_idx=ins)
        self.refresh_combo_list(select_idx=idx)
        self.sync_combo_actions_to_main_steps(combos[idx]["name"], actions)
        self.set_status(f"已在組合加入停頓 {sec} 秒")

    def combo_add_call_action(self):
        idx = self.get_selected_combo_idx()
        if idx is None: return self.set_status("請先選取一個組合！")
        target_name = self.var_combo_to_call.get().strip()
        if not target_name: return self.set_status("請先在下拉選單選擇要呼叫的組合！")
        if target_name == combos[idx]["name"]: return self.set_status("不能在組合內呼叫自己！")

        actions = combos[idx].setdefault("actions", [])
        ins = self.get_selected_action_idx()
        ins = ins + 1 if ins is not None else len(actions)
        actions.insert(ins, {"type": "call_combo", "target_name": target_name, "enabled": True})
        self.refresh_combo_actions_list(select_idx=ins)
        self.refresh_combo_list(select_idx=idx)
        self.sync_combo_actions_to_main_steps(combos[idx]["name"], actions)
        self.set_status(f"已在組合加入呼叫: [{target_name}]")

    def move_combo_action(self, delta):
        c_idx = self.get_selected_combo_idx()
        a_idx = self.get_selected_action_idx()
        if c_idx is None or a_idx is None: return
        actions = combos[c_idx]["actions"]
        target = a_idx + delta
        if 0 <= target < len(actions):
            actions[a_idx], actions[target] = actions[target], actions[a_idx]
            self.refresh_combo_actions_list(select_idx=target)
            self.sync_combo_actions_to_main_steps(combos[c_idx]["name"], actions)

    def duplicate_combo_action(self):
        c_idx = self.get_selected_combo_idx()
        a_idx = self.get_selected_action_idx()
        if c_idx is None or a_idx is None: return
        actions = combos[c_idx]["actions"]
        actions.insert(a_idx + 1, copy.deepcopy(actions[a_idx]))
        self.refresh_combo_actions_list(select_idx=a_idx + 1)
        self.refresh_combo_list(select_idx=c_idx)
        self.sync_combo_actions_to_main_steps(combos[c_idx]["name"], actions)
        self.set_status(f"已複製組合動作 #{a_idx+1}")

    def delete_combo_action(self):
        c_idx = self.get_selected_combo_idx()
        a_idx = self.get_selected_action_idx()
        if c_idx is None or a_idx is None: return
        actions = combos[c_idx]["actions"]
        del actions[a_idx]
        new_sel = min(a_idx, len(actions) - 1) if actions else None
        self.refresh_combo_actions_list(select_idx=new_sel)
        self.refresh_combo_list(select_idx=c_idx)
        self.sync_combo_actions_to_main_steps(combos[c_idx]["name"], actions)
        self.set_status("已刪除組合動作")

    def clear_combo_actions(self):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None: return
        if not combos[c_idx].get("actions"): return
        if messagebox.askyesno("清空確認", f"請問是否清空組合 [{combos[c_idx]['name']}] 的所有動作？", parent=self):
            combos[c_idx]["actions"].clear()
            self.refresh_combo_actions_list()
            self.refresh_combo_list(select_idx=c_idx)
            self.sync_combo_actions_to_main_steps(combos[c_idx]["name"], [])
            self.set_status("已清空組合所有動作")

    # ======================= 自動循環清單（掛機流程）邏輯 =======================
    def get_main_insert_index(self):
        sel = self.step_listbox.curselection()
        return sel[0] + 1 if sel else len(steps)

    def build_main_display_list(self):
        return [(format_action_summary(s, index=i), s.get("enabled", True)) for i, s in enumerate(steps)]

    def update_step_list(self, select_idx=None):
        items = self.build_main_display_list()
        self.step_listbox.set_items(items, select_idx=select_idx)

    def on_main_step_chk_toggle(self, idx, is_enabled):
        if 0 <= idx < len(steps):
            steps[idx]["enabled"] = is_enabled
            state_str = "啟用" if is_enabled else "停用"
            self.set_status(f"已將步驟 #{idx+1} 切換為: {state_str}")

    def test_run_selected_main_step(self):
        sel = self.step_listbox.curselection()
        if not sel:
            return self.set_status("請先選擇要試跑的主步驟！")
        idx = sel[0]
        s = steps[idx]

        def _run():
            if s.get("type") == "combo":
                c_name = s.get("name", "組合")
                for sub_idx, sub_act in enumerate(s.get("actions", [])):
                    if not sub_act.get("enabled", True): continue
                    self.execute_single_action(sub_act, f"[{c_name}#{sub_idx+1}]")
            else:
                self.execute_single_action(s, f"步驟#{idx+1}")

        self.run_in_test_thread(f"步驟 #{idx+1}", _run)

    def add_main_click_step(self):
        ins = self.get_main_insert_index()
        target_btn = "right" if self.var_step_btn.get() == "右鍵" else "left"

        def cb(x, y, rel):
            steps.insert(ins, {"type": "click", "btn": target_btn, "x": x, "y": y, "rel": rel, "enabled": True})
            self.update_step_list(ins)
            btn_cn = "右鍵" if target_btn == "right" else "左鍵"
            self.set_status(f"已成功新增{btn_cn}點擊位置到第 #{ins+1} 步")

        self.capture_pos_space(cb, btn=target_btn)

    def add_main_manual_click(self):
        try:
            x = int(self.var_step_manual_x.get().strip())
            y = int(self.var_step_manual_y.get().strip())
        except ValueError:
            return self.set_status("X 和 Y 必須輸入整數！")

        ins = self.get_main_insert_index()
        rel = self.var_use_rel.get()
        target_btn = "right" if self.var_step_btn.get() == "右鍵" else "left"
        steps.insert(ins, {"type": "click", "btn": target_btn, "x": x, "y": y, "rel": rel, "enabled": True})
        self.update_step_list(ins)
        btn_cn = "右鍵" if target_btn == "right" else "左鍵"
        self.set_status(f"已手動插入{btn_cn}點擊到掛機流程 #{ins+1}: ({x}, {y})")

    def edit_selected_main_step(self):
        sel = self.step_listbox.curselection()
        if not sel: return self.set_status("請先在掛機流程選擇步驟！")
        idx = sel[0]
        s = steps[idx]

        if self.prompt_edit_action(s):
            self.update_step_list(idx)
            self.set_status(f"已成功更新主步驟 #{idx+1}")

    def add_main_key_step(self):
        key = self.var_step_key.get().strip().lower()
        if not key: return
        ins = self.get_main_insert_index()
        steps.insert(ins, {"type": "key", "key": key, "enabled": True})
        self.update_step_list(ins)
        self.set_status(f"已插入按鍵到掛機流程 #{ins+1}: [{key.upper()}]")

    def add_main_wait_step(self):
        try:
            sec = float(self.var_step_wait.get())
            if sec <= 0: raise ValueError
        except ValueError: return
        ins = self.get_main_insert_index()
        steps.insert(ins, {"type": "wait", "sec": sec, "enabled": True})
        self.update_step_list(ins)
        self.set_status(f"已插入等待到掛機流程 #{ins+1}: {sec} 秒")

    def move_main_step(self, delta):
        sel = self.step_listbox.curselection()
        if sel and 0 <= sel[0] + delta < len(steps):
            idx = sel[0]
            steps[idx], steps[idx + delta] = steps[idx + delta], steps[idx]
            self.update_step_list(idx + delta)

    def duplicate_main_step(self):
        sel = self.step_listbox.curselection()
        if not sel: return self.set_status("請先在清單點選要複製的步驟！")
        idx = sel[0]
        steps.insert(idx + 1, copy.deepcopy(steps[idx]))
        self.update_step_list(idx + 1)
        self.set_status(f"已複製主步驟 #{idx+1}")

    def delete_main_step(self):
        sel = self.step_listbox.curselection()
        if sel:
            idx = sel[0]
            del steps[idx]
            self.update_step_list(min(idx, len(steps) - 1) if steps else None)

    def clear_main_steps(self):
        if not steps: return self.set_status("掛機流程本來就是空的")
        if messagebox.askyesno("清空確認", "請問是否清空整個掛機流程？\n清空後未儲存的內容無法還原！", parent=self):
            steps.clear()
            self.update_step_list()
            self.set_status("已清空掛機流程")

    # ======================= 單步執行輔助器 =======================
    def execute_single_action(self, act, desc):
        use_bg = self.var_use_bg.get() and IS_WINDOWS and (target_hwnd is not None)
        try: off_x, off_y = int(self.var_offset_x.get() or 0), int(self.var_offset_y.get() or 0)
        except Exception: off_x, off_y = 0, 0

        atype = act.get("type")
        if atype == "click":
            btn = act.get("btn", "left")
            msg = execute_click(act["x"], act["y"], act.get("rel"), use_bg, off_x, off_y, btn=btn)
            self.set_status(f"{desc} {msg}")
            safe_sleep(0.12)
        elif atype == "key":
            if use_bg:
                post_bg_key(target_hwnd, act["key"])
            else:
                with currently_held_keys_lock:
                    currently_held_keys.add(("fg", act["key"]))
                try:
                    pyautogui.keyDown(act["key"])
                    safe_sleep(0.06)
                finally:
                    try: pyautogui.keyUp(act["key"])
                    except Exception: pass
                    with currently_held_keys_lock:
                        currently_held_keys.discard(("fg", act["key"]))
            self.set_status(f"{desc} 按鍵 [{act['key'].upper()}]")
            safe_sleep(0.10)
        elif atype == "wait":
            sec = float(act.get("sec", 0.5))
            self.set_status(f"{desc} 等待 {sec}s")
            safe_sleep(sec)
        elif atype == "call_combo":
            tgt_name = act.get("target_name")
            with steps_lock:
                tgt_combo = copy.deepcopy(next((c for c in combos if c["name"] == tgt_name), None))
            if tgt_combo:
                for sub_idx, sub_act in enumerate(tgt_combo.get("actions", [])):
                    if not sub_act.get("enabled", True): continue
                    self.execute_single_action(sub_act, f"{desc}->[{tgt_name}#{sub_idx+1}]")

    # ======================= 主執行引擎 =======================
    def toggle_run(self):
        global running, active_steps, active_combos, reload_requested
        if running:
            running = False
            stop_event.set()
            emergency_release_all()
            self.set_running_ui(False)
            self.set_status("已手動停止")
        else:
            if not steps: return self.set_status("執行清單是空的，請先加入步驟！")
            with steps_lock:
                active_steps = copy.deepcopy(steps)
                active_combos = copy.deepcopy(combos)
                reload_requested = False
            stop_event.clear()
            running = True
            self.set_running_ui(True)
            self.set_status("循環運作中...")
            threading.Thread(target=self.macro_worker_loop, daemon=True).start()

    def macro_worker_loop(self):
        global running, reload_requested
        round_idx = 1

        def run_action(act, parent_desc, depth=0, visited_set=None, current_combos=None):
            if visited_set is None: visited_set = set()
            if current_combos is None: current_combos = []
            if not running or stop_event.is_set() or reload_requested: return False
            if not act.get("enabled", True): return True

            use_bg = self.var_use_bg.get() and IS_WINDOWS and (target_hwnd is not None)
            try: off_x, off_y = int(self.var_offset_x.get() or 0), int(self.var_offset_y.get() or 0)
            except Exception: off_x, off_y = 0, 0

            atype = act.get("type")
            if atype == "click":
                btn = act.get("btn", "left")
                msg = execute_click(act["x"], act["y"], act.get("rel"), use_bg, off_x, off_y, btn=btn)
                self.set_status(f"第 {round_idx} 輪: {parent_desc} {msg}")
                if not safe_sleep(0.12): return False

            elif atype == "key":
                if use_bg:
                    post_bg_key(target_hwnd, act["key"])
                else:
                    with currently_held_keys_lock:
                        currently_held_keys.add(("fg", act["key"]))
                    try:
                        pyautogui.keyDown(act["key"])
                        if not safe_sleep(0.06): return False
                    finally:
                        try: pyautogui.keyUp(act["key"])
                        except Exception: pass
                        with currently_held_keys_lock:
                            currently_held_keys.discard(("fg", act["key"]))
                self.set_status(f"第 {round_idx} 輪: {parent_desc} 按鍵 [{act['key'].upper()}]")
                if not safe_sleep(0.10): return False

            elif atype == "wait":
                sec = float(act.get("sec", 0.5))
                self.set_status(f"第 {round_idx} 輪: {parent_desc} 等待 {sec}s")
                if not safe_sleep(sec): return False

            elif atype == "call_combo":
                tgt_name = act.get("target_name")
                if not tgt_name: return True
                if depth >= 10:
                    self.set_status(f"第 {round_idx} 輪: 呼叫 [{tgt_name}] 超過深度上限")
                    return True
                if tgt_name in visited_set:
                    self.set_status(f"第 {round_idx} 輪: 循環呼叫 [{tgt_name}]，自動跳過")
                    return True

                tgt_combo = next((c for c in current_combos if c["name"] == tgt_name), None)
                if tgt_combo:
                    new_visited = visited_set | {tgt_name}
                    for sub_idx, sub_act in enumerate(tgt_combo.get("actions", [])):
                        if not running or stop_event.is_set() or reload_requested: return False
                        if not sub_act.get("enabled", True): continue
                        sub_desc = f"{parent_desc}->[{tgt_name}#{sub_idx+1}]"
                        if not run_action(sub_act, sub_desc, depth + 1, new_visited, current_combos=current_combos):
                            return False
                else:
                    self.set_status(f"第 {round_idx} 輪: 找不到被呼叫的組合 [{tgt_name}]")

            return True

        try:
            while running and not stop_event.is_set():
                with steps_lock:
                    current_steps = copy.deepcopy(active_steps)
                    current_combos = copy.deepcopy(active_combos)
                    reload_requested = False

                for idx, step in enumerate(current_steps):
                    if not running or stop_event.is_set(): break
                    if reload_requested:
                        self.set_status("已檢測到熱更新，即時重新加載最新流程...")
                        break

                    if not step.get("enabled", True): continue

                    self.highlight_active_step(idx)

                    stype = step["type"]
                    if stype == "combo":
                        c_name = step.get("name", "組合")
                        c_actions = step.get("actions", [])
                        for a_idx, act in enumerate(c_actions):
                            if not running or stop_event.is_set() or reload_requested: break
                            if not act.get("enabled", True): continue
                            self.highlight_active_step(idx, sub_idx=a_idx)
                            act_desc = f"[{c_name}#{a_idx+1}]"
                            if not run_action(act, act_desc, depth=0, visited_set={c_name}, current_combos=current_combos):
                                break
                    else:
                        if not run_action(step, f"步驟#{idx+1}", depth=0, visited_set=set(), current_combos=current_combos):
                            break

                round_idx += 1
                if not safe_sleep(0.05):
                    if reload_requested:
                        continue
                    break
        except Exception as e:
            self.set_status(f"異常中斷: {e}")
        finally:
            running = False
            emergency_release_all()
            self.set_running_ui(False)

if __name__ == "__main__":
    app = App()
    app.mainloop()