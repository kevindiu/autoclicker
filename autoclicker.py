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
CONFIG_EXT = ".shm"  # 自訂專屬副檔名 (Shui Hu Macro)

combos, steps = [], []
temp_combo_target = None
running = False
stop_event = threading.Event()
target_hwnd = None

# --- Win32 API 初始化 ---
IS_WINDOWS = hasattr(ctypes, "windll")

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

VK_MAP = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "tab": 0x09, "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
    **{str(i): 0x30 + i for i in range(10)},
    **{chr(c): 0x41 + (c - ord('a')) for c in range(ord('a'), ord('z') + 1)}
}

# --- 中斷等待與後台按鍵釋放 ---
def safe_sleep(seconds):
    end = time.time() + float(seconds)
    while time.time() < end:
        if not running or stop_event.is_set():
            return False
        time.sleep(0.02)
    return True

def emergency_release_bg_only():
    if IS_WINDOWS and target_hwnd:
        try:
            user32.PostMessageW(target_hwnd, 0x0202, 0, 0)
        except Exception:
            pass

# --- 動作發送輔助器 ---
def post_bg_click(hwnd, client_x, client_y, offset_x=0, offset_y=0):
    if not IS_WINDOWS or not hwnd:
        pyautogui.click(client_x, client_y)
        return int(client_x), int(client_y)
    cx, cy = int(client_x) + offset_x, int(client_y) + offset_y
    lparam = ((int(cy) & 0xFFFF) << 16) | (int(cx) & 0xFFFF)
    user32.PostMessageW(hwnd, 0x0200, 0, lparam)
    if safe_sleep(0.02):
        try:
            user32.PostMessageW(hwnd, 0x0201, 0x0001, lparam)
            safe_sleep(0.08)
        finally:
            user32.PostMessageW(hwnd, 0x0202, 0, lparam)
    return cx, cy

def post_bg_key(hwnd, key_str):
    if not IS_WINDOWS or not hwnd:
        try:
            pyautogui.keyDown(key_str); safe_sleep(0.06)
        finally:
            try: pyautogui.keyUp(key_str)
            except Exception: pass
        return
    vk = VK_MAP.get(key_str.lower()) or (ord(key_str.upper()) if len(key_str) == 1 else None)
    if vk is not None:
        try:
            user32.PostMessageW(hwnd, 0x0100, vk, 0); safe_sleep(0.06)
        finally:
            user32.PostMessageW(hwnd, 0x0101, vk, 0xC0000001)

def execute_click(x, y, is_rel, use_bg, off_x, off_y):
    if use_bg:
        if not is_rel:
            pt = POINT(int(x), int(y))
            user32.ScreenToClient(target_hwnd, ctypes.byref(pt))
            x, y = pt.x, pt.y
        cx, cy = post_bg_click(target_hwnd, x, y, off_x, off_y)
        return f"後台點擊相對:({cx},{cy})"
    else:
        if is_rel and IS_WINDOWS and target_hwnd:
            pt = POINT(int(x), int(y))
            user32.ClientToScreen(target_hwnd, ctypes.byref(pt))
            pyautogui.click(pt.x, pt.y)
            return f"前台追蹤點擊 ({pt.x},{pt.y})"
        pyautogui.click(x, y)
        return f"前台點擊 ({x},{y})"

