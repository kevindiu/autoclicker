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

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

WINDOW_TITLE = "水滸歷險 巨集助手"
CONFIG_EXT = ".shm"

def resource_path(relative_path):
    """獲取資源絕對路徑 (相容 PyInstaller 單一執行檔打包與原始碼執行)"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    base_dir = os.path.abspath(os.path.dirname(__file__)) if '__file__' in globals() else os.path.abspath(".")
    return os.path.join(base_dir, relative_path)

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
    ACCENT_CYAN = "#0284c7"      # 青藍 (展開)
    ACCENT_CYAN_HOVER = "#0369a1"

    # ================= 統一清晰字體系統 (微軟正黑體 UI) =================
    FONT_FAMILY = "Microsoft JhengHei UI" if sys.platform == "win32" else ("PingFang TC" if sys.platform == "darwin" else "Noto Sans CJK TC")
    
    FONT_SMALL = (FONT_FAMILY, 9)
    FONT_SMALL_BOLD = (FONT_FAMILY, 9, "bold")
    FONT_NORMAL = (FONT_FAMILY, 10)
    FONT_NORMAL_BOLD = (FONT_FAMILY, 10, "bold")
    FONT_TITLE = (FONT_FAMILY, 11, "bold")
    FONT_BIG_BTN = (FONT_FAMILY, 12, "bold")

# ==============================================================================
# 全域資料狀態與執行緒同步物件
# ==============================================================================
combos = []
steps = []           # 主 UI 編輯器草稿 (Draft)
variables = {}       # 全域變數庫字典: {var_name: {"type": "coord"|"key"|"wait", ...}}
active_steps = []    # 背景運行實例快照 (Active Snapshot)
active_combos = []   # 背景組合運行實例快照 (Active Combo Snapshot)
active_variables = {} # 背景變數運行實例快照 (Active Variables Snapshot)

running = False
is_testing = False
reload_requested = False
steps_lock = threading.Lock() # 保護 active_steps, active_combos 與 active_variables
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
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
else:
    WNDENUMPROC = None

VK_MAP = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "tab": 0x09, "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
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
        if not is_testing and not running:
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
        scan_code = 0
        try:
            scan_code = user32.MapVirtualKeyW(vk, 0)
        except Exception:
            pass
        lparam_down = to_lparam(1 | (scan_code << 16))
        lparam_up = to_lparam(1 | (scan_code << 16) | 0xC0000000)
        with currently_held_keys_lock:
            currently_held_keys.add(("bg", hwnd, vk))
        try:
            user32.PostMessageW(hwnd, 0x0100, vk, lparam_down)
            safe_sleep(0.06)
        finally:
            user32.PostMessageW(hwnd, 0x0101, vk, lparam_up)
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

def format_action_summary(act, index=None, current_variables=None):
    """統一格式化動作或步驟的文字描述，採用 100% 跨平台相容的通用標籤與符號"""
    var_dict = current_variables if current_variables is not None else variables
    atype = act.get("type", "")

    idx_prefix = f"#{index+1:02d} " if index is not None else ""
    var_name = act.get("var_name")

    if atype == "click":
        btn_tag = "右鍵" if act.get("btn") == "right" else "左鍵"
        if var_name:
            v_info = var_dict.get(var_name, {})
            val = v_info.get("value") if isinstance(v_info.get("value"), dict) else v_info
            cx = val.get("x", act.get("x", 0))
            cy = val.get("y", act.get("y", 0))
            body = f"[點擊·{btn_tag}] -> 變數:【{var_name}】({cx},{cy})"
        else:
            prefix = "相對:" if act.get("rel") else "絕對:"
            body = f"[點擊·{btn_tag}] -> {prefix}({act.get('x', 0)},{act.get('y', 0)})"
    elif atype == "key":
        if var_name:
            v_info = var_dict.get(var_name, {})
            val = v_info.get("value") if "value" in v_info else v_info.get("key", act.get("key", ""))
            k_str = str(val).upper()
            body = f"[按鍵] -> 變數:【{var_name}】[ {k_str} ]"
        else:
            key_str = str(act.get("key", "")).upper()
            body = f"[按鍵] -> [ {key_str} ]"
    elif atype == "wait":
        if var_name:
            v_info = var_dict.get(var_name, {})
            val = v_info.get("value") if "value" in v_info else v_info.get("sec", act.get("sec", 0))
            body = f"[停頓] -> 變數:【{var_name}】{val} 秒"
        else:
            body = f"[停頓] -> {act.get('sec', 0)} 秒"
    elif atype == "call_combo":
        body = f"↻ [呼叫] -> 組合:【{act.get('target_name', '')}】"
    elif atype == "combo":
        c_name = act.get("name", "組合")
        act_cnt = len(act.get("actions", []))
        body = f"◆ [組合: {c_name}] ({act_cnt}個動作)"
    else:
        body = f"[{atype}]"

    return f"{idx_prefix}{body}"

# ==============================================================================
# 自訂組件：全深色模式變數表格 (VarTable)
# ==============================================================================
class VarTable(tk.Frame):
    def __init__(self, parent, bg=UITheme.BG_DARK, select_bg=UITheme.ACCENT_BLUE, on_double_click=None):
        super().__init__(parent, bg=bg)
        self.bg = bg
        self.select_bg = select_bg
        self.on_double_click = on_double_click
        self.selected_name = None
        self.rows = {}

        # 標題欄
        self.hdr = tk.Frame(self, bg=UITheme.BG_PANEL, pady=3, padx=4)
        self.hdr.pack(fill="x")
        tk.Label(self.hdr, text="變數名稱", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_SMALL_BOLD, width=12, anchor="w").pack(side="left", padx=2)
        tk.Label(self.hdr, text="種類", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_SMALL_BOLD, width=9, anchor="center").pack(side="left", padx=2)
        tk.Label(self.hdr, text="當前數值", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_SMALL_BOLD, anchor="w").pack(side="left", fill="x", expand=True, padx=2)

        # 內容滾動區
        f_box = tk.Frame(self, bg=bg)
        f_box.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(f_box, bg=bg, bd=0, highlightthickness=0, height=60)
        self.scrollbar = tk.Scrollbar(f_box, orient="vertical", command=self.canvas.yview)
        self.body_frame = tk.Frame(self.canvas, bg=bg)

        self.body_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.body_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width))

        self.bind_mousewheel(self)
        self.bind_mousewheel(self.canvas)
        self.bind_mousewheel(self.body_frame)

    def bind_mousewheel(self, widget):
        widget.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units") if e.delta else None, add="+")
        widget.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"), add="+")
        widget.bind("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"), add="+")

    def get_children(self):
        return list(self.rows.keys())

    def delete(self, item):
        if item in self.rows:
            self.rows[item]['frame'].destroy()
            del self.rows[item]
            if self.selected_name == item:
                self.selected_name = None

    def insert(self, parent, index, iid=None, values=()):
        name, t_disp, v_str = values
        rf = tk.Frame(self.body_frame, bg=self.bg, pady=2, padx=4)
        rf.pack(fill="x", expand=True)

        l1 = tk.Label(rf, text=name, bg=self.bg, fg=UITheme.TEXT_MAIN, font=UITheme.FONT_NORMAL, width=12, anchor="w")
        l1.pack(side="left", padx=2)
        l2 = tk.Label(rf, text=t_disp, bg=self.bg, fg=UITheme.CYAN_SUB, font=UITheme.FONT_SMALL_BOLD, width=9, anchor="center")
        l2.pack(side="left", padx=2)
        l3 = tk.Label(rf, text=v_str, bg=self.bg, fg="#e5e7eb", font=UITheme.FONT_NORMAL, anchor="w")
        l3.pack(side="left", fill="x", expand=True, padx=2)

        for w in (rf, l1, l2, l3):
            w.bind("<Button-1>", lambda e, n=iid: self._select(n))
            w.bind("<Double-Button-1>", lambda e, n=iid: self._on_dbl(n))
            self.bind_mousewheel(w)

        self.rows[iid] = {'frame': rf, 'l1': l1, 'l2': l2, 'l3': l3}

    def _select(self, name):
        if self.selected_name in self.rows:
            old = self.rows[self.selected_name]
            for w in (old['frame'], old['l1'], old['l2'], old['l3']):
                w.config(bg=self.bg)
        self.selected_name = name
        if name in self.rows:
            curr = self.rows[name]
            for w in (curr['frame'], curr['l1'], curr['l2'], curr['l3']):
                w.config(bg=self.select_bg)

    def _on_dbl(self, name):
        self._select(name)
        if self.on_double_click:
            self.on_double_click()

    def selection(self):
        return (self.selected_name,) if self.selected_name else ()

# ==============================================================================
# 原生 Tkinter GUI 主應用程式
# ==============================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("1280x720")
        self.minsize(1200, 660)
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
        global running
        running = False
        stop_event.set()
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
                    self.step_listbox.selection_clear(0, tk.END)
        self.run_on_ui_thread(_u)

    def run_in_test_thread(self, task_name, task_fn):
        """統一的非同步試跑安全守衛與執行緒啟動器"""
        if running:
            return self.set_status("巨集正在循環執行中，請先停止再試跑！")
        if is_testing:
            return self.set_status("已有試跑任務正在執行中，請稍候！")

        def _worker():
            global is_testing
            is_testing = True
            stop_event.clear()  # 關鍵修復：清除先前手動停止或循環殘留的中止信號
            self.set_running_ui(True, is_test=True)
            try:
                self.set_status(f"正在試跑 {task_name}...")
                task_fn()
                if stop_event.is_set():
                    self.set_status(f"{task_name} 試跑已手動中止！")
                else:
                    self.set_status(f"{task_name} 試跑完成！")
            except Exception as e:
                self.set_status(f"{task_name} 試跑異常: {e}")
            finally:
                is_testing = False
                emergency_release_all()
                self.set_running_ui(False)

        threading.Thread(target=_worker, daemon=True).start()

    def track_mouse_live(self):
        """實時監控游標坐標並更新 HUD (具備坐標變更感知，無移動不消耗重繪資源)"""
        if self.is_closing:
            return
        try:
            pos = pyautogui.position()
            if IS_WINDOWS and target_hwnd and getattr(self, "cached_use_rel", True):
                pt = POINT(int(pos.x), int(pos.y))
                user32.ScreenToClient(target_hwnd, ctypes.byref(pt))
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
        if not IS_WINDOWS or not hwnd:
            return
        try:
            if user32.GetForegroundWindow() == hwnd:
                return  # 目標已在前台，不重複執行置頂與敲擊 Alt 鍵
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

            lbl_hud.config(text=f"【設定{btn_cn}點擊】滑鼠指住目標 -> 按 [SPACE 空白鍵] 確定！(坐標: {coord_desc} | ESC 取消)")

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

    # ======================= 主畫面執行步驟高亮跟隨 =======================
    def highlight_active_step(self, idx, sub_idx=None):
        """在主畫面清單中同步高亮當前執行中的步驟並自動滾動跟隨"""
        def _hl():
            if self.is_closing: return
            if hasattr(self, "step_listbox") and self.step_listbox.winfo_exists():
                if 0 <= idx < self.step_listbox.size():
                    self.step_listbox.selection_clear(0, tk.END)
                    self.step_listbox.selection_set(idx)
                    self.step_listbox.see(idx)
        self.run_on_ui_thread(_hl)

    def prompt_edit_combo_dialog(self, combo_step, step_idx=None):
        """彈出完整的組合子動作管理視窗 (支援在組合內移位、刪除、複製、修改、試跑與展開)"""
        dialog = tk.Toplevel(self)
        combo_name = combo_step.get("name", "組合")
        dialog.title(f"管理組合步驟: 【{combo_name}】")
        dialog.configure(bg=UITheme.BG_PANEL)
        dialog.resizable(True, True)
        dialog.attributes("-topmost", True)
        dialog.transient(self)
        dialog.grab_set()
        self.apply_app_icon(dialog)

        w, h = 660, 520
        self.update_idletasks()
        pos_x = self.winfo_x() + max(0, (self.winfo_width() - w) // 2)
        pos_y = self.winfo_y() + max(0, (self.winfo_height() - h) // 2)
        dialog.geometry(f"{w}x{h}+{pos_x}+{pos_y}")
        dialog.minsize(560, 420)

        working_actions = copy.deepcopy(combo_step.get("actions", []))
        modified = [False]

        # 頂部控制欄 (標題、切換範本、展開按鈕)
        f_top = tk.Frame(dialog, bg=UITheme.BG_PANEL, padx=12, pady=8)
        f_top.pack(fill="x")

        r1 = tk.Frame(f_top, bg=UITheme.BG_PANEL)
        r1.pack(fill="x", pady=(0, 4))
        lbl_title = tk.Label(r1, text=f"◆ 組合名稱: 【{combo_name}】", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_TITLE)
        lbl_title.pack(side="left")

        def do_unpack():
            if not working_actions:
                messagebox.showwarning("提示", "此組合內沒有任何子動作可展開！", parent=dialog)
                return
            if messagebox.askyesno("展開確認", f"確定要將組合 【{combo_name}】 的 {len(working_actions)} 個子動作直接展開為掛機流程中的獨立步驟嗎？\n\n展開後每一步均可直接在流程清單中自由移動、修改與刪除。", parent=dialog):
                if step_idx is not None and 0 <= step_idx < len(steps):
                    del steps[step_idx]
                    for offset, act in enumerate(working_actions):
                        steps.insert(step_idx + offset, copy.deepcopy(act))
                    self.update_step_list(select_idx=step_idx)
                    self.set_status(f"已將組合 [{combo_name}] 展開為 {len(working_actions)} 個獨立步驟")
                    self.trigger_hot_reload()
                modified[0] = True
                dialog.destroy()

        btn_unpack = tk.Button(
            r1,
            text="[ ➔ 展開為獨立步驟到掛機流程 ]",
            bg=UITheme.ACCENT_CYAN,
            fg="#fff",
            activebackground=UITheme.ACCENT_CYAN_HOVER,
            font=UITheme.FONT_SMALL_BOLD,
            relief="flat",
            padx=8,
            pady=2,
            command=do_unpack
        )
        btn_unpack.pack(side="right")

        r2 = tk.Frame(f_top, bg=UITheme.BG_PANEL)
        r2.pack(fill="x", pady=(4, 0))
        tk.Label(r2, text="載入組合庫範本:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 4))
        tpl_names = [c["name"] for c in combos]
        var_tpl = tk.StringVar(value=combo_name if combo_name in tpl_names else (tpl_names[0] if tpl_names else ""))
        cbo_tpl = ttk.Combobox(r2, textvariable=var_tpl, values=tpl_names, width=16, state="readonly")
        cbo_tpl.pack(side="left", padx=2)

        def do_load_tpl():
            chosen = var_tpl.get().strip()
            matched = next((c for c in combos if c["name"] == chosen), None)
            if matched:
                nonlocal combo_name
                combo_name = matched["name"]
                combo_step["name"] = combo_name
                lbl_title.config(text=f"◆ 組合名稱: 【{combo_name}】")
                working_actions.clear()
                working_actions.extend(copy.deepcopy(matched.get("actions", [])))
                refresh_sub_list(select_idx=0 if working_actions else None)
                self.set_status(f"已載入範本 [{combo_name}] 的子動作清單")

        tk.Button(r2, text="套用範本動作", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, font=UITheme.FONT_SMALL_BOLD, relief="flat", padx=6, command=do_load_tpl).pack(side="left", padx=4)

        # 中間主工作區 (左邊子步驟清單，右邊垂直操作按鈕列)
        f_mid = tk.Frame(dialog, bg=UITheme.BG_PANEL, padx=12, pady=4)
        f_mid.pack(fill="both", expand=True)

        f_list_wrap = tk.Frame(f_mid, bg=UITheme.BG_PANEL)
        f_list_wrap.pack(side="left", fill="both", expand=True)

        tk.Label(f_list_wrap, text="【子步驟清單】 (雙擊可修改)", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL_BOLD, anchor="w").pack(fill="x", pady=(0, 3))

        f_sub_box = tk.Frame(f_list_wrap, bg=UITheme.BG_DARK)
        f_sub_box.pack(fill="both", expand=True)

        sub_list = tk.Listbox(
            f_sub_box,
            bg=UITheme.BG_DARK,
            fg=UITheme.TEXT_MAIN,
            selectbackground=UITheme.ACCENT_BLUE,
            selectforeground="#fff",
            bd=0,
            highlightthickness=0,
            font=UITheme.FONT_NORMAL,
            exportselection=False
        )
        sub_list.pack(side="left", fill="both", expand=True)
        sub_list.bind("<Double-Button-1>", lambda e: do_edit_sub())

        sc_sub = tk.Scrollbar(f_sub_box, orient="vertical", command=sub_list.yview)
        sc_sub.pack(side="right", fill="y")
        sub_list.config(yscrollcommand=sc_sub.set)

        def refresh_sub_list(select_idx=None):
            sub_list.delete(0, tk.END)
            for i, act in enumerate(working_actions):
                sub_list.insert(tk.END, format_action_summary(act, index=i))
            if select_idx is not None and 0 <= select_idx < len(working_actions):
                sub_list.selection_set(select_idx)
                sub_list.see(select_idx)

        # 右側控制按鈕列
        f_btns = tk.Frame(f_mid, bg=UITheme.BG_PANEL, padx=8)
        f_btns.pack(side="right", fill="y")

        def get_sel_sub():
            sel = sub_list.curselection()
            return sel[0] if sel else None

        def do_move_sub(delta):
            idx = get_sel_sub()
            if idx is None:
                messagebox.showinfo("提示", "請先在清單中選取要移動的子步驟！", parent=dialog)
                return
            target = idx + delta
            if 0 <= target < len(working_actions):
                working_actions[idx], working_actions[target] = working_actions[target], working_actions[idx]
                refresh_sub_list(select_idx=target)

        def do_edit_sub():
            idx = get_sel_sub()
            if idx is None:
                messagebox.showinfo("提示", "請先在清單中選取要修改的子步驟！", parent=dialog)
                return
            curr_act = working_actions[idx]
            if self.prompt_edit_action(curr_act):
                refresh_sub_list(select_idx=idx)

        def do_dup_sub():
            idx = get_sel_sub()
            if idx is None:
                messagebox.showinfo("提示", "請先在清單中選取要複製的子步驟！", parent=dialog)
                return
            working_actions.insert(idx + 1, copy.deepcopy(working_actions[idx]))
            refresh_sub_list(select_idx=idx + 1)

        def do_del_sub():
            idx = get_sel_sub()
            if idx is None:
                messagebox.showinfo("提示", "請先在清單中選取要刪除的子步驟！", parent=dialog)
                return
            del working_actions[idx]
            new_sel = min(idx, len(working_actions) - 1) if working_actions else None
            refresh_sub_list(select_idx=new_sel)

        def do_test_sub():
            idx = get_sel_sub()
            if idx is None:
                messagebox.showinfo("提示", "請先在清單中選取要試跑的子步驟！", parent=dialog)
                return
            act = working_actions[idx]
            self.run_in_test_thread(f"組合動作 #{idx+1}", lambda: self.execute_single_action(act, f"[{combo_name}#{idx+1}]"))

        tk.Button(f_btns, text="▲ 上移步驟", width=12, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, pady=4, command=lambda: do_move_sub(-1)).pack(fill="x", pady=2)
        tk.Button(f_btns, text="▼ 下移步驟", width=12, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, pady=4, command=lambda: do_move_sub(1)).pack(fill="x", pady=2)
        tk.Button(f_btns, text="▶ 試跑動作", width=12, bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, pady=4, command=do_test_sub).pack(fill="x", pady=2)
        tk.Button(f_btns, text="✎ 修改動作", width=12, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, pady=4, command=do_edit_sub).pack(fill="x", pady=2)
        tk.Button(f_btns, text="⎘ 複製動作", width=12, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, pady=4, command=do_dup_sub).pack(fill="x", pady=2)
        tk.Button(f_btns, text="✕ 刪除動作", width=12, bg=UITheme.ACCENT_RED, fg="#fff", activebackground=UITheme.ACCENT_RED_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, pady=4, command=do_del_sub).pack(fill="x", pady=(2, 6))

        # 底部按鈕列 (確認 / 取消)
        f_bot = tk.Frame(dialog, bg=UITheme.BG_PANEL, padx=12, pady=10)
        f_bot.pack(fill="x")

        def on_save():
            combo_step["name"] = combo_name
            combo_step["actions"] = working_actions
            modified[0] = True
            dialog.destroy()

        tk.Button(f_bot, text="✓ 儲存並套用修改", width=16, bg=UITheme.ACCENT_GREEN, fg="#fff", activebackground=UITheme.ACCENT_GREEN_HOVER, relief="flat", font=UITheme.FONT_NORMAL_BOLD, pady=5, command=on_save).pack(side="left", padx=(0, 6))
        tk.Button(f_bot, text="✕ 取消", width=10, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_NORMAL, pady=5, command=dialog.destroy).pack(side="left")

        refresh_sub_list(select_idx=0 if working_actions else None)

        dialog.bind("<Escape>", lambda e: dialog.destroy())
        self.wait_window(dialog)
        return modified[0]

    # ======================= 全功能動作編輯彈窗 =======================
    def prompt_edit_action(self, action, available_combos=None, step_idx=None):
        """彈出針對各動作型別的編輯對話框"""
        atype = action.get("type")
        if not atype: return False

        if atype == "combo":
            return self.prompt_edit_combo_dialog(action, step_idx=step_idx)

        dialog = tk.Toplevel(self)
        dialog.configure(bg=UITheme.BG_PANEL)
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.transient(self)
        dialog.grab_set()
        self.apply_app_icon(dialog)

        w, h = 350, 260
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

            coord_vars = [k for k, v in variables.items() if v.get("type") == "coord"]
            opt_vars = ["(不引用 / 固定坐標)"] + coord_vars
            curr_var = action.get("var_name", "")
            var_ref = tk.StringVar(value=curr_var if curr_var in coord_vars else "(不引用 / 固定坐標)")

            tk.Label(f, text="引用變數:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=0, column=0, padx=6, pady=3, sticky="e")
            cbo_ref = ttk.Combobox(f, textvariable=var_ref, values=opt_vars, width=14, state="readonly")
            cbo_ref.grid(row=0, column=1, padx=6, pady=3, sticky="w")

            def on_ref_change(event=None):
                chosen = var_ref.get()
                if chosen in variables:
                    v_val = variables[chosen].get("value", {})
                    if isinstance(v_val, dict):
                        var_x.set(str(v_val.get("x", 0)))
                        var_y.set(str(v_val.get("y", 0)))
            cbo_ref.bind("<<ComboboxSelected>>", on_ref_change)

            tk.Label(f, text="按鍵類型:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=1, column=0, padx=6, pady=3, sticky="e")
            cbo_btn = ttk.Combobox(f, textvariable=var_btn, values=["左鍵", "右鍵"], width=8, state="readonly")
            cbo_btn.grid(row=1, column=1, padx=6, pady=3, sticky="w")

            tk.Label(f, text="X 坐標:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=2, column=0, padx=6, pady=3, sticky="e")
            e_x = tk.Entry(f, textvariable=var_x, width=10, bg=UITheme.BG_INPUT, fg="#fff")
            e_x.grid(row=2, column=1, padx=6, pady=3, sticky="w")

            tk.Label(f, text="Y 坐標:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=3, column=0, padx=6, pady=3, sticky="e")
            e_y = tk.Entry(f, textvariable=var_y, width=10, bg=UITheme.BG_INPUT, fg="#fff")
            e_y.grid(row=3, column=1, padx=6, pady=3, sticky="w")

            btn_rec = tk.Button(f, text="重新瞄準目標 (按 Space 確定)", width=24, bg=UITheme.ACCENT_GREEN, fg="#fff", activebackground=UITheme.ACCENT_GREEN_HOVER, font=UITheme.FONT_NORMAL_BOLD)
            btn_rec.grid(row=4, column=0, columnspan=2, pady=(8, 2))

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
                    chosen = var_ref.get()
                    if chosen in coord_vars:
                        action["var_name"] = chosen
                    else:
                        action.pop("var_name", None)
                    modified[0] = True
                    dialog.destroy()
                except ValueError:
                    messagebox.showerror("錯誤", "X 和 Y 必須輸入整數！", parent=dialog)

        elif atype == "key":
            dialog.title("修改按鍵")
            var_k = tk.StringVar(value=str(action.get("key", "f1")))
            key_vars = [k for k, v in variables.items() if v.get("type") == "key"]
            opt_vars = ["(不引用 / 固定按鍵)"] + key_vars
            curr_var = action.get("var_name", "")
            var_ref = tk.StringVar(value=curr_var if curr_var in key_vars else "(不引用 / 固定按鍵)")

            tk.Label(f, text="引用變數:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=0, column=0, padx=6, pady=3, sticky="e")
            cbo_ref = ttk.Combobox(f, textvariable=var_ref, values=opt_vars, width=14, state="readonly")
            cbo_ref.grid(row=0, column=1, padx=6, pady=3, sticky="w")

            def on_ref_change(event=None):
                chosen = var_ref.get()
                if chosen in variables:
                    var_k.set(str(variables[chosen].get("value", "")))
            cbo_ref.bind("<<ComboboxSelected>>", on_ref_change)

            tk.Label(f, text="按鍵名稱:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=1, column=0, padx=6, pady=6, sticky="e")
            e_k = tk.Entry(f, textvariable=var_k, width=12, bg=UITheme.BG_INPUT, fg="#fff")
            e_k.grid(row=1, column=1, padx=6, pady=6)
            e_k.focus_set()

            def on_ok():
                k = var_k.get().strip().lower()
                if not k:
                    messagebox.showerror("錯誤", "按鍵名稱不可為空！", parent=dialog)
                    return
                action["key"] = k
                chosen = var_ref.get()
                if chosen in key_vars:
                    action["var_name"] = chosen
                else:
                    action.pop("var_name", None)
                modified[0] = True
                dialog.destroy()

        elif atype == "wait":
            dialog.title("修改停頓時間")
            var_w = tk.StringVar(value=str(action.get("sec", 1.0)))
            wait_vars = [k for k, v in variables.items() if v.get("type") == "wait"]
            opt_vars = ["(不引用 / 固定秒數)"] + wait_vars
            curr_var = action.get("var_name", "")
            var_ref = tk.StringVar(value=curr_var if curr_var in wait_vars else "(不引用 / 固定秒數)")

            tk.Label(f, text="引用變數:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=0, column=0, padx=6, pady=3, sticky="e")
            cbo_ref = ttk.Combobox(f, textvariable=var_ref, values=opt_vars, width=14, state="readonly")
            cbo_ref.grid(row=0, column=1, padx=6, pady=3, sticky="w")

            def on_ref_change(event=None):
                chosen = var_ref.get()
                if chosen in variables:
                    var_w.set(str(variables[chosen].get("value", "")))
            cbo_ref.bind("<<ComboboxSelected>>", on_ref_change)

            tk.Label(f, text="等待秒數:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=1, column=0, padx=6, pady=6, sticky="e")
            e_w = tk.Entry(f, textvariable=var_w, width=10, bg=UITheme.BG_INPUT, fg="#fff")
            e_w.grid(row=1, column=1, padx=6, pady=6)
            e_w.focus_set()

            def on_ok():
                try:
                    sec = float(var_w.get().strip())
                    if sec <= 0: raise ValueError
                    action["sec"] = sec
                    chosen = var_ref.get()
                    if chosen in wait_vars:
                        action["var_name"] = chosen
                    else:
                        action.pop("var_name", None)
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

        # 1. 設定與視窗綁定 (精簡至 2 行，大幅節省縱向空間)
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
        tk.Button(r1, text="+ 新建", width=5, bg=UITheme.ACCENT_GREEN, fg="#fff", activebackground=UITheme.ACCENT_GREEN_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.create_new_profile).pack(side="left", padx=(1, 8))

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
        tk.Button(r2, text="↻ 重新整理", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, padx=4, command=self.refresh_window_dropdown).pack(side="left", padx=1)
        tk.Button(r2, text="◎ 定位視窗", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, padx=4, command=self.locate_target_window).pack(side="left", padx=(1, 8))

        tk.Label(r2, text="偏差校正:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left")
        tk.Label(r2, text="X:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_NORMAL).pack(side="left", padx=(3, 1))
        tk.Entry(r2, textvariable=self.var_offset_x, width=3, bg=UITheme.BG_INPUT, fg="#ffffff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=1)
        tk.Label(r2, text="Y:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_NORMAL).pack(side="left", padx=(3, 1))
        tk.Entry(r2, textvariable=self.var_offset_y, width=3, bg=UITheme.BG_INPUT, fg="#ffffff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=1)

        # 2. 常用變數庫 (表格一覽：名稱 / 種類 / 數值，雙擊可修改 | 右側操作按鈕)
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

        tk.Button(
            col_v_btns,
            text="+ 新增變數",
            width=10,
            bg=UITheme.ACCENT_GREEN,
            fg="#fff",
            activebackground=UITheme.ACCENT_GREEN_HOVER,
            font=UITheme.FONT_SMALL_BOLD,
            relief="flat",
            command=self.add_variable_dialog
        ).pack(fill="x", expand=True, pady=(0, 2))

        tk.Button(
            col_v_btns,
            text="✎ 修改變數",
            width=10,
            bg=UITheme.ACCENT_BLUE,
            fg="#fff",
            activebackground=UITheme.ACCENT_BLUE_HOVER,
            font=UITheme.FONT_SMALL_BOLD,
            relief="flat",
            command=self.edit_selected_variable
        ).pack(fill="x", expand=True, pady=2)

        tk.Button(
            col_v_btns,
            text="✕ 刪除變數",
            width=10,
            bg=UITheme.ACCENT_RED,
            fg="#fff",
            activebackground=UITheme.ACCENT_RED_HOVER,
            font=UITheme.FONT_SMALL_BOLD,
            relief="flat",
            command=self.delete_selected_variable
        ).pack(fill="x", expand=True, pady=(2, 0))

        # 3. 技能組合區塊
        f_combo = tk.LabelFrame(f_left, text=" 技能組合庫 ", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_TITLE, padx=6, pady=6)
        f_combo.pack(fill="both", expand=True)

        f_combo_split = tk.Frame(f_combo, bg=UITheme.BG_PANEL)
        f_combo_split.pack(fill="both", expand=True)
        f_combo_split.grid_columnconfigure(0, weight=3)
        f_combo_split.grid_columnconfigure(1, weight=7)
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

        f_cl_box = tk.Frame(f_cl, bg=UITheme.BG_DARK)
        f_cl_box.pack(fill="both", expand=True, pady=4)
        self.combo_listbox = tk.Listbox(f_cl_box, bg=UITheme.BG_DARK, fg=UITheme.TEXT_MAIN, selectbackground=UITheme.ACCENT_BLUE, selectforeground="#fff", bd=0, highlightthickness=0, font=UITheme.FONT_NORMAL, exportselection=False)
        self.combo_listbox.pack(side="left", fill="both", expand=True)
        self.combo_listbox.bind("<<ListboxSelect>>", self.on_combo_select)
        self.combo_listbox.bind("<Double-Button-1>", self.on_combo_double_click_add) # 雙擊加入掛機流程
        sc_cl = tk.Scrollbar(f_cl_box, orient="vertical", command=self.combo_listbox.yview)
        sc_cl.pack(side="right", fill="y")
        self.combo_listbox.config(yscrollcommand=sc_cl.set)

        cr_act = tk.Frame(f_cl, bg=UITheme.BG_PANEL)
        cr_act.pack(fill="x", pady=(2, 0))
        tk.Button(cr_act, text="➔ 加入掛機流程", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, font=UITheme.FONT_NORMAL_BOLD, command=self.add_combo_to_main_steps).pack(side="left", fill="x", expand=True, padx=(0, 2))
        tk.Button(cr_act, text="✕ 刪除組合", width=9, bg=UITheme.ACCENT_RED, fg="#fff", activebackground=UITheme.ACCENT_RED_HOVER, font=UITheme.FONT_SMALL_BOLD, command=self.delete_selected_combo).pack(side="right")

        # 2-B. 組合動作 (視覺層次優化：超緊湊卡片 + 超寬敞子動作清單)
        f_cr = tk.Frame(f_combo_split, bg=UITheme.BG_PANEL, padx=6, pady=2, highlightbackground=UITheme.BORDER, highlightthickness=1)
        f_cr.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        f_cr_top = tk.Frame(f_cr, bg=UITheme.BG_PANEL)
        f_cr_top.pack(fill="x", pady=(0, 2))
        self.lbl_combo_editing = tk.Label(f_cr_top, text="【組合動作: 未選取】", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_SUB, font=UITheme.FONT_NORMAL_BOLD)
        self.lbl_combo_editing.pack(side="left")
        tk.Button(f_cr_top, text="▶ 試跑組合", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, font=UITheme.FONT_SMALL_BOLD, relief="flat", padx=6, command=self.test_run_current_combo).pack(side="right")

        # 動作建立面板 (精簡排版，節省 40px+ 垂直高度)
        f_action_card = tk.LabelFrame(f_cr, text=" 加入動作 ", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL_BOLD, padx=5, pady=2)
        f_action_card.pack(fill="x", pady=(0, 2))

        # 1. 點擊動作行 (突出主要瞄準點擊 + 手動坐標)
        r_click = tk.Frame(f_action_card, bg=UITheme.BG_PANEL)
        r_click.pack(fill="x", pady=1)
        ttk.Combobox(r_click, textvariable=self.var_combo_btn, values=["左鍵", "右鍵"], width=4, state="readonly").pack(side="left", padx=(0, 2))
        self.btn_combo_add_click = tk.Button(r_click, text="+ 瞄準點擊", bg=UITheme.ACCENT_GREEN, fg="#fff", font=UITheme.FONT_NORMAL_BOLD, activebackground=UITheme.ACCENT_GREEN_HOVER, relief="flat", padx=6, command=lambda: self.add_click_action(is_combo=True))
        self.btn_combo_add_click.pack(side="left", padx=1, fill="x", expand=True)

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
        tk.Button(f_k, text="+ 加按鍵", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", padx=4, font=UITheme.FONT_SMALL_BOLD, command=lambda: self.add_key_action(is_combo=True)).pack(side="left", fill="x", expand=True)

        f_w = tk.Frame(r_fast, bg=UITheme.BG_PANEL)
        f_w.pack(side="left", fill="x", expand=True, padx=(2, 0))
        tk.Entry(f_w, textvariable=self.var_combo_act_wait, width=4, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 2))
        tk.Button(f_w, text="+ 加停頓(s)", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", padx=4, font=UITheme.FONT_SMALL_BOLD, command=lambda: self.add_wait_action(is_combo=True)).pack(side="left", fill="x", expand=True)

        # 3. 呼叫組合與引用變數 (雙拼一行，大幅節省縱向空間)
        r_comb = tk.Frame(f_action_card, bg=UITheme.BG_PANEL)
        r_comb.pack(fill="x", pady=1)

        f_call = tk.Frame(r_comb, bg=UITheme.BG_PANEL)
        f_call.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self.cbo_call_combo = ttk.Combobox(f_call, textvariable=self.var_combo_to_call, width=10, state="readonly")
        self.cbo_call_combo.pack(side="left", fill="x", expand=True, padx=(0, 1))
        tk.Button(f_call, text="+ 呼叫", width=5, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.combo_add_call_action).pack(side="left")

        f_var = tk.Frame(r_comb, bg=UITheme.BG_PANEL)
        f_var.pack(side="left", fill="x", expand=True, padx=(2, 0))
        self.cbo_combo_add_var = ttk.Combobox(f_var, textvariable=self.var_combo_ref_var, width=10, state="readonly")
        self.cbo_combo_add_var.pack(side="left", fill="x", expand=True, padx=(0, 1))
        tk.Button(f_var, text="+ 引用變數", width=8, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.combo_add_variable_action).pack(side="left")

        # 動作清單 (高度大幅釋放)
        f_cr_box = tk.Frame(f_cr, bg=UITheme.BG_DARK)
        f_cr_box.pack(fill="both", expand=True, pady=3)

        self.combo_act_listbox = tk.Listbox(
            f_cr_box,
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

        # 底部單層全功能管理工具列 (統一佈局順序：上移/下移/試跑/修改/複製/刪除/清空)
        cr_act_ctrl = tk.Frame(f_cr, bg=UITheme.BG_PANEL)
        cr_act_ctrl.pack(fill="x", pady=(2, 1))
        tk.Button(cr_act_ctrl, text="▲ 上移", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=lambda: self.move_combo_action(-1)).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(cr_act_ctrl, text="▼ 下移", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=lambda: self.move_combo_action(1)).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(cr_act_ctrl, text="▶ 試跑", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.test_run_selected_combo_action).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(cr_act_ctrl, text="✎ 修改", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.edit_selected_combo_action).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(cr_act_ctrl, text="⎘ 複製", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.duplicate_combo_action).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(cr_act_ctrl, text="✕ 刪除", bg=UITheme.ACCENT_RED, fg="#fff", activebackground=UITheme.ACCENT_RED_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.delete_combo_action).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(cr_act_ctrl, text="✕ 清空", bg=UITheme.ACCENT_RED_DARK, fg="#fff", activebackground=UITheme.ACCENT_RED_DARK_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.clear_combo_actions).pack(side="left", padx=1, fill="x", expand=True)

    # ======================= 右欄佈局 =======================
    def build_right_panel(self):
        f_right = tk.Frame(self, bg=UITheme.BG_PANEL, padx=8, pady=8, highlightbackground=UITheme.BORDER, highlightthickness=1)
        f_right.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="nsew")

        # 1. 單一動作新增 (精簡排版，與左欄風格對齊，節省空間)
        f_step = tk.LabelFrame(f_right, text=" 單一動作 ", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_TITLE, padx=6, pady=3)
        f_step.pack(fill="x", pady=(0, 4))

        sr_click = tk.Frame(f_step, bg=UITheme.BG_PANEL)
        sr_click.pack(fill="x", pady=1)
        ttk.Combobox(sr_click, textvariable=self.var_step_btn, values=["左鍵", "右鍵"], width=4, state="readonly").pack(side="left", padx=(0, 2))
        self.btn_step_click = tk.Button(sr_click, text="+ 瞄準點擊", bg=UITheme.ACCENT_GREEN, fg="#fff", font=UITheme.FONT_NORMAL_BOLD, activebackground=UITheme.ACCENT_GREEN_HOVER, relief="flat", padx=6, command=lambda: self.add_click_action(is_combo=False))
        self.btn_step_click.pack(side="left", padx=1, fill="x", expand=True)
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
        tk.Button(f_sk, text="+ 加按鍵", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", padx=4, font=UITheme.FONT_SMALL_BOLD, command=lambda: self.add_key_action(is_combo=False)).pack(side="left", fill="x", expand=True)

        f_sw = tk.Frame(sr, bg=UITheme.BG_PANEL)
        f_sw.pack(side="left", fill="x", expand=True, padx=(2, 0))
        tk.Entry(f_sw, textvariable=self.var_step_wait, width=4, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 2))
        tk.Button(f_sw, text="+ 加停頓(s)", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", padx=4, font=UITheme.FONT_SMALL_BOLD, command=lambda: self.add_wait_action(is_combo=False)).pack(side="left", fill="x", expand=True)

        # 2. 自動循環清單（掛機流程）
        f_seq = tk.LabelFrame(f_right, text=" 掛機流程清單 ", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_TITLE, padx=6, pady=6)
        f_seq.pack(fill="both", expand=True)

        f_list_s = tk.Frame(f_seq, bg=UITheme.BG_DARK)
        f_list_s.pack(fill="both", expand=True, pady=4)

        self.step_listbox = tk.Listbox(
            f_list_s,
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

        # 底部單層全功能管理工具列 (統一佈局順序：上移/下移/試跑/修改/複製/展開/刪除/清空)
        sr2 = tk.Frame(f_seq, bg=UITheme.BG_PANEL)
        sr2.pack(fill="x", pady=(2, 0))
        tk.Button(sr2, text="▲ 上移", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=lambda: self.move_main_step(-1)).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(sr2, text="▼ 下移", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=lambda: self.move_main_step(1)).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(sr2, text="▶ 試跑", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.test_run_selected_main_step).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(sr2, text="✎ 修改", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.edit_selected_main_step).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(sr2, text="⎘ 複製", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.duplicate_main_step).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(sr2, text="[ 展開組合 ]", bg=UITheme.ACCENT_CYAN, fg="#fff", activebackground=UITheme.ACCENT_CYAN_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.unpack_main_step_combo).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(sr2, text="✕ 刪除", bg=UITheme.ACCENT_RED, fg="#fff", activebackground=UITheme.ACCENT_RED_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.delete_main_step).pack(side="left", padx=1, fill="x", expand=True)
        tk.Button(sr2, text="✕ 清空", bg=UITheme.ACCENT_RED_DARK, fg="#fff", activebackground=UITheme.ACCENT_RED_DARK_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=self.clear_main_steps).pack(side="left", padx=1, fill="x", expand=True)
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
        if running or is_testing:
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
                json.dump({"variables": variables, "combos": combos, "steps": steps}, f, ensure_ascii=False, indent=2)
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
                json.dump({"variables": variables, "combos": combos, "steps": steps}, f, ensure_ascii=False, indent=2)
            self.set_status(f"已成功儲存至 {fn}")
            self.refresh_profiles(select_name=name)
        except Exception as e:
            self.set_status(f"儲存失敗: {e}")

    def load_config(self):
        if running or is_testing:
            return self.set_status("巨集正在執行或試跑中，請先停止再載入設定檔！")
        name = self.var_profile_name.get().strip()
        if not name: return
        fn = f"{name}{CONFIG_EXT}"
        if not os.path.exists(fn): return self.set_status(f"找不到檔案：{fn}")
        try:
            with open(fn, "r", encoding="utf-8") as f:
                data = json.load(f)

            variables.clear()
            variables.update(data.get("variables", {}))
            self.refresh_variables_table()

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
        user32.EnumWindows(WNDENUMPROC(enum_proc), 0)
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

    # ======================= 變數管理邏輯 =======================
    def refresh_variables_table(self):
        """重新整理變數表格一覽與關聯下拉選單"""
        if not hasattr(self, "tree_vars"):
            return
        for item in self.tree_vars.get_children():
            self.tree_vars.delete(item)

        type_display = {"coord": "[坐標]", "key": "[按鍵]", "wait": "[停頓]"}

        for name, data in variables.items():
            t_key = data.get("type", "coord")
            t_disp = type_display.get(t_key, t_key)
            val = data.get("value")

            if t_key == "coord":
                if isinstance(val, dict):
                    v_str = f"({val.get('x', 0)}, {val.get('y', 0)})"
                else:
                    v_str = str(val)
            elif t_key == "key":
                v_str = str(val).upper()
            elif t_key == "wait":
                v_str = f"{val} 秒"
            else:
                v_str = str(val)

            self.tree_vars.insert("", "end", iid=name, values=(name, t_disp, v_str))

        var_names = list(variables.keys())
        if hasattr(self, "cbo_combo_add_var"):
            self.cbo_combo_add_var["values"] = var_names
            if var_names:
                if self.var_combo_ref_var.get() not in var_names:
                    self.cbo_combo_add_var.current(0)
            else:
                self.var_combo_ref_var.set("")

    def prompt_variable_dialog(self, edit_name=None):
        """彈出變數新增 / 修改對話框 (通用無 Emoji 標籤)"""
        is_edit = edit_name is not None
        title = f"修改變數: {edit_name}" if is_edit else "新增變數"

        orig_data = variables.get(edit_name, {}) if is_edit else {}
        orig_type = orig_data.get("type", "coord")
        orig_val = orig_data.get("value", {})

        type_display_map = {"coord": "[坐標]", "key": "[按鍵]", "wait": "[停頓]"}
        type_key_map = {"[坐標]": "coord", "[按鍵]": "key", "[停頓]": "wait", "坐標": "coord", "按鍵": "key", "停頓": "wait"}

        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.configure(bg=UITheme.BG_PANEL)
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.transient(self)
        dialog.grab_set()
        self.apply_app_icon(dialog)

        w, h = 380, 310
        self.update_idletasks()
        pos_x = self.winfo_x() + max(0, (self.winfo_width() - w) // 2)
        pos_y = self.winfo_y() + max(0, (self.winfo_height() - h) // 2)
        dialog.geometry(f"{w}x{h}+{pos_x}+{pos_y}")

        f_main = tk.Frame(dialog, bg=UITheme.BG_PANEL, padx=16, pady=12)
        f_main.pack(fill="both", expand=True)

        # 變數名稱
        r_name = tk.Frame(f_main, bg=UITheme.BG_PANEL)
        r_name.pack(fill="x", pady=(0, 8))
        tk.Label(r_name, text="變數名稱:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL_BOLD, width=8, anchor="e").pack(side="left", padx=(0, 8))
        var_name = tk.StringVar(value=edit_name if is_edit else "")
        e_name = tk.Entry(r_name, textvariable=var_name, bg=UITheme.BG_INPUT, fg="#fff", font=UITheme.FONT_NORMAL, relief="flat")
        e_name.pack(side="left", fill="x", expand=True)
        if is_edit:
            e_name.config(state="disabled", fg=UITheme.TEXT_MUTED)

        # 變數種類
        r_type = tk.Frame(f_main, bg=UITheme.BG_PANEL)
        r_type.pack(fill="x", pady=(0, 8))
        tk.Label(r_type, text="變數種類:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL_BOLD, width=8, anchor="e").pack(side="left", padx=(0, 8))
        curr_type_disp = type_display_map.get(orig_type, "[坐標]")
        var_type = tk.StringVar(value=curr_type_disp)
        cbo_type = ttk.Combobox(r_type, textvariable=var_type, values=["[坐標]", "[按鍵]", "[停頓]"], state="readonly" if not is_edit else "disabled", font=UITheme.FONT_NORMAL)
        cbo_type.pack(side="left", fill="x", expand=True)

        # 數值動態容器
        f_val_box = tk.LabelFrame(f_main, text=" 數值設定 ", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_TITLE, padx=10, pady=8)
        f_val_box.pack(fill="both", expand=True, pady=(0, 10))

        if orig_type == "coord" and isinstance(orig_val, dict):
            init_x = str(orig_val.get("x", 0))
            init_y = str(orig_val.get("y", 0))
        else:
            init_x, init_y = "0", "0"
        var_x = tk.StringVar(value=init_x)
        var_y = tk.StringVar(value=init_y)

        init_key = str(orig_val) if orig_type == "key" else "f1"
        var_key = tk.StringVar(value=init_key)

        init_wait = str(orig_val) if orig_type == "wait" else "1.0"
        var_wait = tk.StringVar(value=init_wait)

        def start_space_capture():
            dialog.grab_release()
            dialog.withdraw()
            def on_finish(rx, ry, rel):
                dialog.deiconify()
                dialog.lift()
                dialog.focus_force()
                dialog.grab_set()
                var_x.set(str(rx))
                var_y.set(str(ry))
                self.set_status(f"變數取點成功: ({rx}, {ry})")
            def on_cancel():
                dialog.deiconify()
                dialog.lift()
                dialog.focus_force()
                dialog.grab_set()
            self.capture_pos_space(on_finish, on_cancel, btn="left")

        def render_inputs():
            for child in f_val_box.winfo_children():
                child.destroy()

            selected_type_disp = var_type.get()
            selected_type = type_key_map.get(selected_type_disp, "coord")
            if selected_type == "coord":
                r_coords = tk.Frame(f_val_box, bg=UITheme.BG_PANEL)
                r_coords.pack(fill="x", pady=(2, 6))

                tk.Label(r_coords, text="X:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 4))
                e_x = tk.Entry(r_coords, textvariable=var_x, width=7, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL)
                e_x.pack(side="left", padx=(0, 12))

                tk.Label(r_coords, text="Y:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 4))
                e_y = tk.Entry(r_coords, textvariable=var_y, width=7, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL)
                e_y.pack(side="left", padx=(0, 4))

                btn_rec = tk.Button(
                    f_val_box,
                    text="◎ 瞄準取點 (Space)",
                    bg=UITheme.ACCENT_GREEN,
                    fg="#fff",
                    activebackground=UITheme.ACCENT_GREEN_HOVER,
                    font=UITheme.FONT_NORMAL_BOLD,
                    relief="flat",
                    command=start_space_capture
                )
                btn_rec.pack(fill="x", pady=(2, 2))

            elif selected_type == "key":
                r_k = tk.Frame(f_val_box, bg=UITheme.BG_PANEL)
                r_k.pack(fill="x", pady=6)
                tk.Label(r_k, text="按鍵名稱:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 8))
                e_k = tk.Entry(r_k, textvariable=var_key, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL)
                e_k.pack(side="left", fill="x", expand=True)
                tk.Label(f_val_box, text="(例: f1, 1, z, space, enter)", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL).pack(anchor="w")

            elif selected_type == "wait":
                r_w = tk.Frame(f_val_box, bg=UITheme.BG_PANEL)
                r_w.pack(fill="x", pady=6)
                tk.Label(r_w, text="停頓時間 (秒):", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 8))
                e_w = tk.Entry(r_w, textvariable=var_wait, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL)
                e_w.pack(side="left", fill="x", expand=True)
                tk.Label(f_val_box, text="(例: 0.5, 1.0, 2.5)", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL).pack(anchor="w")

        cbo_type.bind("<<ComboboxSelected>>", lambda e: render_inputs())
        render_inputs()

        # 底部確定 / 取消按鈕
        r_btns = tk.Frame(f_main, bg=UITheme.BG_PANEL)
        r_btns.pack(fill="x")

        def on_save():
            name = var_name.get().strip()
            if not name:
                messagebox.showerror("錯誤", "變數名稱不可為空！", parent=dialog)
                return
            if not is_edit and name in variables:
                messagebox.showerror("錯誤", f"變數「{name}」已存在！請使用其他名稱。", parent=dialog)
                return

            sel_type_disp = var_type.get()
            type_key = type_key_map.get(sel_type_disp, "coord")

            if type_key == "coord":
                try:
                    px = int(var_x.get().strip())
                    py = int(var_y.get().strip())
                except ValueError:
                    messagebox.showerror("錯誤", "坐標 X 與 Y 必須是整數！", parent=dialog)
                    return
                val = {"x": px, "y": py}
            elif type_key == "key":
                k = var_key.get().strip().lower()
                if not k:
                    messagebox.showerror("錯誤", "按鍵名稱不可為空！", parent=dialog)
                    return
                val = k
            elif type_key == "wait":
                try:
                    sec = float(var_wait.get().strip())
                    if sec <= 0:
                        raise ValueError
                except ValueError:
                    messagebox.showerror("錯誤", "停頓時間必須輸入大於 0 的秒數！", parent=dialog)
                    return
                val = sec
            else:
                return

            variables[name] = {"type": type_key, "value": val}
            self.trigger_hot_reload()
            self.refresh_variables_table()
            self.refresh_combo_actions_list()
            self.update_step_list()
            self.set_status(f"已儲存變數: {name}")
            dialog.destroy()

        tk.Button(
            r_btns,
            text="[ 確定儲存 ]",
            bg=UITheme.ACCENT_BLUE,
            fg="#fff",
            activebackground=UITheme.ACCENT_BLUE_HOVER,
            font=UITheme.FONT_NORMAL_BOLD,
            relief="flat",
            padx=12,
            pady=4,
            command=on_save
        ).pack(side="right", padx=(4, 0))

        tk.Button(
            r_btns,
            text="[ 取消 ]",
            bg=UITheme.BTN_GRAY,
            fg="#fff",
            activebackground=UITheme.BTN_GRAY_HOVER,
            font=UITheme.FONT_NORMAL,
            relief="flat",
            padx=12,
            pady=4,
            command=dialog.destroy
        ).pack(side="right")

        dialog.bind("<Return>", lambda e: on_save())
        dialog.bind("<Escape>", lambda e: dialog.destroy())

        if not is_edit:
            e_name.focus_set()

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
        variables.pop(var_name, None)
        self.trigger_hot_reload()
        self.refresh_variables_table()
        self.refresh_combo_actions_list()
        self.update_step_list()
        self.set_status(f"已刪除變數: {var_name}")

    def combo_add_variable_action(self):
        """將選定的變數以引用方式加入當前選取組合"""
        var_name = self.var_combo_ref_var.get().strip()
        if not var_name or var_name not in variables:
            return self.set_status("請先選擇要引用的變數")

        c_idx = self.get_selected_combo_idx()
        if c_idx is None:
            return self.set_status("請先在左邊清單選擇要加入動作的組合！")

        v_info = variables[var_name]
        v_type = v_info.get("type", "coord")
        v_val = v_info.get("value")

        if v_type == "coord":
            px = v_val.get("x", 0) if isinstance(v_val, dict) else 0
            py = v_val.get("y", 0) if isinstance(v_val, dict) else 0
            new_act = {
                "type": "click",
                "btn": "left",
                "x": px,
                "y": py,
                "rel": self.var_use_rel.get(),
                "var_name": var_name
            }
        elif v_type == "key":
            new_act = {
                "type": "key",
                "key": str(v_val),
                "var_name": var_name
            }
        elif v_type == "wait":
            try: sec = float(v_val)
            except Exception: sec = 1.0
            new_act = {
                "type": "wait",
                "sec": sec,
                "var_name": var_name
            }
        else:
            return

        self._insert_action_to_target(new_act, is_combo=True, success_msg=f"已在組合加入引用變數【{var_name}】")

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
        self.trigger_hot_reload()

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
        self.trigger_hot_reload()

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
        self.trigger_hot_reload()

    def delete_selected_combo(self):
        idx = self.get_selected_combo_idx()
        if idx is None: return
        name = combos[idx]["name"]
        del combos[idx]
        new_sel = min(idx, len(combos) - 1) if combos else None
        self.refresh_combo_list(select_idx=new_sel)
        self.on_combo_select()
        self.set_status(f"已刪除組合 [{name}]")
        self.trigger_hot_reload()

    def add_combo_to_main_steps(self):
        idx = self.get_selected_combo_idx()
        if idx is None: return self.set_status("請先在左邊選擇要加入的組合！")
        c = combos[idx]
        if not c.get("actions"): return self.set_status(f"組合 [{c['name']}] 內尚未加入任何動作！")

        ins = self.get_main_insert_index()
        steps.insert(ins, {"type": "combo", "name": c["name"], "actions": copy.deepcopy(c["actions"])})
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
        actions = combos[idx].get("actions", [])
        for i, act in enumerate(actions):
            self.combo_act_listbox.insert(tk.END, format_action_summary(act, index=i))
        if select_idx is not None and 0 <= select_idx < len(actions):
            self.combo_act_listbox.selection_set(select_idx)
            self.combo_act_listbox.see(select_idx)

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
        self.run_in_test_thread(f"組合動作 #{a_idx+1}", lambda: self.execute_single_action(act, f"組合動作#{a_idx+1}"))

    def test_run_current_combo(self):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None:
            return self.set_status("請先選擇要試跑的組合！")
        c = combos[c_idx]
        sub_actions = c.get("actions", [])
        if not sub_actions:
            return self.set_status(f"組合 [{c['name']}] 內無任何動作可試跑！")

        def _run():
            for a_idx, act in enumerate(sub_actions):
                if stop_event.is_set(): break
                self.execute_single_action(act, f"[{c['name']}#{a_idx+1}]")

        self.run_in_test_thread(f"組合 [{c['name']}]", _run)

    # ======================= 熱更新同步與清單動作輔助函數 =======================
    def trigger_hot_reload(self):
        """若巨集運行中，同步最新草稿至背景實例快照，並於下一輪自動生效"""
        global active_steps, active_combos, active_variables, reload_requested
        if running:
            with steps_lock:
                active_steps = copy.deepcopy(steps)
                active_combos = copy.deepcopy(combos)
                active_variables = copy.deepcopy(variables)
                reload_requested = True

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
            actions = combos[idx].setdefault("actions", [])
            sel = self.get_selected_action_idx()
            ins = sel + 1 if sel is not None else len(actions)
            actions.insert(ins, action_dict)
            self.refresh_combo_actions_list(select_idx=ins)
            self.refresh_combo_list(select_idx=idx)
            self.sync_combo_actions_to_main_steps(combos[idx]["name"], actions)
            if success_msg: self.set_status(success_msg)
            self.trigger_hot_reload()
            return ins
        else:
            ins = self.get_main_insert_index()
            steps.insert(ins, action_dict)
            self.update_step_list(ins)
            if success_msg: self.set_status(success_msg)
            self.trigger_hot_reload()
            return ins

    def add_click_action(self, is_combo=False):
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

        act = combos[c_idx]["actions"][a_idx]
        curr_combo_name = combos[c_idx]["name"]
        avail_combos = [c["name"] for c in combos if c["name"] != curr_combo_name]

        if self.prompt_edit_action(act, available_combos=avail_combos):
            self.refresh_combo_actions_list(select_idx=a_idx)
            self.sync_combo_actions_to_main_steps(combos[c_idx]["name"], combos[c_idx]["actions"])
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
        if target_name == combos[idx]["name"]: return self.set_status("不能在組合內呼叫自己！")
        self._insert_action_to_target({"type": "call_combo", "target_name": target_name}, is_combo=True, success_msg=f"已在組合加入呼叫: [{target_name}]")

    def move_combo_action(self, delta):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None: return self.set_status("請先在左邊清單選取一個組合！")
        a_idx = self.get_selected_action_idx()
        actions = combos[c_idx]["actions"]
        def _refresh(target):
            self.refresh_combo_actions_list(select_idx=target)
            self.sync_combo_actions_to_main_steps(combos[c_idx]["name"], actions)
        self._move_list_item(actions, a_idx, delta, _refresh, item_name="組合動作")

    def duplicate_combo_action(self):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None: return self.set_status("請先在左邊清單選取一個組合！")
        a_idx = self.get_selected_action_idx()
        actions = combos[c_idx]["actions"]
        def _refresh(target):
            self.refresh_combo_actions_list(select_idx=target)
            self.refresh_combo_list(select_idx=c_idx)
            self.sync_combo_actions_to_main_steps(combos[c_idx]["name"], actions)
        self._duplicate_list_item(actions, a_idx, _refresh, item_name="組合動作")

    def delete_combo_action(self):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None: return self.set_status("請先在左邊清單選取一個組合！")
        a_idx = self.get_selected_action_idx()
        actions = combos[c_idx]["actions"]
        def _refresh(target):
            self.refresh_combo_actions_list(select_idx=target)
            self.refresh_combo_list(select_idx=c_idx)
            self.sync_combo_actions_to_main_steps(combos[c_idx]["name"], actions)
        self._delete_list_item(actions, a_idx, _refresh, item_name="組合動作")

    def clear_combo_actions(self):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None: return
        actions = combos[c_idx].get("actions", [])
        def _refresh(_):
            self.refresh_combo_actions_list()
            self.refresh_combo_list(select_idx=c_idx)
            self.sync_combo_actions_to_main_steps(combos[c_idx]["name"], [])
        self._clear_list_items(actions, f"請問是否清空組合 [{combos[c_idx]['name']}] 的所有動作？", _refresh, "組合所有動作")

    # ======================= 自動循環清單（掛機流程）邏輯 =======================
    def get_main_insert_index(self):
        sel = self.step_listbox.curselection()
        return sel[0] + 1 if sel else len(steps)

    def update_step_list(self, select_idx=None):
        self.step_listbox.delete(0, tk.END)
        for i, s in enumerate(steps):
            self.step_listbox.insert(tk.END, format_action_summary(s, index=i))
        if select_idx is not None and 0 <= select_idx < len(steps):
            self.step_listbox.selection_set(select_idx)
            self.step_listbox.see(select_idx)

    def test_run_selected_main_step(self):
        sel = self.step_listbox.curselection()
        if not sel:
            return self.set_status("請先在清單中選擇要試跑的主步驟！")
        idx = sel[0]
        s = steps[idx]

        def _run():
            if s.get("type") == "combo":
                c_name = s.get("name", "組合")
                sub_actions = s.get("actions", [])
                if not sub_actions:
                    return self.set_status(f"組合 [{c_name}] 內無任何動作！")
                for sub_idx, sub_act in enumerate(sub_actions):
                    if stop_event.is_set(): break
                    self.execute_single_action(sub_act, f"[{c_name}#{sub_idx+1}]")
            else:
                self.execute_single_action(s, f"步驟#{idx+1}")

        self.run_in_test_thread(f"步驟 #{idx+1}", _run)

    def edit_selected_main_step(self):
        sel = self.step_listbox.curselection()
        if not sel: return self.set_status("請先在掛機流程選擇步驟！")
        idx = sel[0]
        if self.prompt_edit_action(steps[idx], step_idx=idx):
            self.update_step_list(idx)
            self.set_status(f"已成功更新主步驟 #{idx+1}")
            self.trigger_hot_reload()

    def move_main_step(self, delta):
        sel = self.step_listbox.curselection()
        idx = sel[0] if sel else None
        self._move_list_item(steps, idx, delta, self.update_step_list, item_name="主步驟")

    def duplicate_main_step(self):
        sel = self.step_listbox.curselection()
        idx = sel[0] if sel else None
        self._duplicate_list_item(steps, idx, self.update_step_list, item_name="主步驟")

    def unpack_main_step_combo(self):
        sel = self.step_listbox.curselection()
        if not sel:
            return self.set_status("請先在掛機流程選擇要展開的組合步驟！")
        idx = sel[0]
        step = steps[idx]
        if step.get("type") != "combo":
            return self.set_status("所選步驟不是組合，無法展開！")
        c_actions = step.get("actions", [])
        if not c_actions:
            return self.set_status("此組合內沒有任何動作！")
        del steps[idx]
        for offset, act in enumerate(c_actions):
            steps.insert(idx + offset, copy.deepcopy(act))
        self.update_step_list(select_idx=idx)
        self.set_status(f"已將組合 [{step.get('name', '')}] 展開為 {len(c_actions)} 個獨立步驟")
        self.trigger_hot_reload()

    def delete_main_step(self):
        sel = self.step_listbox.curselection()
        idx = sel[0] if sel else None
        self._delete_list_item(steps, idx, self.update_step_list, item_name="主步驟")

    def clear_main_steps(self):
        self._clear_list_items(steps, "請問是否清空整個掛機流程？\n清空後未儲存的內容無法還原！", self.update_step_list, "掛機流程")

    # ======================= 動作執行調度器 =======================
    def dispatch_action(self, act, parent_desc, current_vars=None, current_combos=None, depth=0, visited_set=None, is_test=False, round_prefix=""):
        if visited_set is None: visited_set = set()
        if not is_test:
            if not running or stop_event.is_set(): return False
            if current_vars is None: current_vars = {}
            if current_combos is None: current_combos = []
        else:
            if stop_event.is_set(): return False
            if current_vars is None:
                with steps_lock: current_vars = copy.deepcopy(variables)
            if current_combos is None:
                with steps_lock: current_combos = copy.deepcopy(combos)

        use_bg = getattr(self, "cached_use_bg", True) and IS_WINDOWS and (target_hwnd is not None)
        off_x = getattr(self, "cached_offset_x", 0)
        off_y = getattr(self, "cached_offset_y", 0)

        # 若在前台模式且有綁定目標視窗，自動將目標視窗置頂以確保能接收點擊與按鍵
        if not use_bg and IS_WINDOWS and target_hwnd:
            self.force_bring_window_to_front(target_hwnd)

        var_name = act.get("var_name")
        v_data = current_vars.get(var_name) if (current_vars and var_name) else None

        atype = act.get("type")
        if atype == "click":
            x, y = act["x"], act["y"]
            if v_data and v_data.get("type") == "coord":
                val = v_data.get("value", {})
                if isinstance(val, dict):
                    x, y = val.get("x", x), val.get("y", y)
            btn = act.get("btn", "left")
            msg = execute_click(x, y, act.get("rel"), use_bg, off_x, off_y, btn=btn)
            var_info = f"【{var_name}】" if var_name else ""
            self.set_status(f"{round_prefix}{parent_desc} {var_info}{msg}")
            if not safe_sleep(0.12): return False

        elif atype == "key":
            key = act["key"]
            if v_data and v_data.get("type") == "key":
                key = str(v_data.get("value", key))
            if use_bg:
                post_bg_key(target_hwnd, key)
            else:
                with currently_held_keys_lock:
                    currently_held_keys.add(("fg", key))
                try:
                    pyautogui.keyDown(key)
                    if not safe_sleep(0.06): return False
                finally:
                    try: pyautogui.keyUp(key)
                    except Exception: pass
                    with currently_held_keys_lock:
                        currently_held_keys.discard(("fg", key))
            var_info = f"【{var_name}】" if var_name else ""
            self.set_status(f"{round_prefix}{parent_desc} {var_info}按鍵 [{key.upper()}]")
            if not safe_sleep(0.10): return False

        elif atype == "wait":
            sec = float(act.get("sec", 0.5))
            if v_data and v_data.get("type") == "wait":
                try: sec = float(v_data.get("value", sec))
                except Exception: pass
            var_info = f"【{var_name}】" if var_name else ""
            self.set_status(f"{round_prefix}{parent_desc} {var_info}等待 {sec}s")
            if not safe_sleep(sec): return False

        elif atype == "call_combo":
            tgt_name = act.get("target_name")
            if not tgt_name: return True
            if depth >= 10:
                self.set_status(f"{round_prefix}呼叫 [{tgt_name}] 超過深度上限")
                return True
            if tgt_name in visited_set:
                self.set_status(f"{round_prefix}循環呼叫 [{tgt_name}]，自動跳過")
                return True

            tgt_combo = next((c for c in current_combos if c["name"] == tgt_name), None)
            if tgt_combo:
                new_visited = visited_set | {tgt_name}
                for sub_idx, sub_act in enumerate(tgt_combo.get("actions", [])):
                    if not is_test and (not running or stop_event.is_set()): return False
                    if is_test and stop_event.is_set(): return False
                    sub_desc = f"{parent_desc}->[{tgt_name}#{sub_idx+1}]"
                    if not self.dispatch_action(sub_act, sub_desc, current_vars=current_vars, current_combos=current_combos, depth=depth + 1, visited_set=new_visited, is_test=is_test, round_prefix=round_prefix):
                        return False
            else:
                self.set_status(f"{round_prefix}找不到被呼叫的組合 [{tgt_name}]")

        return True

    def execute_single_action(self, act, desc):
        self.dispatch_action(act, desc, is_test=True)

    # ======================= 主執行引擎 =======================
    def toggle_run(self):
        global running, is_testing, active_steps, active_combos, active_variables, reload_requested
        if running or is_testing:
            was_test = is_testing
            running = False
            is_testing = False
            stop_event.set()
            emergency_release_all()
            self.set_running_ui(False)
            self.set_status("試跑已手動中止！" if was_test else "已手動停止")
        else:
            if not steps: return self.set_status("執行清單是空的，請先加入步驟！")
            with steps_lock:
                active_steps = copy.deepcopy(steps)
                active_combos = copy.deepcopy(combos)
                active_variables = copy.deepcopy(variables)
                reload_requested = False
            stop_event.clear()
            running = True
            self.set_running_ui(True)
            self.set_status("循環運作中...")
            threading.Thread(target=self.macro_worker_loop, daemon=True).start()

    def macro_worker_loop(self):
        global running, reload_requested
        round_idx = 1
        try:
            while running and not stop_event.is_set():
                with steps_lock:
                    current_steps = copy.deepcopy(active_steps)
                    current_combos = copy.deepcopy(active_combos)
                    current_variables = copy.deepcopy(active_variables)
                    was_reloaded = reload_requested
                    reload_requested = False

                if was_reloaded:
                    self.set_status(f"第 {round_idx} 輪: 已套用最新熱更新流程！")

                for idx, step in enumerate(current_steps):
                    if not running or stop_event.is_set(): break

                    self.highlight_active_step(idx)
                    pfx = f"第 {round_idx} 輪: "

                    stype = step["type"]
                    if stype == "combo":
                        c_name = step.get("name", "組合")
                        for a_idx, act in enumerate(step.get("actions", [])):
                            if not running or stop_event.is_set(): break
                            self.highlight_active_step(idx, sub_idx=a_idx)
                            if not self.dispatch_action(act, f"[{c_name}#{a_idx+1}]", current_vars=current_variables, current_combos=current_combos, depth=0, visited_set={c_name}, is_test=False, round_prefix=pfx):
                                break
                    else:
                        if not self.dispatch_action(step, f"步驟#{idx+1}", current_vars=current_variables, current_combos=current_combos, depth=0, visited_set=set(), is_test=False, round_prefix=pfx):
                            break

                round_idx += 1
                if not safe_sleep(0.05):
                    break
        except Exception as e:
            self.set_status(f"異常中斷: {e}")
        finally:
            running = False
            emergency_release_all()
            self.set_running_ui(False)

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("sh.autoclicker.app.1.0")
        except Exception:
            pass
    app = App()
    app.mainloop()