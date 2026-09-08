import os
import json
import time
import ctypes
from ctypes import wintypes
import threading
import pyautogui
import dearpygui.dearpygui as dpg

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

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

# --- 中斷等待與按鍵釋放 ---
def safe_sleep(seconds):
    end = time.time() + float(seconds)
    while time.time() < end:
        if not running or stop_event.is_set():
            return False
        time.sleep(0.02)
    return True

def emergency_release():
    try: pyautogui.mouseUp()
    except Exception: pass
    for k in ["shift", "ctrl", "alt", "space", "enter"] + [f"f{i}" for i in range(1, 13)]:
        try: pyautogui.keyUp(k)
        except Exception: pass
    if IS_WINDOWS and target_hwnd:
        try: user32.PostMessageW(target_hwnd, 0x0202, 0, 0)
        except Exception: pass
        for vk in VK_MAP.values():
            try: user32.PostMessageW(target_hwnd, 0x0101, vk, 0xC0000001)
            except Exception: pass

# --- 視窗列舉與綁定 ---
def get_window_list():
    if not IS_WINDOWS: return []
    windows = []
    def enum_proc(hwnd, lParam):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            buff = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
            user32.GetWindowTextW(hwnd, buff, len(buff))
            if buff.value.strip(): windows.append((hwnd, buff.value.strip()))
        return True
    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)(enum_proc), 0)
    return windows

def refresh_window_dropdown():
    global target_hwnd
    win_list = get_window_list()
    items, target_idx = [], 0
    for i, (hwnd, title) in enumerate(win_list):
        items.append(f"[{hwnd}] {title}")
        if "水滸" in title or "online" in title.lower(): target_idx = i

    if not items:
        items, target_hwnd = ["未偵測到任何視窗 (非 Windows/Wine 環境)"], None
    else:
        target_hwnd = win_list[target_idx][0]

    dpg.configure_item("combo_window_select", items=items)
    if items and not items[0].startswith("未偵測"):
        dpg.set_value("combo_window_select", items[target_idx])
        dpg.set_value("lbl_status", f"已綁定目標視窗 HWND: {target_hwnd}")

def on_window_select(sender, app_data):
    global target_hwnd
    val = app_data or dpg.get_value("combo_window_select")
    if val and str(val).startswith("["):
        try:
            target_hwnd = int(str(val).split("]")[0].replace("[", ""))
            dpg.set_value("lbl_status", f"已綁定目標視窗 HWND: {target_hwnd}")
        except Exception:
            target_hwnd = None

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

# --- 坐標取點 (通用倒數函式) ---
def capture_pos_countdown(btn_tag, on_finish):
    def worker():
        dpg.configure_item(btn_tag, enabled=False)
        for i in range(3, 0, -1):
            dpg.set_value("lbl_status", f"請移至目標點... 倒數 {i} 秒")
            time.sleep(1)
        pos = pyautogui.position()
        use_rel = dpg.get_value("chk_use_relative")
        if use_rel and IS_WINDOWS and target_hwnd:
            pt = POINT(int(pos.x), int(pos.y))
            user32.ScreenToClient(target_hwnd, ctypes.byref(pt))
            x, y, rel = pt.x, pt.y, True
        else:
            x, y, rel = pos.x, pos.y, False
        on_finish(x, y, rel)
        dpg.configure_item(btn_tag, enabled=True)
    threading.Thread(target=worker, daemon=True).start()

def record_combo_target():
    def cb(x, y, rel):
        global temp_combo_target
        temp_combo_target = {"x": x, "y": y, "rel": rel}
        prefix = "相對" if rel else "絕對"
        dpg.set_value("lbl_combo_target", f"{prefix}:({x}, {y})")
        dpg.set_value("lbl_status", f"已鎖定組合{prefix}目標：({x}, {y})")
    capture_pos_countdown("btn_combo_target", cb)

def clear_combo_target():
    global temp_combo_target
    temp_combo_target = None
    dpg.set_value("lbl_combo_target", "無 (原地)")
    dpg.set_value("lbl_status", "已清除目標坐標")