# ==============================================================================
# 原生 Tkinter GUI
# ==============================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("960x600")
        self.resizable(False, False)
        self.configure(bg="#15171c")
        self.attributes("-topmost", True)

        self.var_profile_name = tk.StringVar()
        self.var_use_bg = tk.BooleanVar(value=True)
        self.var_use_rel = tk.BooleanVar(value=True)
        self.var_offset_x = tk.StringVar(value="0")
        self.var_offset_y = tk.StringVar(value="0")
        self.var_combo_name = tk.StringVar(value="F4補血CD")
        self.var_combo_keys = tk.StringVar(value="f4")
        self.var_combo_wait = tk.StringVar(value="10.0")
        self.var_step_key = tk.StringVar(value="f1")
        self.var_step_wait = tk.StringVar(value="1.0")
        self.var_window = tk.StringVar(value="未偵測到視窗")

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.build_left_panel()
        self.build_right_panel()
        self.refresh_window_dropdown()
        self.refresh_profiles()

    def set_status(self, msg):
        self.after(0, lambda: self.lbl_status.config(text=f"狀態: {msg}"))

    def set_running_ui(self, is_running):
        def _u():
            if is_running:
                self.btn_toggle.config(text="停止執行", bg="#dc2626", activebackground="#b91c1c")
            else:
                self.btn_toggle.config(text="開始循環執行", bg="#16a34a", activebackground="#15803d")
        self.after(0, _u)

    def highlight_step(self, idx):
        def _hl():
            self.step_listbox.selection_clear(0, tk.END)
            if 0 <= idx < self.step_listbox.size():
                self.step_listbox.selection_set(idx)
                self.step_listbox.see(idx)
        self.after(0, _hl)

    def build_left_panel(self):
        f_left = tk.Frame(self, bg="#1c1f26", padx=8, pady=8, highlightbackground="#2d333b", highlightthickness=1)
        f_left.grid(row=0, column=0, padx=(10, 5), pady=10, sticky="nsew")

        # 1. 設定與後台
        f_cfg = tk.LabelFrame(f_left, text=" 設定與 Win32 後台綁定 ", bg="#1c1f26", fg="#38bdf8", font=("Segoe UI", 10, "bold"), padx=6, pady=6)
        f_cfg.pack(fill="x", pady=(0, 6))

        r1 = tk.Frame(f_cfg, bg="#1c1f26")
        r1.pack(fill="x", pady=2)
        tk.Label(r1, text="設定檔:", bg="#1c1f26", fg="#cbd5e1").pack(side="left")
        self.cbo_profile = ttk.Combobox(r1, textvariable=self.var_profile_name, width=15, state="readonly")
        self.cbo_profile.pack(side="left", padx=4)
        tk.Button(r1, text="載入", width=5, bg="#334155", fg="#fff", command=self.load_config).pack(side="left", padx=2)
        tk.Button(r1, text="儲存", width=5, bg="#334155", fg="#fff", command=self.save_config).pack(side="left", padx=2)
        tk.Button(r1, text="新建", width=5, bg="#0284c7", fg="#fff", activebackground="#0369a1", command=self.create_new_profile).pack(side="left", padx=2)

        r2 = tk.Frame(f_cfg, bg="#1c1f26")
        r2.pack(fill="x", pady=4)
        tk.Checkbutton(r2, text="Win32後台", variable=self.var_use_bg, bg="#1c1f26", fg="#cbd5e1", selectcolor="#1c1f26", activebackground="#1c1f26").pack(side="left")
        tk.Checkbutton(r2, text="相對坐標 (Relative)", variable=self.var_use_rel, bg="#1c1f26", fg="#cbd5e1", selectcolor="#1c1f26", activebackground="#1c1f26").pack(side="left", padx=4)
        tk.Label(r2, text="微調X:", bg="#1c1f26", fg="#cbd5e1").pack(side="left")
        tk.Entry(r2, textvariable=self.var_offset_x, width=4, bg="#2d333b", fg="#ffffff").pack(side="left", padx=2)
        tk.Label(r2, text="Y:", bg="#1c1f26", fg="#cbd5e1").pack(side="left")
        tk.Entry(r2, textvariable=self.var_offset_y, width=4, bg="#2d333b", fg="#ffffff").pack(side="left", padx=2)

        r3 = tk.Frame(f_cfg, bg="#1c1f26")
        r3.pack(fill="x", pady=2)
        tk.Label(r3, text="目標視窗:", bg="#1c1f26", fg="#cbd5e1").pack(side="left")
        self.cbo_window = ttk.Combobox(r3, textvariable=self.var_window, width=28, state="readonly")
        self.cbo_window.pack(side="left", padx=4)
        self.cbo_window.bind("<<ComboboxSelected>>", self.on_window_select)
        tk.Button(r3, text="重新整理", bg="#334155", fg="#fff", command=self.refresh_window_dropdown).pack(side="left", padx=2)

        # 2. 組合庫
        f_combo = tk.LabelFrame(f_left, text=" 技能組合預設 (Combinations) ", bg="#1c1f26", fg="#38bdf8", font=("Segoe UI", 10, "bold"), padx=6, pady=6)
        f_combo.pack(fill="both", expand=True)

        cr1 = tk.Frame(f_combo, bg="#1c1f26")
        cr1.pack(fill="x", pady=2)
        tk.Label(cr1, text="名稱:", bg="#1c1f26", fg="#cbd5e1").pack(side="left")
        tk.Entry(cr1, textvariable=self.var_combo_name, width=12, bg="#2d333b", fg="#fff").pack(side="left", padx=3)
        tk.Label(cr1, text="按鍵:", bg="#1c1f26", fg="#cbd5e1").pack(side="left")
        tk.Entry(cr1, textvariable=self.var_combo_keys, width=8, bg="#2d333b", fg="#fff").pack(side="left", padx=3)
        tk.Label(cr1, text="CD(秒):", bg="#1c1f26", fg="#cbd5e1").pack(side="left")
        tk.Entry(cr1, textvariable=self.var_combo_wait, width=5, bg="#2d333b", fg="#fff").pack(side="left", padx=3)

        cr2 = tk.Frame(f_combo, bg="#1c1f26")
        cr2.pack(fill="x", pady=4)
        tk.Label(cr2, text="目標:", bg="#1c1f26", fg="#cbd5e1").pack(side="left")
        self.lbl_combo_target = tk.Label(cr2, text="無 (原地)", bg="#1c1f26", fg="#7dd3fc", font=("Segoe UI", 9, "bold"))
        self.lbl_combo_target.pack(side="left", padx=4)
        self.btn_combo_target = tk.Button(cr2, text="記錄目標 (3秒)", bg="#334155", fg="#fff", command=self.record_combo_target)
        self.btn_combo_target.pack(side="left", padx=2)
        tk.Button(cr2, text="清除", bg="#334155", fg="#fff", command=self.clear_combo_target).pack(side="left", padx=2)
        tk.Button(cr2, text="新增", bg="#334155", fg="#fff", command=self.save_new_combo).pack(side="left", padx=2)
        tk.Button(cr2, text="更新", bg="#334155", fg="#fff", command=self.update_selected_combo).pack(side="left", padx=2)

        f_list_c = tk.Frame(f_combo, bg="#15171c")
        f_list_c.pack(fill="both", expand=True, pady=4)
        self.combo_listbox = tk.Listbox(f_list_c, bg="#15171c", fg="#f1f5f9", selectbackground="#0284c7", selectforeground="#fff", bd=0, highlightthickness=0, font=("Segoe UI", 10), exportselection=False)
        self.combo_listbox.pack(side="left", fill="both", expand=True)
        self.combo_listbox.bind("<<ListboxSelect>>", self.on_combo_select)
        sc1 = tk.Scrollbar(f_list_c, orient="vertical", command=self.combo_listbox.yview)
        sc1.pack(side="right", fill="y")
        self.combo_listbox.config(yscrollcommand=sc1.set)

        cr3 = tk.Frame(f_combo, bg="#1c1f26")
        cr3.pack(fill="x", pady=(2, 0))
        tk.Button(cr3, text="將所選組合加入執行清單", bg="#0284c7", fg="#fff", activebackground="#0369a1", command=self.add_combo_to_steps).pack(side="left", fill="x", expand=True, padx=(0, 4))
        tk.Button(cr3, text="刪除組合", width=10, bg="#b91c1c", fg="#fff", activebackground="#991b1b", command=self.delete_selected_combo).pack(side="right")

    def build_right_panel(self):
        f_right = tk.Frame(self, bg="#1c1f26", padx=8, pady=8, highlightbackground="#2d333b", highlightthickness=1)
        f_right.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="nsew")

        # 1. 微步
        f_step = tk.LabelFrame(f_right, text=" 單獨新增微步 (點擊 / 按鍵 / 停頓) ", bg="#1c1f26", fg="#38bdf8", font=("Segoe UI", 10, "bold"), padx=6, pady=6)
        f_step.pack(fill="x", pady=(0, 6))

        self.btn_step_click = tk.Button(f_step, text="記錄點擊坐標 (3秒)", bg="#334155", fg="#fff", command=self.add_click_step)
        self.btn_step_click.pack(fill="x", pady=2)

        sr = tk.Frame(f_step, bg="#1c1f26")
        sr.pack(fill="x", pady=2)
        tk.Label(sr, text="按鍵:", bg="#1c1f26", fg="#cbd5e1").pack(side="left")
        tk.Entry(sr, textvariable=self.var_step_key, width=6, bg="#2d333b", fg="#fff").pack(side="left", padx=3)
        tk.Button(sr, text="加按鍵", bg="#334155", fg="#fff", command=self.add_key_step).pack(side="left", padx=2)

        tk.Label(sr, text="停頓:", bg="#1c1f26", fg="#cbd5e1").pack(side="left", padx=(10, 0))
        tk.Entry(sr, textvariable=self.var_step_wait, width=5, bg="#2d333b", fg="#fff").pack(side="left", padx=3)
        tk.Button(sr, text="加停頓", bg="#334155", fg="#fff", command=self.add_wait_step).pack(side="left", padx=2)

        # 2. 執行順序清單
        f_seq = tk.LabelFrame(f_right, text=" 執行順序清單 (由上至下循環) ", bg="#1c1f26", fg="#38bdf8", font=("Segoe UI", 10, "bold"), padx=6, pady=6)
        f_seq.pack(fill="both", expand=True)

        f_list_s = tk.Frame(f_seq, bg="#15171c")
        f_list_s.pack(fill="both", expand=True, pady=4)
        self.step_listbox = tk.Listbox(f_list_s, bg="#15171c", fg="#f1f5f9", selectbackground="#0284c7", selectforeground="#fff", bd=0, highlightthickness=0, font=("Segoe UI", 10), exportselection=False)
        self.step_listbox.pack(side="left", fill="both", expand=True)
        sc2 = tk.Scrollbar(f_list_s, orient="vertical", command=self.step_listbox.yview)
        sc2.pack(side="right", fill="y")
        self.step_listbox.config(yscrollcommand=sc2.set)

        # 控制按鈕列：加入「複製所選」
        sr2 = tk.Frame(f_seq, bg="#1c1f26")
        sr2.pack(fill="x", pady=(2, 0))
        tk.Button(sr2, text="上移", width=6, bg="#334155", fg="#fff", command=lambda: self.move_step(-1)).pack(side="left", padx=2)
        tk.Button(sr2, text="下移", width=6, bg="#334155", fg="#fff", command=lambda: self.move_step(1)).pack(side="left", padx=2)
        tk.Button(sr2, text="複製所選", width=8, bg="#0284c7", fg="#fff", activebackground="#0369a1", command=self.duplicate_selected).pack(side="left", padx=2)
        tk.Button(sr2, text="刪除所選", width=8, bg="#b91c1c", fg="#fff", command=self.delete_selected).pack(side="left", padx=2)
        tk.Button(sr2, text="清空清單", width=8, bg="#b91c1c", fg="#fff", command=self.clear_all).pack(side="left", padx=2)

        # 3. 狀態與主執行開關
        bot = tk.Frame(f_right, bg="#1c1f26")
        bot.pack(fill="x", pady=(6, 0))
        self.lbl_status = tk.Label(bot, text="狀態: 已就緒", anchor="w", bg="#1c1f26", fg="#f1f5f9", font=("Segoe UI", 9))
        self.lbl_status.pack(fill="x", pady=(0, 4))
        self.btn_toggle = tk.Button(bot, text="開始循環執行", height=2, bg="#16a34a", fg="#ffffff", font=("Segoe UI", 11, "bold"), activebackground="#15803d", command=self.toggle_run)
        self.btn_toggle.pack(fill="x")

    # ======================= 設定檔管理 =======================
    def get_profile_files(self):
        try:
            files = [f[:-len(CONFIG_EXT)] for f in os.listdir(".") if f.endswith(CONFIG_EXT)]
            return sorted(files)
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
        if not name: return
        name = name.strip()
        if not name: return

        fn = f"{name}{CONFIG_EXT}"
        if os.path.exists(fn):
            confirmed = messagebox.askyesno("檔案覆蓋確認", f"設定檔「{name}」已存在！\n請問是否確認覆蓋原有設定？", parent=self)
            if not confirmed: return

        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump({"combos": combos, "steps": steps}, f, ensure_ascii=False, indent=2)
            self.refresh_profiles(select_name=name)
            self.set_status(f"已新建並儲存至 {fn}")
        except Exception as e:
            self.set_status(f"新建失敗: {e}")

    def save_config(self):
        name = self.var_profile_name.get().strip()
        if not name:
            self.set_status("請先選擇或新建設定檔")
            return
        fn = f"{name}{CONFIG_EXT}"

        if os.path.exists(fn):
            confirmed = messagebox.askyesno("檔案覆蓋確認", f"請問是否確認覆蓋「{name}」的原有設定？", parent=self)
            if not confirmed:
                self.set_status("已取消儲存")
                return

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
        if not os.path.exists(fn):
            self.set_status(f"找不到檔案：{fn}")
            return
        try:
            with open(fn, "r", encoding="utf-8") as f: data = json.load(f)
            combos.clear(); combos.extend(data.get("combos", []) if isinstance(data, dict) else [])
            steps.clear(); steps.extend(data.get("steps", []) if isinstance(data, dict) else (data if isinstance(data, list) else []))
            self.update_combo_list()
            self.update_step_list()
            self.set_status(f"成功載入設定檔：{name}")
        except Exception as e:
            self.set_status(f"載入失敗: {e}")

    # ======================= 邏輯控制 =======================
    def get_window_list(self):
        if not IS_WINDOWS: return []
        windows = []
        def enum_proc(hwnd, lParam):
            if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
                buff = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
                user32.GetWindowTextW(hwnd, buff, len(buff))
                t = buff.value.strip()
                if t and WINDOW_TITLE not in t:
                    windows.append((hwnd, t))
            return True
        user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)(enum_proc), 0)
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

    def capture_pos_countdown(self, btn, on_finish):
        def worker():
            btn.config(state="disabled")
            for i in range(3, 0, -1):
                self.set_status(f"請移至目標點... 倒數 {i} 秒")
                time.sleep(1)
            pos = pyautogui.position()
            use_rel = self.var_use_rel.get()
            if use_rel and IS_WINDOWS and target_hwnd:
                pt = POINT(int(pos.x), int(pos.y))
                user32.ScreenToClient(target_hwnd, ctypes.byref(pt))
                x, y, rel = pt.x, pt.y, True
            else:
                x, y, rel = pos.x, pos.y, False
            on_finish(x, y, rel)
            btn.config(state="normal")
        threading.Thread(target=worker, daemon=True).start()

    def record_combo_target(self):
        def cb(x, y, rel):
            global temp_combo_target
            temp_combo_target = {"x": x, "y": y, "rel": rel}
            prefix = "相對" if rel else "絕對"
            self.lbl_combo_target.config(text=f"{prefix}:({x}, {y})")
            self.set_status(f"已鎖定組合{prefix}目標：({x}, {y})")
        self.capture_pos_countdown(self.btn_combo_target, cb)

    def clear_combo_target(self):
        global temp_combo_target
        temp_combo_target = None
        self.lbl_combo_target.config(text="無 (原地)")
        self.set_status("已清除目標坐標")

    def update_combo_list(self, select_idx=None):
        self.combo_listbox.delete(0, tk.END)
        for c in combos:
            t = c.get("target")
            t_tag = f" [{'相對' if t.get('rel') else '絕對'}目標]" if t else ""
            self.combo_listbox.insert(tk.END, f"{c['name']} ({','.join(c.get('keys', [])).upper()} / {c['wait']}s){t_tag}")
        if select_idx is not None and 0 <= select_idx < len(combos):
            self.combo_listbox.selection_set(select_idx)

    def on_combo_select(self, event=None):
        sel = self.combo_listbox.curselection()
        if not sel: return
        c = combos[sel[0]]
        self.var_combo_name.set(c["name"])
        self.var_combo_keys.set(",".join(c["keys"]))
        self.var_combo_wait.set(str(c["wait"]))
        global temp_combo_target
        temp_combo_target = c.get("target")
        prefix = ("相對:" if temp_combo_target.get("rel") else "絕對:") if temp_combo_target else ""
        self.lbl_combo_target.config(text=f"{prefix}({temp_combo_target['x']}, {temp_combo_target['y']})" if temp_combo_target else "無 (原地)")

    def save_new_combo(self):
        name = self.var_combo_name.get().strip()
        keys = [k.strip().lower() for k in self.var_combo_keys.get().replace("，", ",").split(",") if k.strip()]
        try: wait_sec = max(0.0, float(self.var_combo_wait.get()))
        except ValueError: return self.set_status("CD等待時間格式錯誤！")
        if not name or not keys: return self.set_status("請輸入組合名稱與按鍵！")

        combos.append({"name": name, "keys": keys, "wait": wait_sec, "target": dict(temp_combo_target) if temp_combo_target else None})
        self.update_combo_list(len(combos)-1)
        self.set_status(f"已建立新組合：[{name}]")

    def update_selected_combo(self):
        sel = self.combo_listbox.curselection()
        if not sel: return self.set_status("請先在清單點選要修改的組合！")
        idx = sel[0]
        old_name = combos[idx]["name"]
        name = self.var_combo_name.get().strip()
        keys = [k.strip().lower() for k in self.var_combo_keys.get().replace("，", ",").split(",") if k.strip()]
        try: wait_sec = max(0.0, float(self.var_combo_wait.get()))
        except ValueError: return

        new_target = dict(temp_combo_target) if temp_combo_target else None
        combos[idx] = {"name": name, "keys": keys, "wait": wait_sec, "target": new_target}
        self.update_combo_list(idx)

        sync_count = 0
        for s in steps:
            if s.get("type") == "combo" and s.get("name") == old_name:
                s.update({"name": name, "keys": list(keys), "wait": wait_sec, "target": dict(new_target) if new_target else None})
                sync_count += 1
        if sync_count > 0: self.update_step_list()
        self.set_status(f"已更新組合 [{name}]，並同步刷新清單內 {sync_count} 個步驟！")

    def delete_selected_combo(self):
        sel = self.combo_listbox.curselection()
        if sel:
            del combos[sel[0]]
            self.update_combo_list()
            self.set_status("已刪除該組合 (執行清單保留原有步驟)")

    def get_insert_index(self):
        sel = self.step_listbox.curselection()
        return sel[0] + 1 if sel else len(steps)

    def build_display_list(self):
        items = []
        for i, s in enumerate(steps):
            t = s.get("target")
            t_str = f"[{'相對:' if t.get('rel') else '絕對:'}({t['x']},{t['y']})] " if t else ""
            if s["type"] == "click": items.append(f"#{i+1:02d}  [點擊] -> {'相對:' if s.get('rel') else '絕對:'}({s['x']}, {s['y']})")
            elif s["type"] == "key": items.append(f"#{i+1:02d}  [按鍵] -> [ {s['key'].upper()} ]")
            elif s["type"] == "wait": items.append(f"#{i+1:02d}  [停頓] -> {s['sec']} 秒")
            elif s["type"] == "combo": items.append(f"#{i+1:02d}  [{s['name']}] {t_str}[{','.join(s.get('keys', [])).upper()}] [CD:{s['wait']}s]")
        return items

    def update_step_list(self, select_idx=None):
        self.step_listbox.delete(0, tk.END)
        for it in self.build_display_list():
            self.step_listbox.insert(tk.END, it)
        if select_idx is not None and 0 <= select_idx < len(steps):
            self.step_listbox.selection_set(select_idx)

    def add_combo_to_steps(self):
        sel = self.combo_listbox.curselection()
        c = combos[sel[0]] if sel else None
        if not c:
            name = self.var_combo_name.get().strip()
            keys = [k.strip().lower() for k in self.var_combo_keys.get().replace("，", ",").split(",") if k.strip()]
            if name and keys: c = {"name": name, "keys": keys, "wait": float(self.var_combo_wait.get() or 1.0), "target": temp_combo_target}
        if not c: return self.set_status("請先選擇或填寫組合內容！")

        ins = self.get_insert_index()
        steps.insert(ins, {"type": "combo", "name": c["name"], "keys": list(c["keys"]), "wait": c["wait"], "target": dict(c["target"]) if c.get("target") else None})
        self.update_step_list(ins)
        self.set_status(f"已加入清單 #{ins+1}: [{c['name']}]")

    def add_click_step(self):
        ins = self.get_insert_index()
        def cb(x, y, rel):
            steps.insert(ins, {"type": "click", "x": x, "y": y, "rel": rel})
            self.update_step_list(ins)
            self.set_status(f"已插入{'相對' if rel else '絕對'}點擊到 #{ins+1}：({x}, {y})")
        self.capture_pos_countdown(self.btn_step_click, cb)

    def add_key_step(self):
        key = self.var_step_key.get().strip().lower()
        if not key: return
        ins = self.get_insert_index()
        steps.insert(ins, {"type": "key", "key": key})
        self.update_step_list(ins)
        self.set_status(f"已插入按鍵到 #{ins+1}：[{key.upper()}]")

    def add_wait_step(self):
        try: sec = float(self.var_step_wait.get())
        except ValueError: return
        if sec <= 0: return
        ins = self.get_insert_index()
        steps.insert(ins, {"type": "wait", "sec": sec})
        self.update_step_list(ins)
        self.set_status(f"已插入等待到 #{ins+1}：{sec} 秒")

    def move_step(self, delta):
        sel = self.step_listbox.curselection()
        if sel and 0 <= sel[0] + delta < len(steps):
            idx = sel[0]
            steps[idx], steps[idx + delta] = steps[idx + delta], steps[idx]
            self.update_step_list(idx + delta)

    # 核心新增：複製所選步驟 (Duplicate)
    def duplicate_selected(self):
        sel = self.step_listbox.curselection()
        if not sel:
            self.set_status("請先在清單點選要複製的步驟！")
            return
        idx = sel[0]
        # 深層複製選中的步驟物件，避免共享參照
        new_step = copy.deepcopy(steps[idx])
        ins = idx + 1
        steps.insert(ins, new_step)
        self.update_step_list(ins)
        self.set_status(f"已複製步驟 #{idx+1} 到 #{ins+1}")

    def delete_selected(self):
        sel = self.step_listbox.curselection()
        if sel:
            idx = sel[0]
            del steps[idx]
            self.update_step_list(min(idx, len(steps) - 1) if steps else None)

    def clear_all(self):
        if not steps:
            self.set_status("執行清單本來就是空的")
            return

        confirmed = messagebox.askyesno(
            "清空清單確認",
            "請問是否確認要清空整個執行順序清單？\n清空後未儲存的步驟將無法還原！",
            parent=self
        )
        if confirmed:
            steps.clear()
            self.update_step_list()
            self.set_status("已清空執行清單")
        else:
            self.set_status("已取消清空清單")

    def toggle_run(self):
        global running
        if running:
            running = False
            stop_event.set()
            emergency_release_bg_only()
            self.set_running_ui(False)
            self.set_status("已手動停止")
        else:
            if not steps: return self.set_status("執行清單是空的，請先加入步驟！")
            stop_event.clear()
            running = True
            self.set_running_ui(True)
            self.set_status("循環運作中...")
            threading.Thread(target=self.macro_worker_loop, daemon=True).start()

    def macro_worker_loop(self):
        global running
        round_idx = 1
        try:
            while running and not stop_event.is_set():
                use_bg = self.var_use_bg.get() and IS_WINDOWS and (target_hwnd is not None)
                try: off_x, off_y = int(self.var_offset_x.get() or 0), int(self.var_offset_y.get() or 0)
                except Exception: off_x, off_y = 0, 0

                for idx, step in enumerate(steps):
                    if not running or stop_event.is_set(): break
                    self.highlight_step(idx)

                    stype = step["type"]
                    if stype == "click":
                        msg = execute_click(step["x"], step["y"], step.get("rel"), use_bg, off_x, off_y)
                        self.set_status(f"第 {round_idx} 輪 ({idx+1}/{len(steps)}): {msg}")
                        if not safe_sleep(0.12): break

                    elif stype == "key":
                        post_bg_key(target_hwnd, step["key"]) if use_bg else (pyautogui.keyDown(step["key"]), safe_sleep(0.06), pyautogui.keyUp(step["key"]))
                        self.set_status(f"第 {round_idx} 輪 ({idx+1}/{len(steps)}): 按鍵 [{step['key'].upper()}]")
                        if not safe_sleep(0.10): break

                    elif stype == "wait":
                        if not safe_sleep(float(step["sec"])): break

                    elif stype == "combo":
                        if step.get("target"):
                            msg = execute_click(step["target"]["x"], step["target"]["y"], step["target"].get("rel"), use_bg, off_x, off_y)
                            self.set_status(f"第 {round_idx} 輪: 組合[{step['name']}] {msg}")
                            if not safe_sleep(0.12): break

                        for k in step.get("keys", []):
                            if not running or stop_event.is_set(): break
                            post_bg_key(target_hwnd, k) if use_bg else (pyautogui.keyDown(k), safe_sleep(0.06), pyautogui.keyUp(k))
                            if not safe_sleep(0.12): break

                        if not running or stop_event.is_set(): break
                        cd = float(step.get("wait", 0))
                        if cd > 0 and not safe_sleep(cd): break

                round_idx += 1
                if not safe_sleep(0.05): break
        except Exception as e:
            self.set_status(f"異常中斷: {e}")
        finally:
            running = False
            emergency_release_bg_only()
            self.set_running_ui(False)

if __name__ == "__main__":
    app = App()
    app.mainloop()