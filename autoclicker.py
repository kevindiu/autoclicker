import os
import json
import time
import ctypes
from ctypes import wintypes
import threading
import pyautogui
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk

# --- 基礎配置 ---
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

WINDOW_TITLE = "水滸歷險 巨集助手"

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

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
            user32.PostMessageW(target_hwnd, 0x0202, 0, 0)  # WM_LBUTTONUP
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
# 主 GUI 介面類別 (CustomTkinter)
# ==============================================================================
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("960x600")
        self.resizable(False, False)
        self.attributes("-topmost", True)

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.build_left_panel()
        self.build_right_panel()

        self.refresh_window_dropdown()

    # --- 執行安全 UI 更新（線程安全分發） ---
    def set_status(self, msg):
        self.after(0, lambda: self.lbl_status.configure(text=f"狀態: {msg}"))

    def set_running_ui(self, is_running):
        def _update():
            if is_running:
                self.btn_toggle.configure(text="停止執行", fg_color="#dc2626", hover_color="#b91c1c")
            else:
                self.btn_toggle.configure(text="開始循環執行", fg_color="#16a34a", hover_color="#15803d")
        self.after(0, _update)

    def highlight_step(self, idx):
        def _hl():
            self.step_listbox.selection_clear(0, tk.END)
            if 0 <= idx < self.step_listbox.size():
                self.step_listbox.selection_set(idx)
                self.step_listbox.see(idx)
        self.after(0, _hl)

    # ======================= 左欄佈局 =======================
    def build_left_panel(self):
        left_frame = ctk.CTkFrame(self, corner_radius=8)
        left_frame.grid(row=0, column=0, padx=(10, 5), pady=10, sticky="nsew")

        # 1. 設定檔與 Win32 視窗綁定
        cfg_box = ctk.CTkFrame(left_frame, corner_radius=6)
        cfg_box.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(cfg_box, text="設定與 Win32 後台綁定", font=ctk.CTkFont(size=13, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=10, pady=(6, 2))

        # 存取檔行
        r1 = ctk.CTkFrame(cfg_box, fg_color="transparent")
        r1.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(r1, text="設定檔:").pack(side="left")
        self.ent_cfg_name = ctk.CTkEntry(r1, width=190)
        self.ent_cfg_name.insert(0, "sh_macro.json")
        self.ent_cfg_name.pack(side="left", padx=5)
        ctk.CTkButton(r1, text="儲存", width=60, command=self.save_config).pack(side="left", padx=2)
        ctk.CTkButton(r1, text="載入", width=60, command=self.load_config).pack(side="left", padx=2)

        # 模式勾選與微調
        r2 = ctk.CTkFrame(cfg_box, fg_color="transparent")
        r2.pack(fill="x", padx=10, pady=4)
        self.chk_use_bg = ctk.CTkCheckBox(r2, text="Win32後台")
        self.chk_use_bg.select()
        self.chk_use_bg.pack(side="left", padx=(0, 5))

        self.chk_use_rel = ctk.CTkCheckBox(r2, text="相對坐標 (Relative)")
        self.chk_use_rel.select()
        self.chk_use_rel.pack(side="left", padx=5)

        ctk.CTkLabel(r2, text="微調X:").pack(side="left", padx=(5, 2))
        self.ent_offset_x = ctk.CTkEntry(r2, width=35)
        self.ent_offset_x.insert(0, "0")
        self.ent_offset_x.pack(side="left")

        ctk.CTkLabel(r2, text="Y:").pack(side="left", padx=(5, 2))
        self.ent_offset_y = ctk.CTkEntry(r2, width=35)
        self.ent_offset_y.insert(0, "0")
        self.ent_offset_y.pack(side="left")

        # 目標視窗
        r3 = ctk.CTkFrame(cfg_box, fg_color="transparent")
        r3.pack(fill="x", padx=10, pady=(2, 8))
        ctk.CTkLabel(r3, text="目標視窗:").pack(side="left")
        self.cbo_window = ctk.CTkOptionMenu(r3, width=250, values=["未偵測到視窗"], command=self.on_window_select)
        self.cbo_window.pack(side="left", padx=5)
        ctk.CTkButton(r3, text="重新整理", width=70, command=self.refresh_window_dropdown).pack(side="left", padx=2)

        # 2. 技能組合預設 (Combinations)
        combo_box = ctk.CTkFrame(left_frame, corner_radius=6)
        combo_box.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        ctk.CTkLabel(combo_box, text="技能組合預設 (Combinations)", font=ctk.CTkFont(size=13, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=10, pady=(6, 2))

        # 組合輸入
        cr1 = ctk.CTkFrame(combo_box, fg_color="transparent")
        cr1.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(cr1, text="名稱:").pack(side="left")
        self.ent_combo_name = ctk.CTkEntry(cr1, width=120)
        self.ent_combo_name.insert(0, "F4補血CD")
        self.ent_combo_name.pack(side="left", padx=4)

        ctk.CTkLabel(cr1, text="按鍵:").pack(side="left", padx=(4, 0))
        self.ent_combo_keys = ctk.CTkEntry(cr1, width=80)
        self.ent_combo_keys.insert(0, "f4")
        self.ent_combo_keys.pack(side="left", padx=4)

        ctk.CTkLabel(cr1, text="CD(秒):").pack(side="left", padx=(4, 0))
        self.ent_combo_wait = ctk.CTkEntry(cr1, width=45)
        self.ent_combo_wait.insert(0, "10.0")
        self.ent_combo_wait.pack(side="left", padx=4)

        # 目標坐標行
        cr2 = ctk.CTkFrame(combo_box, fg_color="transparent")
        cr2.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(cr2, text="目標:").pack(side="left")
        self.lbl_combo_target = ctk.CTkLabel(cr2, text="無 (原地)", text_color="#7dd3fc", font=ctk.CTkFont(weight="bold"))
        self.lbl_combo_target.pack(side="left", padx=4)

        self.btn_combo_target = ctk.CTkButton(cr2, text="記錄目標 (3秒)", width=105, command=self.record_combo_target)
        self.btn_combo_target.pack(side="left", padx=3)
        ctk.CTkButton(cr2, text="清除", width=45, command=self.clear_combo_target).pack(side="left", padx=2)
        ctk.CTkButton(cr2, text="新增組合", width=68, command=self.save_new_combo).pack(side="left", padx=2)
        ctk.CTkButton(cr2, text="更新", width=50, command=self.update_selected_combo).pack(side="left", padx=2)

        # 組合 Listbox
        list_container = ctk.CTkFrame(combo_box, fg_color="#181a1f", corner_radius=4)
        list_container.pack(fill="both", expand=True, padx=10, pady=5)

        self.combo_listbox = tk.Listbox(
            list_container,
            bg="#1c1f26",
            fg="#f1f5f9",
            selectbackground="#0284c7",
            selectforeground="#ffffff",
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 10),
            exportselection=False
        )
        self.combo_listbox.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        self.combo_listbox.bind("<<ListboxSelect>>", self.on_combo_select)

        c_scroll = ttk.Scrollbar(list_container, orient="vertical", command=self.combo_listbox.yview)
        c_scroll.pack(side="right", fill="y")
        self.combo_listbox.configure(yscrollcommand=c_scroll.set)

        # 組合操作按鈕
        cr3 = ctk.CTkFrame(combo_box, fg_color="transparent")
        cr3.pack(fill="x", padx=10, pady=(2, 8))
        ctk.CTkButton(cr3, text="將所選組合加入執行清單", fg_color="#0284c7", hover_color="#0369a1", command=self.add_combo_to_steps).pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(cr3, text="刪除組合", width=80, fg_color="#b91c1c", hover_color="#991b1b", command=self.delete_selected_combo).pack(side="right")

    # ======================= 右欄佈局 =======================
    def build_right_panel(self):
        right_frame = ctk.CTkFrame(self, corner_radius=8)
        right_frame.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="nsew")

        # 1. 單獨新增微步
        step_box = ctk.CTkFrame(right_frame, corner_radius=6)
        step_box.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(step_box, text="單獨新增微步 (點擊 / 按鍵 / 停頓)", font=ctk.CTkFont(size=13, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=10, pady=(6, 2))

        self.btn_step_click = ctk.CTkButton(step_box, text="記錄點擊坐標 (3秒)", command=self.add_click_step)
        self.btn_step_click.pack(fill="x", padx=10, pady=3)

        sr = ctk.CTkFrame(step_box, fg_color="transparent")
        sr.pack(fill="x", padx=10, pady=(2, 6))
        ctk.CTkLabel(sr, text="按鍵:").pack(side="left")
        self.ent_key = ctk.CTkEntry(sr, width=65)
        self.ent_key.insert(0, "f1")
        self.ent_key.pack(side="left", padx=4)
        ctk.CTkButton(sr, text="加按鍵", width=75, command=self.add_key_step).pack(side="left", padx=2)

        ctk.CTkLabel(sr, text="停頓:").pack(side="left", padx=(10, 0))
        self.ent_wait = ctk.CTkEntry(sr, width=45)
        self.ent_wait.insert(0, "1.0")
        self.ent_wait.pack(side="left", padx=4)
        ctk.CTkButton(sr, text="加停頓", width=75, command=self.add_wait_step).pack(side="left", padx=2)

        # 2. 執行順序清單
        seq_box = ctk.CTkFrame(right_frame, corner_radius=6)
        seq_box.pack(fill="both", expand=True, padx=10, pady=5)

        ctk.CTkLabel(seq_box, text="執行順序清單 (由上至下循環)", font=ctk.CTkFont(size=13, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=10, pady=(6, 2))

        list_container2 = ctk.CTkFrame(seq_box, fg_color="#181a1f", corner_radius=4)
        list_container2.pack(fill="both", expand=True, padx=10, pady=5)

        self.step_listbox = tk.Listbox(
            list_container2,
            bg="#1c1f26",
            fg="#f1f5f9",
            selectbackground="#0284c7",
            selectforeground="#ffffff",
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 10),
            exportselection=False
        )
        self.step_listbox.pack(side="left", fill="both", expand=True, padx=2, pady=2)

        s_scroll = ttk.Scrollbar(list_container2, orient="vertical", command=self.step_listbox.yview)
        s_scroll.pack(side="right", fill="y")
        self.step_listbox.configure(yscrollcommand=s_scroll.set)

        # 清單控制按鈕
        cr4 = ctk.CTkFrame(seq_box, fg_color="transparent")
        cr4.pack(fill="x", padx=10, pady=(2, 8))
        ctk.CTkButton(cr4, text="上移", width=85, command=lambda: self.move_step(-1)).pack(side="left", padx=2)
        ctk.CTkButton(cr4, text="下移", width=85, command=lambda: self.move_step(1)).pack(side="left", padx=2)
        ctk.CTkButton(cr4, text="刪除所選", width=95, fg_color="#b91c1c", hover_color="#991b1b", command=self.delete_selected).pack(side="left", padx=2)
        ctk.CTkButton(cr4, text="清空清單", width=95, fg_color="#b91c1c", hover_color="#991b1b", command=self.clear_all).pack(side="left", padx=2)

        # 3. 狀態與主開關
        bot_box = ctk.CTkFrame(right_frame, fg_color="transparent")
        bot_box.pack(fill="x", padx=10, pady=(2, 10))

        self.lbl_status = ctk.CTkLabel(bot_box, text="狀態: 已就緒", anchor="w", font=ctk.CTkFont(size=12))
        self.lbl_status.pack(fill="x", pady=(0, 4))

        self.btn_toggle = ctk.CTkButton(bot_box, text="開始循環執行", height=42, fg_color="#16a34a", hover_color="#15803d", font=ctk.CTkFont(size=14, weight="bold"), command=self.toggle_run)
        self.btn_toggle.pack(fill="x")

    # ======================= 視窗與坐標邏輯 =======================
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

        self.cbo_window.configure(values=items)
        self.cbo_window.set(items[target_idx])
        if target_hwnd:
            self.set_status(f"已綁定目標視窗 HWND: {target_hwnd}")

    def on_window_select(self, val):
        global target_hwnd
        if val and str(val).startswith("["):
            try:
                target_hwnd = int(str(val).split("]")[0].replace("[", ""))
                self.set_status(f"已綁定目標視窗 HWND: {target_hwnd}")
            except Exception:
                target_hwnd = None

    def capture_pos_countdown(self, btn, on_finish):
        def worker():
            btn.configure(state="disabled")
            for i in range(3, 0, -1):
                self.set_status(f"請移至目標點... 倒數 {i} 秒")
                time.sleep(1)
            pos = pyautogui.position()
            use_rel = bool(self.chk_use_rel.get())
            if use_rel and IS_WINDOWS and target_hwnd:
                pt = POINT(int(pos.x), int(pos.y))
                user32.ScreenToClient(target_hwnd, ctypes.byref(pt))
                x, y, rel = pt.x, pt.y, True
            else:
                x, y, rel = pos.x, pos.y, False
            on_finish(x, y, rel)
            btn.configure(state="normal")
        threading.Thread(target=worker, daemon=True).start()

    def record_combo_target(self):
        def cb(x, y, rel):
            global temp_combo_target
            temp_combo_target = {"x": x, "y": y, "rel": rel}
            prefix = "相對" if rel else "絕對"
            self.lbl_combo_target.configure(text=f"{prefix}:({x}, {y})")
            self.set_status(f"已鎖定組合{prefix}目標：({x}, {y})")
        self.capture_pos_countdown(self.btn_combo_target, cb)

    def clear_combo_target(self):
        global temp_combo_target
        temp_combo_target = None
        self.lbl_combo_target.configure(text="無 (原地)")
        self.set_status("已清除目標坐標")

    # ======================= 組合庫操作 =======================
    def update_combo_list(self, select_idx=None):
        self.combo_listbox.delete(0, tk.END)
        for c in combos:
            t = c.get("target")
            t_tag = f" [{'相對' if t.get('rel') else '絕對'}目標]" if t else ""
            self.combo_listbox.insert(tk.END, f"{c['name']} ({','.join(c.get('keys', [])).upper()} / {c['wait']}s){t_tag}")
        if select_idx is not None and 0 <= select_idx < len(combos):
            self.combo_listbox.selection_set(select_idx)

    def on_combo_select(self, event):
        sel = self.combo_listbox.curselection()
        if not sel: return
        c = combos[sel[0]]
        self.ent_combo_name.delete(0, tk.END); self.ent_combo_name.insert(0, c["name"])
        self.ent_combo_keys.delete(0, tk.END); self.ent_combo_keys.insert(0, ",".join(c["keys"]))
        self.ent_combo_wait.delete(0, tk.END); self.ent_combo_wait.insert(0, str(c["wait"]))
        global temp_combo_target
        temp_combo_target = c.get("target")
        prefix = ("相對:" if temp_combo_target.get("rel") else "絕對:") if temp_combo_target else ""
        self.lbl_combo_target.configure(text=f"{prefix}({temp_combo_target['x']}, {temp_combo_target['y']})" if temp_combo_target else "無 (原地)")

    def save_new_combo(self):
        name = self.ent_combo_name.get().strip()
        keys = [k.strip().lower() for k in self.ent_combo_keys.get().replace("，", ",").split(",") if k.strip()]
        try: wait_sec = max(0.0, float(self.ent_combo_wait.get()))
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
        name = self.ent_combo_name.get().strip()
        keys = [k.strip().lower() for k in self.ent_combo_keys.get().replace("，", ",").split(",") if k.strip()]
        try: wait_sec = max(0.0, float(self.ent_combo_wait.get()))
        except ValueError: return

        new_target = dict(temp_combo_target) if temp_combo_target else None
        combos[idx] = {"name": name, "keys": keys, "wait": wait_sec, "target": new_target}
        self.update_combo_list(idx)

        # 核心聯動：自動同步執行清單所有步驟
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

    # ======================= 步驟清單操作 =======================
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
            name = self.ent_combo_name.get().strip()
            keys = [k.strip().lower() for k in self.ent_combo_keys.get().replace("，", ",").split(",") if k.strip()]
            if name and keys: c = {"name": name, "keys": keys, "wait": float(self.ent_combo_wait.get() or 1.0), "target": temp_combo_target}
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
        key = self.ent_key.get().strip().lower()
        if not key: return
        ins = self.get_insert_index()
        steps.insert(ins, {"type": "key", "key": key})
        self.update_step_list(ins)
        self.set_status(f"已插入按鍵到 #{ins+1}：[{key.upper()}]")

    def add_wait_step(self):
        try: sec = float(self.ent_wait.get())
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

    def delete_selected(self):
        sel = self.step_listbox.curselection()
        if sel:
            idx = sel[0]
            del steps[idx]
            self.update_step_list(min(idx, len(steps) - 1) if steps else None)

    def clear_all(self):
        steps.clear()
        self.update_step_list()
        self.set_status("已清空執行清單")

    # ======================= 存檔與讀檔 =======================
    def save_config(self):
        fn = self.ent_cfg_name.get().strip() or "macro_config.json"
        if not fn.endswith(".json"): fn += ".json"
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump({"combos": combos, "steps": steps}, f, ensure_ascii=False, indent=2)
            self.set_status(f"已成功儲存至 {fn}")
        except Exception as e:
            self.set_status(f"儲存失敗: {e}")

    def load_config(self):
        fn = self.ent_cfg_name.get().strip() or "macro_config.json"
        if not fn.endswith(".json"): fn += ".json"
        if not os.path.exists(fn): return self.set_status(f"找不到檔案：{fn}")
        try:
            with open(fn, "r", encoding="utf-8") as f: data = json.load(f)
            combos.clear(); combos.extend(data.get("combos", []) if isinstance(data, dict) else [])
            steps.clear(); steps.extend(data.get("steps", []) if isinstance(data, dict) else (data if isinstance(data, list) else []))
            self.update_combo_list(); self.update_step_list()
            self.set_status(f"成功載入設定檔：{fn}")
        except Exception as e:
            self.set_status(f"載入失敗: {e}")

    # ======================= 主執行循環 =======================
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
                use_bg = bool(self.chk_use_bg.get()) and IS_WINDOWS and (target_hwnd is not None)
                try: off_x, off_y = int(self.ent_offset_x.get() or 0), int(self.ent_offset_y.get() or 0)
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