# --- 技能組合庫邏輯 ---
def update_combo_list(select_idx=None):
    items = []
    for c in combos:
        t = c.get("target")
        t_tag = f" [{'相對' if t.get('rel') else '絕對'}目標]" if t else ""
        items.append(f"{c['name']} ({','.join(c.get('keys', [])).upper()} / {c['wait']}s){t_tag}")
    dpg.configure_item("combo_listbox", items=items)
    if select_idx is not None and 0 <= select_idx < len(items):
        dpg.set_value("combo_listbox", items[select_idx])

def on_combo_select(sender, app_data):
    selected = dpg.get_value("combo_listbox")
    items = dpg.get_item_configuration("combo_listbox")["items"]
    if selected in items:
        c = combos[items.index(selected)]
        dpg.set_value("input_combo_name", c["name"])
        dpg.set_value("input_combo_keys", ",".join(c["keys"]))
        dpg.set_value("input_combo_wait", str(c["wait"]))
        global temp_combo_target
        temp_combo_target = c.get("target")
        prefix = ("相對:" if temp_combo_target.get("rel") else "絕對:") if temp_combo_target else ""
        dpg.set_value("lbl_combo_target", f"{prefix}({temp_combo_target['x']}, {temp_combo_target['y']})" if temp_combo_target else "無 (原地)")

def save_new_combo():
    name = dpg.get_value("input_combo_name").strip()
    keys = [k.strip().lower() for k in dpg.get_value("input_combo_keys").replace("，", ",").split(",") if k.strip()]
    try: wait_sec = max(0.0, float(dpg.get_value("input_combo_wait")))
    except ValueError: return dpg.set_value("lbl_status", "CD等待時間格式錯誤！")
    if not name or not keys: return dpg.set_value("lbl_status", "請輸入組合名稱與按鍵！")

    combos.append({"name": name, "keys": keys, "wait": wait_sec, "target": dict(temp_combo_target) if temp_combo_target else None})
    update_combo_list(select_idx=len(combos)-1)
    dpg.set_value("lbl_status", f"已建立新組合：[{name}]")

def update_selected_combo():
    selected = dpg.get_value("combo_listbox")
    items = dpg.get_item_configuration("combo_listbox")["items"]
    if not selected or selected not in items: return dpg.set_value("lbl_status", "請先在清單點選要修改的組合！")

    idx = items.index(selected)
    old_name = combos[idx]["name"]
    name = dpg.get_value("input_combo_name").strip()
    keys = [k.strip().lower() for k in dpg.get_value("input_combo_keys").replace("，", ",").split(",") if k.strip()]
    try: wait_sec = max(0.0, float(dpg.get_value("input_combo_wait")))
    except ValueError: return

    new_target = dict(temp_combo_target) if temp_combo_target else None
    combos[idx] = {"name": name, "keys": keys, "wait": wait_sec, "target": new_target}
    update_combo_list(select_idx=idx)

    sync_count = 0
    for s in steps:
        if s.get("type") == "combo" and s.get("name") == old_name:
            s.update({"name": name, "keys": list(keys), "wait": wait_sec, "target": dict(new_target) if new_target else None})
            sync_count += 1
    if sync_count > 0: update_step_list()
    dpg.set_value("lbl_status", f"已更新組合 [{name}]，並同步刷新清單內 {sync_count} 個步驟！")

def delete_selected_combo():
    selected = dpg.get_value("combo_listbox")
    items = dpg.get_item_configuration("combo_listbox")["items"]
    if selected in items:
        del combos[items.index(selected)]
        update_combo_list()
        dpg.set_value("lbl_status", "已刪除該組合 (執行清單保留原有步驟)")

# --- 步驟清單邏輯與通用索引輔助 ---
def get_sel_step_idx():
    val = dpg.get_value("step_listbox")
    if val and val.startswith("#"):
        try: return int(val.split()[0][1:]) - 1
        except Exception: pass
    return None

def get_insert_index():
    idx = get_sel_step_idx()
    return len(steps) if idx is None or not (0 <= idx < len(steps)) else idx + 1

