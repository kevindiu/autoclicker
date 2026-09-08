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

combos = []
cur_combo_idx = -1
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
# 主 GUI 介面
# ==============================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("980x620")
        self.resizable(False, False)
        self.configure(bg="#15171c")
        self.attributes("-topmost", True)

        self.var_profile_name = tk.StringVar()
        self.var_use_bg = tk.BooleanVar(value=True)
        self.var_use_rel = tk.BooleanVar(value=True)
        self.var_offset_x = tk.StringVar(value="0")
        self.var_offset_y = tk.StringVar(value="0")
        self.var_window = tk.StringVar(value="未偵測到視窗")

        self.var_action_key = tk.StringVar(value="f1")
        self.var_action_wait = tk.StringVar(value="1.0")

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
                self.btn_toggle.config(text="開始循環執行 (當前組合)", bg="#16a34a", activebackground="#15803d")
        self.after(0, _u)

    def highlight_action(self, idx):
        def _hl():
            self.action_listbox.selection_clear(0, tk.END)
            if 0 <= idx < self.action_listbox.size():
                self.action_listbox.selection_set(idx)
                self.action_listbox.see(idx)
        self.after(0, _hl)

    # ======================= [左欄：設定 + 組合清單] =======================
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

        # 2. COMBINATION LIST (組合清單)
        f_combo = tk.LabelFrame(f_left, text=" 技能組合清單 (Combination List) ", bg="#1c1f26", fg="#38bdf8", font=("Segoe UI", 10, "bold"), padx=6, pady=6)
        f_combo.pack(fill="both", expand=True)

        cr_top = tk.Frame(f_combo, bg="#1c1f26")
        cr_top.pack(fill="x", pady=(0, 4))
        tk.Button(cr_top, text="＋ 新建組合", bg="#0284c7", fg="#fff", activebackground="#0369a1", command=self.add_new_combo).pack(side="left", padx=2)
        tk.Button(cr_top, text="複製組合", bg="#334155", fg="#fff", command=self.duplicate_combo).pack(side="left", padx=2)
        tk.Button(cr_top, text="重新命名", bg="#334155", fg="#fff", command=self.rename_combo).pack(side="left", padx=2)
        tk.Button(cr_top, text="刪除組合", bg="#b91c1c", fg="#fff", command=self.delete_combo).pack(side="right", padx=2)

        f_list_c = tk.Frame(f_combo, bg="#15171c")
        f_list_c.pack(fill="both", expand=True, pady=4)
        self.combo_listbox = tk.Listbox(
            f_list_c, bg="#15171c", fg="#f1f5f9", selectbackground="#0284c7", selectforeground="#fff",
            bd=0, highlightthickness=0, font=("Segoe UI", 10), exportselection=False
        )
        self.combo_listbox.pack(side="left", fill="both", expand=True)
        self.combo_listbox.bind("<<ListboxSelect>>", self.on_combo_select)
        sc1 = tk.Scrollbar(f_list_c, orient="vertical", command=self.combo_listbox.yview)
        sc1.pack(side="right", fill="y")
        self.combo_listbox.config(yscrollcommand=sc1.set)

    # ======================= [右欄：組合動作 (ACTIONS) + 控制] =======================
    def build_right_panel(self):
        f_right = tk.Frame(self, bg="#1c1f26", padx=8, pady=8, highlightbackground="#2d333b", highlightthickness=1)
        f_right.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="nsew")

        self.f_action = tk.LabelFrame(f_right, text=" 當前組合動作 (Combination Actions) ", bg="#1c1f26", fg="#38bdf8", font=("Segoe UI", 10, "bold"), padx=6, pady=6)
        self.f_action.pack(fill="both", expand=True)

        self.lbl_cur_combo_title = tk.Label(self.f_action, text="當前組合: 未選取", font=("Segoe UI", 11, "bold"), bg="#1c1f26", fg="#7dd3fc", anchor="w")
        self.lbl_cur_combo_title.pack(fill="x", pady=(0, 4))

        # 動作新增工具列
        f_add_tools = tk.Frame(self.f_action, bg="#1c1f26", pady=2)
        f_add_tools.pack(fill="x")

        # 動作列：記錄點擊 + 調用其他組合
        ar0 = tk.Frame(f_add_tools, bg="#1c1f26")
        ar0.pack(fill="x", pady=(0, 4))
        self.btn_action_click = tk.Button(ar0, text="記錄點擊坐標 (3秒)", bg="#334155", fg="#fff", command=self.add_click_action)
        self.btn_action_click.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self.btn_action_subcombo = tk.Button(ar0, text="＋ 調用其他組合", bg="#0284c7", fg="#fff", activebackground="#0369a1", command=self.add_subcombo_action)
        self.btn_action_subcombo.pack(side="right", fill="x", expand=True, padx=(2, 0))

        # 動作列：按鍵 + 停頓
        ar = tk.Frame(f_add_tools, bg="#1c1f26")
        ar.pack(fill="x")
        tk.Label(ar, text="按鍵:", bg="#1c1f26", fg="#cbd5e1").pack(side="left")
        tk.Entry(ar, textvariable=self.var_action_key, width=6, bg="#2d333b", fg="#fff").pack(side="left", padx=3)
        tk.Button(ar, text="加按鍵", bg="#334155", fg="#fff", command=self.add_key_action).pack(side="left", padx=2)

        tk.Label(ar, text="停頓:", bg="#1c1f26", fg="#cbd5e1").pack(side="left", padx=(12, 0))
        tk.Entry(ar, textvariable=self.var_action_wait, width=5, bg="#2d333b", fg="#fff").pack(side="left", padx=3)
        tk.Button(ar, text="加停頓", bg="#334155", fg="#fff", command=self.add_wait_action).pack(side="left", padx=2)

        # 動作清單 (ACTION LISTBOX)
        f_list_a = tk.Frame(self.f_action, bg="#15171c")
        f_list_a.pack(fill="both", expand=True, pady=6)
        self.action_listbox = tk.Listbox(
            f_list_a, bg="#15171c", fg="#f1f5f9", selectbackground="#0284c7", selectforeground="#fff",
            bd=0, highlightthickness=0, font=("Segoe UI", 10), exportselection=False
        )
        self.action_listbox.pack(side="left", fill="both", expand=True)
        sc2 = tk.Scrollbar(f_list_a, orient="vertical", command=self.action_listbox.yview)
        sc2.pack(side="right", fill="y")
        self.action_listbox.config(yscrollcommand=sc2.set)

        # 動作操作工具列
        ar2 = tk.Frame(self.f_action, bg="#1c1f26")
        ar2.pack(fill="x", pady=(2, 0))
        tk.Button(ar2, text="上移", width=7, bg="#334155", fg="#fff", command=lambda: self.move_action(-1)).pack(side="left", padx=2)
        tk.Button(ar2, text="下移", width=7, bg="#334155", fg="#fff", command=lambda: self.move_action(1)).pack(side="left", padx=2)
        tk.Button(ar2, text="複製所選", width=8, bg="#0284c7", fg="#fff", activebackground="#0369a1", command=self.duplicate_action).pack(side="left", padx=2)
        tk.Button(ar2, text="刪除所選", width=8, bg="#b91c1c", fg="#fff", command=self.delete_action).pack(side="left", padx=2)
        tk.Button(ar2, text="清空動作", width=8, bg="#b91c1c", fg="#fff", command=self.clear_actions).pack(side="left", padx=2)

        # 底部狀態與主執行開關
        bot = tk.Frame(f_right, bg="#1c1f26")
        bot.pack(fill="x", pady=(6, 0))
        self.lbl_status = tk.Label(bot, text="狀態: 已就緒", anchor="w", bg="#1c1f26", fg="#f1f5f9", font=("Segoe UI", 9))
        self.lbl_status.pack(fill="x", pady=(0, 4))
        self.btn_toggle = tk.Button(bot, text="開始循環執行 (當前組合)", height=2, bg="#16a34a", fg="#ffffff", font=("Segoe UI", 11, "bold"), activebackground="#15803d", command=self.toggle_run)
        self.btn_toggle.pack(fill="x")

    # ======================= 組合管理邏輯 (左欄) =======================
    def update_combo_listbox(self, select_idx=None):
        self.combo_listbox.delete(0, tk.END)
        for i, c in enumerate(combos):
            cnt = len(c.get("actions", []))
            self.combo_listbox.insert(tk.END, f"#{i+1:02d}  {c['name']}  ({cnt} 個動作)")

        if select_idx is not None and 0 <= select_idx < len(combos):
            self.combo_listbox.selection_set(select_idx)
            self.on_combo_select()
        elif len(combos) > 0 and not self.combo_listbox.curselection():
            self.combo_listbox.selection_set(0)
            self.on_combo_select()
        elif len(combos) == 0:
            self.lbl_cur_combo_title.config(text="當前組合: 未選取")
            self.action_listbox.delete(0, tk.END)

    def on_combo_select(self, event=None):
        global cur_combo_idx
        sel = self.combo_listbox.curselection()
        if not sel: return
        cur_combo_idx = sel[0]
        c = combos[cur_combo_idx]
        self.lbl_cur_combo_title.config(text=f"當前組合: [ {c['name']} ]")
        self.update_action_listbox()

    def add_new_combo(self):
        name = simpledialog.askstring("新建組合", "請輸入新組合名稱:", parent=self)
        if not name or not name.strip(): return
        new_c = {"name": name.strip(), "actions": []}
        combos.append(new_c)
        self.update_combo_listbox(select_idx=len(combos)-1)
        self.set_status(f"已新增組合：[{name.strip()}]")

    def duplicate_combo(self):
        sel = self.combo_listbox.curselection()
        if not sel: return self.set_status("請先選擇要複製的組合！")
        src = combos[sel[0]]
        new_c = copy.deepcopy(src)
        new_c["name"] = f"{src['name']} (副本)"
        combos.insert(sel[0] + 1, new_c)
        self.update_combo_listbox(select_idx=sel[0] + 1)
        self.set_status(f"已複製組合：[{new_c['name']}]")

    def rename_combo(self):
        sel = self.combo_listbox.curselection()
        if not sel: return self.set_status("請先選擇要重新命名的組合！")
        old_name = combos[sel[0]]["name"]
        new_name = simpledialog.askstring("重新命名組合", "請輸入新的組合名稱:", initialvalue=old_name, parent=self)
        if not new_name or not new_name.strip(): return
        new_name = new_name.strip()
        # 同步更新其他組合內部有引用此名稱的 combo_call
        for c in combos:
            for act in c.get("actions", []):
                if act.get("type") == "combo_call" and act.get("target_name") == old_name:
                    act["target_name"] = new_name
        combos[sel[0]]["name"] = new_name
        self.update_combo_listbox(select_idx=sel[0])
        self.set_status(f"組合已更名為：[{new_name}]")

    def delete_combo(self):
        sel = self.combo_listbox.curselection()
        if not sel: return self.set_status("請先選擇要刪除的組合！")
        name = combos[sel[0]]["name"]
        if messagebox.askyesno("刪除確認", f"確定要刪除組合「{name}」及其所有動作？", parent=self):
            del combos[sel[0]]
            new_sel = min(sel[0], len(combos) - 1) if combos else None
            self.update_combo_listbox(select_idx=new_sel)
            self.set_status(f"已刪除組合：[{name}]")

    # ======================= 組合動作編輯邏輯 (右欄) =======================
    def get_cur_actions(self):
        if 0 <= cur_combo_idx < len(combos):
            if "actions" not in combos[cur_combo_idx]:
                combos[cur_combo_idx]["actions"] = []
            return combos[cur_combo_idx]["actions"]
        return None

    def build_action_display_list(self):
        actions = self.get_cur_actions()
        if actions is None: return []
        items = []
        for i, s in enumerate(actions):
            if s["type"] == "click":
                prefix = "相對:" if s.get("rel", False) else "絕對:"
                items.append(f"#{i+1:02d}  [點擊] -> {prefix}({s['x']}, {s['y']})")
            elif s["type"] == "key":
                items.append(f"#{i+1:02d}  [按鍵] -> [ {s['key'].upper()} ]")
            elif s["type"] == "wait":
                items.append(f"#{i+1:02d}  [停頓] -> {s['sec']} 秒")
            elif s["type"] == "combo_call":
                items.append(f"#{i+1:02d}  [子組合] -> [ {s['target_name']} ]")
        return items

    def update_action_listbox(self, select_idx=None):
        self.action_listbox.delete(0, tk.END)
        for it in self.build_action_display_list():
            self.action_listbox.insert(tk.END, it)

        if 0 <= cur_combo_idx < len(combos):
            cnt = len(self.get_cur_actions())
            self.combo_listbox.delete(cur_combo_idx)
            self.combo_listbox.insert(cur_combo_idx, f"#{cur_combo_idx+1:02d}  {combos[cur_combo_idx]['name']}  ({cnt} 個動作)")
            self.combo_listbox.selection_set(cur_combo_idx)

        if select_idx is not None:
            actions = self.get_cur_actions()
            if actions and 0 <= select_idx < len(actions):
                self.action_listbox.selection_set(select_idx)

    def get_action_insert_index(self):
        sel = self.action_listbox.curselection()
        actions = self.get_cur_actions()
        return sel[0] + 1 if sel else (len(actions) if actions is not None else 0)

    def add_click_action(self):
        actions = self.get_cur_actions()
        if actions is None: return self.set_status("請先在左邊選擇或新建組合！")
        ins = self.get_action_insert_index()

        def cb(x, y, rel):
            actions.insert(ins, {"type": "click", "x": x, "y": y, "rel": rel})
            self.update_action_listbox(ins)
            self.set_status(f"已插入{'相對' if rel else '絕對'}點擊到 #{ins+1}：({x}, {y})")

        self.capture_pos_countdown(self.btn_action_click, cb)

    def add_key_action(self):
        actions = self.get_cur_actions()
        if actions is None: return self.set_status("請先在左邊選擇或新建組合！")
        key = self.var_action_key.get().strip().lower()
        if not key: return
        ins = self.get_action_insert_index()
        actions.insert(ins, {"type": "key", "key": key})
        self.update_action_listbox(ins)
        self.set_status(f"已插入按鍵到 #{ins+1}：[{key.upper()}]")

    def add_wait_action(self):
        actions = self.get_cur_actions()
        if actions is None: return self.set_status("請先在左邊選擇或新建組合！")
        try: sec = float(self.var_action_wait.get())
        except ValueError: return self.set_status("停頓時間格式錯誤！")
        if sec <= 0: return
        ins = self.get_action_insert_index()
        actions.insert(ins, {"type": "wait", "sec": sec})
        self.update_action_listbox(ins)
        self.set_status(f"已插入等待到 #{ins+1}：{sec} 秒")

    # 核心：調用其他組合為動作步驟
    def add_subcombo_action(self):
        actions = self.get_cur_actions()
        if actions is None: return self.set_status("請先在左邊選擇或新建組合！")
        cur_name = combos[cur_combo_idx]["name"]

        # 排除自己，列出其餘可調用組合
        avail_combos = [c["name"] for i, c in enumerate(combos) if i != cur_combo_idx]
        if not avail_combos:
            messagebox.showinfo("提示", "目前沒有其他組合可供調用！\n請先在左邊「＋新建組合」建立其他組合。", parent=self)
            return

        # 彈出小視窗選擇欲調用的組合
        dlg = tk.Toplevel(self)
        dlg.title("選擇要調用的子組合")
        dlg.geometry("320x130")
        dlg.resizable(False, False)
        dlg.configure(bg="#1c1f26")
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="請選擇要嵌入的子組合:", bg="#1c1f26", fg="#f1f5f9", font=("Segoe UI", 10)).pack(pady=(15, 6))
        var_choice = tk.StringVar(value=avail_combos[0])
        cbo = ttk.Combobox(dlg, textvariable=var_choice, values=avail_combos, state="readonly", width=25)
        cbo.pack(pady=4)

        def on_confirm():
            chosen = var_choice.get()
            dlg.destroy()
            ins = self.get_action_insert_index()
            actions.insert(ins, {"type": "combo_call", "target_name": chosen})
            self.update_action_listbox(ins)
            self.set_status(f"已插入子組合調用 #{ins+1}：[{chosen}]")

        btn_f = tk.Frame(dlg, bg="#1c1f26")
        btn_f.pack(pady=10)
        tk.Button(btn_f, text="確定加入", bg="#0284c7", fg="#fff", width=10, command=on_confirm).pack(side="left", padx=4)
        tk.Button(btn_f, text="取消", bg="#334155", fg="#fff", width=8, command=dlg.destroy).pack(side="left", padx=4)

    def move_action(self, delta):
        actions = self.get_cur_actions()
        if not actions: return
        sel = self.action_listbox.curselection()
        if sel and 0 <= sel[0] + delta < len(actions):
            idx = sel[0]
            actions[idx], actions[idx + delta] = actions[idx + delta], actions[idx]
            self.update_action_listbox(idx + delta)

    def duplicate_action(self):
        actions = self.get_cur_actions()
        if not actions: return
        sel = self.action_listbox.curselection()
        if not sel: return self.set_status("請先選擇要複製的動作！")
        idx = sel[0]
        ins = idx + 1
        actions.insert(ins, copy.deepcopy(actions[idx]))
        self.update_action_listbox(ins)
        self.set_status(f"已複製動作 #{idx+1} 到 #{ins+1}")

    def delete_action(self):
        actions = self.get_cur_actions()
        if not actions: return
        sel = self.action_listbox.curselection()
        if sel:
            idx = sel[0]
            del actions[idx]
            self.update_action_listbox(min(idx, len(actions) - 1) if actions else None)

    def clear_actions(self):
        actions = self.get_cur_actions()
        if not actions: return self.set_status("動作清單本來就是空的")
        if messagebox.askyesno("清空確認", "確定要清空當前組合的所有動作？", parent=self):
            actions.clear()
            self.update_action_listbox()
            self.set_status("已清空當前組合的所有動作")

    # ======================= 系統與設定檔管理 =======================
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
                        json.dump({"combos": [{"name": "預設連招", "actions": []}]}, f)
                except Exception: pass

        self.cbo_profile["values"] = profiles
        if select_name and select_name in profiles:
            self.cbo_profile.set(select_name)
        elif self.var_profile_name.get() in profiles:
            self.cbo_profile.set(self.var_profile_name.get())
        else:
            self.cbo_profile.current(0)
        self.load_config()

    def create_new_profile(self):
        name = simpledialog.askstring("新建設定檔", "請輸入新設定檔名稱 (毋須輸入副檔名):", parent=self)
        if not name or not name.strip(): return
        name = name.strip()
        fn = f"{name}{CONFIG_EXT}"
        if os.path.exists(fn) and not messagebox.askyesno("檔案覆蓋確認", f"「{name}」已存在，是否覆蓋？", parent=self):
            return
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump({"combos": [{"name": "新連招", "actions": []}]}, f, ensure_ascii=False, indent=2)
            self.refresh_profiles(select_name=name)
            self.set_status(f"已新建設定檔：{name}")
        except Exception as e:
            self.set_status(f"新建失敗: {e}")

    def save_config(self):
        name = self.var_profile_name.get().strip()
        if not name: return self.set_status("請先選擇或新建設定檔")
        fn = f"{name}{CONFIG_EXT}"
        if os.path.exists(fn) and not messagebox.askyesno("檔案覆蓋確認", f"確定要覆蓋「{name}」的設定？", parent=self):
            return self.set_status("已取消儲存")
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump({"combos": combos}, f, ensure_ascii=False, indent=2)
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
            combos.clear()
            raw_combos = data.get("combos", []) if isinstance(data, dict) else []

            for rc in raw_combos:
                if "actions" in rc:
                    combos.append(rc)
                else:
                    actions = []
                    t = rc.get("target")
                    if t:
                        actions.append({"type": "click", "x": t["x"], "y": t["y"], "rel": t.get("rel", True)})
                    for k in rc.get("keys", []):
                        actions.append({"type": "key", "key": k})
                    if rc.get("wait", 0) > 0:
                        actions.append({"type": "wait", "sec": rc["wait"]})
                    combos.append({"name": rc.get("name", "未命名"), "actions": actions})

            if not combos:
                combos.append({"name": "預設連招", "actions": []})

            self.update_combo_listbox(select_idx=0)
            self.set_status(f"成功載入設定檔：{name}")
        except Exception as e:
            self.set_status(f"載入失敗: {e}")

    # ======================= 主執行循環 (支援子組合遞迴調用) =======================
    def toggle_run(self):
        global running
        if running:
            running = False
            stop_event.set()
            emergency_release_bg_only()
            self.set_running_ui(False)
            self.set_status("已手動停止")
        else:
            actions = self.get_cur_actions()
            if not actions:
                return self.set_status("當前組合沒有任何動作，請先在右邊加入動作！")
            stop_event.clear()
            running = True
            self.set_running_ui(True)
            self.set_status(f"循環運作中... (組合: {combos[cur_combo_idx]['name']})")
            threading.Thread(target=self.macro_worker_loop, daemon=True).start()

    def macro_worker_loop(self):
        global running
        round_idx = 1

        # 動作遞迴執行函數 (防死循環呼叫)
        def run_action_sequence(action_list, call_stack, is_top_level=True):
            use_bg = self.var_use_bg.get() and IS_WINDOWS and (target_hwnd is not None)
            try: off_x, off_y = int(self.var_offset_x.get() or 0), int(self.var_offset_y.get() or 0)
            except Exception: off_x, off_y = 0, 0

            for idx, step in enumerate(action_list):
                if not running or stop_event.is_set(): return False
                if is_top_level: self.highlight_action(idx)

                stype = step["type"]
                if stype == "click":
                    msg = execute_click(step["x"], step["y"], step.get("rel", True), use_bg, off_x, off_y)
                    self.set_status(f"第 {round_idx} 輪: {msg}")
                    if not safe_sleep(0.12): return False

                elif stype == "key":
                    post_bg_key(target_hwnd, step["key"]) if use_bg else (pyautogui.keyDown(step["key"]), safe_sleep(0.06), pyautogui.keyUp(step["key"]))
                    self.set_status(f"第 {round_idx} 輪: 按鍵 [{step['key'].upper()}]")
                    if not safe_sleep(0.10): return False

                elif stype == "wait":
                    self.set_status(f"第 {round_idx} 輪: 等待 {step['sec']} 秒")
                    if not safe_sleep(float(step["sec"])): return False

                elif stype == "combo_call":
                    target_name = step.get("target_name")
                    if target_name in call_stack:
                        self.set_status(f"警告: 偵測到循環調用 [{target_name}]，已跳過！")
                        continue

                    # 尋找目標組合
                    target_combo = next((c for c in combos if c["name"] == target_name), None)
                    if target_combo:
                        self.set_status(f"第 {round_idx} 輪: 進入子組合 [{target_name}]")
                        new_stack = call_stack | {target_name}
                        if not run_action_sequence(target_combo.get("actions", []), new_stack, is_top_level=False):
                            return False
                    else:
                        self.set_status(f"警告: 找不到子組合 [{target_name}]")
            return True

        try:
            while running and not stop_event.is_set():
                if 0 <= cur_combo_idx < len(combos):
                    top_actions = list(combos[cur_combo_idx].get("actions", []))
                    top_name = combos[cur_combo_idx]["name"]
                    if not run_action_sequence(top_actions, call_stack={top_name}, is_top_level=True):
                        break
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