def build_display_list():
    items = []
    for i, s in enumerate(steps):
        t = s.get("target")
        t_str = f"[{'相對:' if t.get('rel') else '絕對:'}({t['x']},{t['y']})] " if t else ""
        if s["type"] == "click": items.append(f"#{i+1:02d}  [點擊] -> {'相對:' if s.get('rel') else '絕對:'}({s['x']}, {s['y']})")
        elif s["type"] == "key": items.append(f"#{i+1:02d}  [按鍵] -> [ {s['key'].upper()} ]")
        elif s["type"] == "wait": items.append(f"#{i+1:02d}  [停頓] -> {s['sec']} 秒")
        elif s["type"] == "combo": items.append(f"#{i+1:02d}  [{s['name']}] {t_str}[{','.join(s.get('keys', [])).upper()}] [CD:{s['wait']}s]")
    return items

def update_step_list(select_idx=None):
    items = build_display_list()
    dpg.configure_item("step_listbox", items=items)
    if select_idx is not None and 0 <= select_idx < len(items):
        dpg.set_value("step_listbox", items[select_idx])

def add_combo_to_steps():
    selected = dpg.get_value("combo_listbox")
    items = dpg.get_item_configuration("combo_listbox")["items"]
    c = combos[items.index(selected)] if selected in items else None
    if not c:
        name = dpg.get_value("input_combo_name").strip()
        keys = [k.strip().lower() for k in dpg.get_value("input_combo_keys").replace("，", ",").split(",") if k.strip()]
        if name and keys: c = {"name": name, "keys": keys, "wait": float(dpg.get_value("input_combo_wait") or 1.0), "target": temp_combo_target}
    if not c: return dpg.set_value("lbl_status", "請先選擇或填寫組合內容！")

    ins = get_insert_index()
    steps.insert(ins, {"type": "combo", "name": c["name"], "keys": list(c["keys"]), "wait": c["wait"], "target": dict(c["target"]) if c.get("target") else None})
    update_step_list(ins)
    dpg.set_value("lbl_status", f"已加入清單 #{ins+1}: [{c['name']}]")

def add_click_step():
    ins = get_insert_index()
    def cb(x, y, rel):
        steps.insert(ins, {"type": "click", "x": x, "y": y, "rel": rel})
        update_step_list(ins)
        dpg.set_value("lbl_status", f"已插入{'相對' if rel else '絕對'}點擊到 #{ins+1}：({x}, {y})")
    capture_pos_countdown("btn_add_click", cb)

def add_key_step():
    key = dpg.get_value("input_key").strip().lower()
    if not key: return
    ins = get_insert_index()
    steps.insert(ins, {"type": "key", "key": key})
    update_step_list(ins)
    dpg.set_value("lbl_status", f"已插入按鍵到 #{ins+1}：[{key.upper()}]")

def add_wait_step():
    try: sec = float(dpg.get_value("input_wait"))
    except ValueError: return
    if sec <= 0: return
    ins = get_insert_index()
    steps.insert(ins, {"type": "wait", "sec": sec})
    update_step_list(ins)
    dpg.set_value("lbl_status", f"已插入等待到 #{ins+1}：{sec} 秒")

def move_step(delta):
    idx = get_sel_step_idx()
    if idx is not None and 0 <= idx + delta < len(steps):
        steps[idx], steps[idx + delta] = steps[idx + delta], steps[idx]
        update_step_list(idx + delta)

def delete_selected():
    idx = get_sel_step_idx()
    if idx is not None and 0 <= idx < len(steps):
        del steps[idx]
        update_step_list(min(idx, len(steps) - 1) if steps else None)

def clear_all():
    steps.clear()
    update_step_list()
    dpg.set_value("lbl_status", "已清空執行清單")

# --- 存檔與讀檔 ---
def save_config():
    fn = dpg.get_value("input_config_name").strip() or "macro_config.json"
    if not fn.endswith(".json"): fn += ".json"
    try:
        with open(fn, "w", encoding="utf-8") as f: json.dump({"combos": combos, "steps": steps}, f, ensure_ascii=False, indent=2)
        dpg.set_value("lbl_status", f"已成功儲存至 {fn}")
    except Exception as e: dpg.set_value("lbl_status", f"儲存失敗: {e}")

def load_config():
    fn = dpg.get_value("input_config_name").strip() or "macro_config.json"
    if not fn.endswith(".json"): fn += ".json"
    if not os.path.exists(fn): return dpg.set_value("lbl_status", f"找不到檔案：{fn}")
    try:
        with open(fn, "r", encoding="utf-8") as f: data = json.load(f)
        combos.clear(); combos.extend(data.get("combos", []) if isinstance(data, dict) else [])
        steps.clear(); steps.extend(data.get("steps", []) if isinstance(data, dict) else (data if isinstance(data, list) else []))
        update_combo_list(); update_step_list()
        dpg.set_value("lbl_status", f"成功載入設定檔：{fn}")
    except Exception as e: dpg.set_value("lbl_status", f"載入失敗: {e}")

# --- 主執行引擎 ---
def toggle_run():
    global running
    if running:
        running = False
        stop_event.set()
        emergency_release()
        dpg.configure_item("btn_toggle", label="開始循環執行")
        dpg.bind_item_theme("btn_toggle", "theme_btn_start")
        dpg.set_value("lbl_status", "狀態：已手動停止")
    else:
        if not steps: return dpg.set_value("lbl_status", "執行清單是空的，請先加入步驟！")
        emergency_release()
        stop_event.clear()
        running = True
        dpg.configure_item("btn_toggle", label="停止執行")
        dpg.bind_item_theme("btn_toggle", "theme_btn_stop")
        dpg.set_value("lbl_status", "狀態：循環運作中...")
        threading.Thread(target=macro_worker_loop, daemon=True).start()

def macro_worker_loop():
    global running
    round_idx = 1
    display_items = build_display_list()

    try:
        while running and not stop_event.is_set():
            use_bg = dpg.get_value("chk_use_bg") and IS_WINDOWS and (target_hwnd is not None)
            try: off_x, off_y = int(dpg.get_value("input_offset_x") or 0), int(dpg.get_value("input_offset_y") or 0)
            except Exception: off_x, off_y = 0, 0

            for idx, step in enumerate(steps):
                if not running or stop_event.is_set(): break
                if 0 <= idx < len(display_items):
                    try: dpg.set_value("step_listbox", display_items[idx])
                    except Exception: pass

                stype = step["type"]
                if stype == "click":
                    msg = execute_click(step["x"], step["y"], step.get("rel"), use_bg, off_x, off_y)
                    dpg.set_value("lbl_status", f"第 {round_idx} 輪 ({idx+1}/{len(steps)}): {msg}")
                    if not safe_sleep(0.12): break

                elif stype == "key":
                    post_bg_key(target_hwnd, step["key"]) if use_bg else (pyautogui.keyDown(step["key"]), safe_sleep(0.06), pyautogui.keyUp(step["key"]))
                    dpg.set_value("lbl_status", f"第 {round_idx} 輪 ({idx+1}/{len(steps)}): 按鍵 [{step['key'].upper()}]")
                    if not safe_sleep(0.10): break

                elif stype == "wait":
                    if not safe_sleep(float(step["sec"])): break

                elif stype == "combo":
                    if step.get("target"):
                        msg = execute_click(step["target"]["x"], step["target"]["y"], step["target"].get("rel"), use_bg, off_x, off_y)
                        dpg.set_value("lbl_status", f"第 {round_idx} 輪: 組合[{step['name']}] {msg}")
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
        dpg.set_value("lbl_status", f"異常中斷: {e}")
    finally:
        running = False
        emergency_release()
        try:
            dpg.configure_item("btn_toggle", label="開始循環執行")
            dpg.bind_item_theme("btn_toggle", "theme_btn_start")
        except Exception: pass

# --- UI 構建與樣式初始化 ---
dpg.create_context()

candidate_fonts = [
    os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", f)
    for f in ["msjh.ttc", "msjhbd.ttc", "msyh.ttc", "mingliu.ttc"]
] + ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc"]

fpath = next((f for f in candidate_fonts if os.path.exists(f)), None)
if fpath:
    with dpg.font_registry():
        with dpg.font(fpath, 14) as df: dpg.add_font_range_hint(dpg.mvFontRangeHint_Chinese_Full)
        dpg.bind_font(df)

with dpg.theme() as global_theme:
    with dpg.theme_component(dpg.mvAll):
        for var, val in [(dpg.mvStyleVar_WindowPadding, (10, 10)), (dpg.mvStyleVar_FramePadding, (7, 5)), (dpg.mvStyleVar_ItemSpacing, (7, 6)), (dpg.mvStyleVar_FrameRounding, 5), (dpg.mvStyleVar_ChildRounding, 6)]:
            dpg.add_theme_style(var, *val if isinstance(val, tuple) else (val,))
        for col, val in [(dpg.mvThemeCol_WindowBg, (21, 23, 28)), (dpg.mvThemeCol_ChildBg, (28, 31, 38)), (dpg.mvThemeCol_Border, (44, 49, 60)), (dpg.mvThemeCol_Text, (241, 245, 249)), (dpg.mvThemeCol_FrameBg, (37, 41, 50)), (dpg.mvThemeCol_Button, (41, 46, 56)), (dpg.mvThemeCol_ButtonHovered, (56, 63, 77)), (dpg.mvThemeCol_ButtonActive, (71, 80, 98)), (dpg.mvThemeCol_Header, (37, 99, 235, 160)), (dpg.mvThemeCol_HeaderHovered, (37, 99, 235, 220)), (dpg.mvThemeCol_HeaderActive, (29, 78, 216))]:
            dpg.add_theme_color(col, (*val, 255) if len(val) == 3 else val)
dpg.bind_theme(global_theme)

theme_data = [
    ("theme_btn_action", (2, 132, 199, 220), (14, 165, 233, 255), (3, 105, 161, 255)),
    ("theme_btn_danger", (185, 28, 28, 180), (220, 38, 38, 255), (153, 27, 27, 255)),
    ("theme_btn_start",  (22, 163, 74, 255), (34, 197, 94, 255), (21, 128, 61, 255)),
    ("theme_btn_stop",   (220, 38, 38, 255), (239, 68, 68, 255), (185, 28, 28, 255)),
]
for tag, norm, hov, act in theme_data:
    with dpg.theme(tag=tag):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, norm)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, hov)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, act)

# ================= 主介面排版 (左右雙欄) =================
with dpg.window(tag="primary_window"):
    with dpg.group(horizontal=True):
        # [左欄：設定檔 + 組合庫]
        with dpg.child_window(width=445, height=545, border=False):
            with dpg.child_window(height=130, border=True):
                dpg.add_text("設定與 Win32 後台綁定", color=(56, 189, 248))
                dpg.add_separator()
                with dpg.group(horizontal=True):
                    dpg.add_text("設定檔:")
                    dpg.add_input_text(tag="input_config_name", default_value="sh_macro.json", width=180)
                    dpg.add_button(label="儲存", callback=save_config, width=65)
                    dpg.add_button(label="載入", callback=load_config, width=65)
                with dpg.group(horizontal=True):
                    dpg.add_checkbox(label="Win32後台", tag="chk_use_bg", default_value=True)
                    dpg.add_checkbox(label="相對坐標 (Relative)", tag="chk_use_relative", default_value=True)
                    dpg.add_text("微調X:")
                    dpg.add_input_text(tag="input_offset_x", default_value="0", width=35)
                    dpg.add_text("Y:")
                    dpg.add_input_text(tag="input_offset_y", default_value="0", width=35)
                with dpg.group(horizontal=True):
                    dpg.add_text("目標視窗:")
                    dpg.add_combo(tag="combo_window_select", items=[], width=240, callback=on_window_select)
                    dpg.add_button(label="重新整理", callback=refresh_window_dropdown, width=65)

            dpg.add_spacer(height=2)

            # 核心調整：高度微調至 410，num_items 擴大到 12 行，完美消除按鈕下方的空白
            with dpg.child_window(height=410, border=True):
                dpg.add_text("技能組合預設 (Combinations)", color=(56, 189, 248))
                dpg.add_separator()
                with dpg.group(horizontal=True):
                    dpg.add_text("名稱:")
                    dpg.add_input_text(tag="input_combo_name", default_value="F4補血CD", width=120)
                    dpg.add_text("按鍵:")
                    dpg.add_input_text(tag="input_combo_keys", default_value="f4", width=80)
                    dpg.add_text("CD(秒):")
                    dpg.add_input_text(tag="input_combo_wait", default_value="10.0", width=45)
                with dpg.group(horizontal=True):
                    dpg.add_text("目標:")
                    dpg.add_text("無 (原地)", tag="lbl_combo_target", color=(125, 211, 252))
                    dpg.add_button(label="記錄目標 (3秒)", tag="btn_combo_target", callback=record_combo_target, width=105)
                    dpg.add_button(label="清除", callback=clear_combo_target, width=45)
                    dpg.add_button(label="新增組合", callback=save_new_combo, width=70)
                    dpg.add_button(label="更新", callback=update_selected_combo, width=50)

                # 由 8 行加大至 12 行
                dpg.add_listbox(tag="combo_listbox", items=[], num_items=12, width=415, callback=on_combo_select)
                with dpg.group(horizontal=True):
                    b_add = dpg.add_button(label="將所選組合加入執行清單", callback=add_combo_to_steps, width=315)
                    dpg.bind_item_theme(b_add, "theme_btn_action")
                    b_del = dpg.add_button(label="刪除組合", callback=delete_selected_combo, width=90)
                    dpg.bind_item_theme(b_del, "theme_btn_danger")

        # [右欄：單獨微步 + 執行清單 + 控制]
        with dpg.child_window(width=455, height=545, border=False):
            with dpg.child_window(height=100, border=True):
                dpg.add_text("單獨新增微步 (點擊 / 按鍵 / 停頓)", color=(56, 189, 248))
                dpg.add_separator()
                dpg.add_button(label="記錄點擊坐標 (3秒)", tag="btn_add_click", callback=add_click_step, width=410)
                with dpg.group(horizontal=True):
                    dpg.add_text("按鍵:")
                    dpg.add_input_text(tag="input_key", default_value="f1", width=65)
                    dpg.add_button(label="加按鍵", callback=add_key_step, width=80)
                    dpg.add_text("停頓:")
                    dpg.add_input_text(tag="input_wait", default_value="1.0", width=45)
                    dpg.add_button(label="加停頓", callback=add_wait_step, width=80)

            dpg.add_spacer(height=2)

            with dpg.child_window(height=340, border=True):
                dpg.add_text("執行順序清單 (由上至下循環)", color=(56, 189, 248))
                dpg.add_separator()
                dpg.add_listbox(tag="step_listbox", items=[], num_items=11, width=425)
                with dpg.group(horizontal=True):
                    dpg.add_button(label="上移", callback=lambda: move_step(-1), width=95)
                    dpg.add_button(label="下移", callback=lambda: move_step(1), width=95)
                    b_del_step = dpg.add_button(label="刪除所選", callback=delete_selected, width=110)
                    dpg.bind_item_theme(b_del_step, "theme_btn_danger")
                    b_clear = dpg.add_button(label="清空清單", callback=clear_all, width=110)
                    dpg.bind_item_theme(b_clear, "theme_btn_danger")

            dpg.add_spacer(height=2)

            with dpg.group(horizontal=True):
                dpg.add_text("狀態:", color=(148, 163, 184))
                dpg.add_text("已就緒", tag="lbl_status", color=(255, 255, 255))

            btn_start = dpg.add_button(label="開始循環執行", tag="btn_toggle", callback=toggle_run, width=435, height=42)
            dpg.bind_item_theme(btn_start, "theme_btn_start")

dpg.create_viewport(
    title="水滸歷險 巨集助手", 
    width=935, 
    height=585, 
    always_on_top=True, 
    resizable=False,
    vsync=False
)
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.set_primary_window("primary_window", True)
dpg.configure_app(wait_for_input=False)

refresh_window_dropdown()
dpg.start_dearpygui()
dpg.destroy_context()