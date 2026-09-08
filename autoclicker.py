import os
import json
import time
import ctypes
from ctypes import wintypes
import pyautogui
import dearpygui.dearpygui as dpg

pyautogui.FAILSAFE = True

combos = []   # 存放定義好的技能組合庫
steps = []    # 存放主執行順序清單
temp_combo_target = None  # 記錄組合專用目標坐標

# --- Win32 後台輸入與 DPI 環境初始化 ---
IS_WINDOWS = hasattr(ctypes, "windll")
target_hwnd = None

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

if IS_WINDOWS:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    user32 = ctypes.windll.user32
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
    user32.ScreenToClient.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL

VK_MAP = {
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "tab": 0x09, "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
}
for i in range(10):
    VK_MAP[str(i)] = 0x30 + i
for c in range(ord('a'), ord('z') + 1):
    VK_MAP[chr(c)] = 0x41 + (c - ord('a'))

def check_failsafe():
    """主動檢查滑鼠是否甩至左上角"""
    try:
        pos = pyautogui.position()
        if pos.x < 20 and pos.y < 20:
            return True
    except Exception:
        pass
    return False

def get_window_list():
    if not IS_WINDOWS:
        return []
    windows = []
    
    def enum_proc(hwnd, lParam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value.strip()
                if title:
                    windows.append((hwnd, title))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    user32.EnumWindows(WNDENUMPROC(enum_proc), 0)
    return windows

def refresh_window_dropdown():
    global target_hwnd
    win_list = get_window_list()
    items = []
    target_idx = 0
    for i, (hwnd, title) in enumerate(win_list):
        items.append(f"[{hwnd}] {title}")
        if "水滸" in title or "online" in title.lower():
            target_idx = i

    if not items:
        items = ["未偵測到任何視窗 (非 Windows/Wine 環境)"]

    dpg.configure_item("combo_window_select", items=items)
    if items and items[0] != "未偵測到任何視窗 (非 Windows/Wine 環境)":
        dpg.set_value("combo_window_select", items[target_idx])
        on_window_select(None, items[target_idx])

def on_window_select(sender, app_data):
    global target_hwnd
    val = dpg.get_value("combo_window_select")
    if val and val.startswith("["):
        try:
            hwnd_str = val.split("]")[0].replace("[", "")
            target_hwnd = int(hwnd_str)
            dpg.set_value("lbl_status", f"已綁定目標視窗 HWND: {target_hwnd}")
        except Exception:
            target_hwnd = None

# --- 非阻塞 Win32 後台動作發送 ---
def post_bg_down(hwnd, cx, cy):
    lparam = ((int(cy) & 0xFFFF) << 16) | (int(cx) & 0xFFFF)
    user32.PostMessageW(hwnd, 0x0200, 0, lparam)       # WM_MOUSEMOVE
    user32.PostMessageW(hwnd, 0x0201, 0x0001, lparam)  # WM_LBUTTONDOWN

def post_bg_up(hwnd, cx, cy):
    lparam = ((int(cy) & 0xFFFF) << 16) | (int(cx) & 0xFFFF)
    user32.PostMessageW(hwnd, 0x0202, 0, lparam)       # WM_LBUTTONUP

def post_bg_key_down(hwnd, key_str):
    vk = VK_MAP.get(key_str.lower()) or (ord(key_str.upper()) if len(key_str) == 1 else None)
    if vk is not None:
        user32.PostMessageW(hwnd, 0x0100, vk, 0)       # WM_KEYDOWN

def post_bg_key_up(hwnd, key_str):
    vk = VK_MAP.get(key_str.lower()) or (ord(key_str.upper()) if len(key_str) == 1 else None)
    if vk is not None:
        user32.PostMessageW(hwnd, 0x0101, vk, 0xC0000001)  # WM_KEYUP

# --- 單線程倒數取點狀態變數 ---
countdown_active = False
countdown_type = None  # "combo" 或 "click"
countdown_end_time = 0.0
countdown_last_sec = -1
countdown_insert_at = 0

def record_combo_target():
    global countdown_active, countdown_type, countdown_end_time, countdown_last_sec
    dpg.configure_item("btn_combo_target", enabled=False)
    countdown_active = True
    countdown_type = "combo"
    countdown_end_time = time.time() + 3.0
    countdown_last_sec = -1

def clear_combo_target():
    global temp_combo_target
    temp_combo_target = None
    dpg.set_value("lbl_combo_target", "無 (原地)")
    dpg.set_value("lbl_status", "已清除目標坐標")

def get_keys_from_input(text):
    raw = text.replace("，", ",").split(",")
    return [k.strip().lower() for k in raw if k.strip()]

def update_combo_list(select_idx=None):
    items = []
    for c in combos:
        t = c.get("target")
        if t:
            t_prefix = "相對" if t.get("rel", False) else "絕對"
            t_tag = f" [{t_prefix}目標]"
        else:
            t_tag = ""
        k_str = ",".join(c.get("keys", [])).upper()
        items.append(f"{c['name']} ({k_str} / {c['wait']}s){t_tag}")
    
    dpg.configure_item("combo_listbox", items=items)
    if select_idx is not None and 0 <= select_idx < len(items):
        dpg.set_value("combo_listbox", items[select_idx])

def on_combo_select(sender, app_data):
    selected = dpg.get_value("combo_listbox")
    if not selected: return
    items = dpg.get_item_configuration("combo_listbox")["items"]
    if selected in items:
        idx = items.index(selected)
        c = combos[idx]
        dpg.set_value("input_combo_name", c["name"])
        dpg.set_value("input_combo_keys", ",".join(c["keys"]))
        dpg.set_value("input_combo_wait", str(c["wait"]))
        global temp_combo_target
        temp_combo_target = c.get("target")
        if temp_combo_target:
            prefix = "相對:" if temp_combo_target.get("rel", False) else "絕對:"
            dpg.set_value("lbl_combo_target", f"{prefix}({temp_combo_target['x']}, {temp_combo_target['y']})")
        else:
            dpg.set_value("lbl_combo_target", "無 (原地)")

def save_new_combo():
    name = dpg.get_value("input_combo_name").strip()
    if not name:
        dpg.set_value("lbl_status", "請輸入組合名稱！")
        return
    keys = get_keys_from_input(dpg.get_value("input_combo_keys"))
    if not keys:
        dpg.set_value("lbl_status", "請至少輸入一個按鍵！")
        return
    try:
        wait_sec = float(dpg.get_value("input_combo_wait"))
        if wait_sec < 0: raise ValueError
    except ValueError:
        dpg.set_value("lbl_status", "CD等待時間請填大於或等於 0 的數字")
        return

    new_c = {
        "name": name,
        "keys": keys,
        "wait": wait_sec,
        "target": dict(temp_combo_target) if temp_combo_target else None
    }
    combos.append(new_c)
    update_combo_list(select_idx=len(combos)-1)
    dpg.set_value("lbl_status", f"已建立新組合：[{name}]")

def update_selected_combo():
    selected = dpg.get_value("combo_listbox")
    if not selected:
        dpg.set_value("lbl_status", "請先在清單點選要修改的組合！")
        return
    items = dpg.get_item_configuration("combo_listbox")["items"]
    if selected in items:
        idx = items.index(selected)
        old_name = combos[idx]["name"]
        name = dpg.get_value("input_combo_name").strip()
        keys = get_keys_from_input(dpg.get_value("input_combo_keys"))
        try:
            wait_sec = float(dpg.get_value("input_combo_wait"))
            if wait_sec < 0: raise ValueError
        except ValueError:
            return

        new_target = dict(temp_combo_target) if temp_combo_target else None

        combos[idx] = {
            "name": name,
            "keys": keys,
            "wait": wait_sec,
            "target": new_target
        }
        update_combo_list(select_idx=idx)

        sync_count = 0
        for s in steps:
            if s.get("type") == "combo" and s.get("name") == old_name:
                s["name"] = name
                s["keys"] = list(keys)
                s["wait"] = wait_sec
                s["target"] = dict(new_target) if new_target else None
                sync_count += 1

        if sync_count > 0:
            update_step_list()

        dpg.set_value("lbl_status", f"已更新組合 [{name}]，並同步刷新清單內 {sync_count} 個步驟！")

def delete_selected_combo():
    selected = dpg.get_value("combo_listbox")
    if not selected: return
    items = dpg.get_item_configuration("combo_listbox")["items"]
    if selected in items:
        idx = items.index(selected)
        del combos[idx]
        update_combo_list()
        dpg.set_value("lbl_status", "已刪除該組合 (執行清單保留原有步驟)")

def add_combo_to_steps():
    selected = dpg.get_value("combo_listbox")
    c_data = None
    if selected:
        items = dpg.get_item_configuration("combo_listbox")["items"]
        if selected in items:
            c_data = combos[items.index(selected)]
    
    if not c_data:
        name = dpg.get_value("input_combo_name").strip()
        keys = get_keys_from_input(dpg.get_value("input_combo_keys"))
        try:
            wait_sec = float(dpg.get_value("input_combo_wait"))
        except ValueError:
            wait_sec = 1.0
        if name and keys:
            c_data = {"name": name, "keys": keys, "wait": wait_sec, "target": temp_combo_target}

    if not c_data:
        dpg.set_value("lbl_status", "請先選擇或填寫組合內容！")
        return

    insert_at = get_insert_index()
    step = {
        "type": "combo",
        "name": c_data["name"],
        "keys": list(c_data["keys"]),
        "wait": c_data["wait"],
        "target": dict(c_data["target"]) if c_data.get("target") else None
    }
    steps.insert(insert_at, step)
    update_step_list(select_idx=insert_at)
    dpg.set_value("lbl_status", f"已加入清單 #{insert_at+1}: [{c_data['name']}]")

# --- 主步驟清單與單步邏輯 ---
def get_insert_index():
    selected = dpg.get_value("step_listbox")
    if not selected: return len(steps)
    try:
        idx = int(selected.split(" ")[0].replace("#", "")) - 1
        if 0 <= idx < len(steps): return idx + 1
    except Exception:
        pass
    return len(steps)

def update_step_list(select_idx=None):
    items = []
    for i, s in enumerate(steps):
        if s["type"] == "click":
            prefix = "相對:" if s.get("rel", False) else "絕對:"
            items.append(f"#{i+1:02d}  [點擊] -> {prefix}({s['x']}, {s['y']})")
        elif s["type"] == "key":
            items.append(f"#{i+1:02d}  [按鍵] -> [ {s['key'].upper()} ]")
        elif s["type"] == "wait":
            items.append(f"#{i+1:02d}  [停頓] -> {s['sec']} 秒")
        elif s["type"] == "combo":
            t = s.get("target")
            if t:
                prefix = "相對:" if t.get("rel", False) else "絕對:"
                t_str = f"[{prefix}({t['x']},{t['y']})] "
            else:
                t_str = ""
            k_str = ",".join(s.get("keys", []))
            items.append(f"#{i+1:02d}  [{s['name']}] {t_str}[{k_str.upper()}] [CD:{s['wait']}s]")
    dpg.configure_item("step_listbox", items=items)
    if select_idx is not None and 0 <= select_idx < len(items):
        dpg.set_value("step_listbox", items[select_idx])

def add_click_step():
    global countdown_active, countdown_type, countdown_end_time, countdown_last_sec, countdown_insert_at
    dpg.configure_item("btn_add_click", enabled=False)
    countdown_active = True
    countdown_type = "click"
    countdown_end_time = time.time() + 3.0
    countdown_last_sec = -1
    countdown_insert_at = get_insert_index()

def add_key_step():
    key = dpg.get_value("input_key").strip().lower()
    if not key: return
    insert_at = get_insert_index()
    steps.insert(insert_at, {"type": "key", "key": key})
    update_step_list(select_idx=insert_at)
    dpg.set_value("lbl_status", f"已插入按鍵到 #{insert_at+1}：[{key.upper()}]")

def add_wait_step():
    try:
        sec = float(dpg.get_value("input_wait"))
        if sec <= 0: raise ValueError
    except ValueError: return
    insert_at = get_insert_index()
    steps.insert(insert_at, {"type": "wait", "sec": sec})
    update_step_list(select_idx=insert_at)
    dpg.set_value("lbl_status", f"已插入等待到 #{insert_at+1}：{sec} 秒")

def move_up():
    selected = dpg.get_value("step_listbox")
    if not selected: return
    try:
        idx = int(selected.split(" ")[0].replace("#", "")) - 1
        if idx > 0:
            steps[idx - 1], steps[idx] = steps[idx], steps[idx - 1]
            update_step_list(select_idx=idx - 1)
    except Exception: pass

def move_down():
    selected = dpg.get_value("step_listbox")
    if not selected: return
    try:
        idx = int(selected.split(" ")[0].replace("#", "")) - 1
        if 0 <= idx < len(steps) - 1:
            steps[idx + 1], steps[idx] = steps[idx], steps[idx + 1]
            update_step_list(select_idx=idx + 2)
    except Exception: pass

def delete_selected():
    selected = dpg.get_value("step_listbox")
    if not selected: return
    try:
        idx = int(selected.split(" ")[0].replace("#", "")) - 1
        if 0 <= idx < len(steps):
            del steps[idx]
            new_sel = idx if idx < len(steps) else (idx - 1 if idx - 1 >= 0 else None)
            update_step_list(select_idx=new_sel)
    except Exception: pass

def clear_all():
    steps.clear()
    update_step_list()
    dpg.set_value("lbl_status", "已清空執行清單")

# --- 存檔與讀檔 ---
def save_config():
    filename = dpg.get_value("input_config_name").strip() or "macro_config.json"
    if not filename.endswith(".json"): filename += ".json"
    data = {"combos": combos, "steps": steps}
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        dpg.set_value("lbl_status", f"已成功儲存至 {filename}")
    except Exception as e:
        dpg.set_value("lbl_status", f"儲存失敗: {str(e)}")

def load_config():
    filename = dpg.get_value("input_config_name").strip() or "macro_config.json"
    if not filename.endswith(".json"): filename += ".json"
    if not os.path.exists(filename):
        dpg.set_value("lbl_status", f"找不到檔案：{filename}")
        return
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            combos.clear()
            combos.extend(data.get("combos", []))
            steps.clear()
            steps.extend(data.get("steps", []))
        elif isinstance(data, list):
            steps.clear()
            steps.extend(data)
        update_combo_list()
        update_step_list()
        dpg.set_value("lbl_status", f"成功載入設定檔：{filename}")
    except Exception as e:
        dpg.set_value("lbl_status", f"載入失敗: {str(e)}")

# ================= 單線程非阻塞狀態機（State Machine） =================
macro_running = False
round_idx = 1
cur_step_idx = 0
cur_substate = 0
combo_key_idx = 0
next_action_time = 0.0
cached_click_pos = (0, 0)

def toggle_run():
    global macro_running, round_idx, cur_step_idx, cur_substate, combo_key_idx, next_action_time
    if not macro_running:
        if not steps:
            dpg.set_value("lbl_status", "執行清單是空的，請先加入步驟！")
            return
        macro_running = True
        round_idx = 1
        cur_step_idx = 0
        cur_substate = 0
        combo_key_idx = 0
        next_action_time = 0.0
        dpg.configure_item("btn_toggle", label="停止執行 (或甩滑鼠至左上角)")
        dpg.bind_item_theme("btn_toggle", "theme_btn_stop")
        dpg.set_value("lbl_status", "狀態：循環運作中...")
    else:
        stop_macro("狀態：已手動停止")

def stop_macro(reason=None):
    global macro_running
    macro_running = False
    dpg.configure_item("btn_toggle", label="開始循環執行")
    dpg.bind_item_theme("btn_toggle", "theme_btn_start")
    if reason:
        dpg.set_value("lbl_status", reason)

def process_macro_tick(now):
    """主線程巨集步進狀態機，絕不阻擋 UI 繪製"""
    global macro_running, round_idx, cur_step_idx, cur_substate, combo_key_idx, next_action_time, cached_click_pos

    if cur_step_idx >= len(steps):
        cur_step_idx = 0
        round_idx += 1
        cur_substate = 0
        combo_key_idx = 0
        next_action_time = now + 0.05
        return

    step = steps[cur_step_idx]

    # 每步開始時高亮游標
    if cur_substate == 0 and combo_key_idx == 0:
        list_items = dpg.get_item_configuration("step_listbox").get("items", [])
        if 0 <= cur_step_idx < len(list_items):
            dpg.set_value("step_listbox", list_items[cur_step_idx])

    use_bg = dpg.get_value("chk_use_bg") and IS_WINDOWS and (target_hwnd is not None)
    try:
        offset_x = int(dpg.get_value("input_offset_x") or 0)
        offset_y = int(dpg.get_value("input_offset_y") or 0)
    except Exception:
        offset_x, offset_y = 0, 0

    stype = step["type"]

    # 1. 點擊步驟
    if stype == "click":
        if cur_substate == 0:
            is_rel = step.get("rel", False)
            if use_bg:
                if is_rel:
                    cx = step["x"] + offset_x
                    cy = step["y"] + offset_y
                else:
                    pt = POINT(int(step["x"]), int(step["y"]))
                    user32.ScreenToClient(target_hwnd, ctypes.byref(pt))
                    cx = pt.x + offset_x
                    cy = pt.y + offset_y
                post_bg_down(target_hwnd, cx, cy)
                cached_click_pos = (cx, cy)
                dpg.set_value("lbl_status", f"第 {round_idx} 輪 ({cur_step_idx+1}/{len(steps)}): 後台點擊相對:({cx},{cy})")
            else:
                if is_rel and IS_WINDOWS and target_hwnd:
                    pt = POINT(int(step["x"]), int(step["y"]))
                    user32.ClientToScreen(target_hwnd, ctypes.byref(pt))
                    pyautogui.mouseDown(pt.x, pt.y)
                    dpg.set_value("lbl_status", f"第 {round_idx} 輪: 前台追蹤點擊 ({pt.x},{pt.y})")
                else:
                    pyautogui.mouseDown(step["x"], step["y"])
                    dpg.set_value("lbl_status", f"第 {round_idx} 輪: 前台點擊 ({step['x']},{step['y']})")
            next_action_time = now + 0.08
            cur_substate = 1

        elif cur_substate == 1:
            if use_bg:
                post_bg_up(target_hwnd, cached_click_pos[0], cached_click_pos[1])
            else:
                pyautogui.mouseUp()
            next_action_time = now + 0.12
            cur_step_idx += 1
            cur_substate = 0

    # 2. 按鍵步驟
    elif stype == "key":
        k = step["key"]
        if cur_substate == 0:
            if use_bg:
                post_bg_key_down(target_hwnd, k)
            else:
                pyautogui.keyDown(k)
            dpg.set_value("lbl_status", f"第 {round_idx} 輪 ({cur_step_idx+1}/{len(steps)}): 按鍵 [{k.upper()}]")
            next_action_time = now + 0.06
            cur_substate = 1

        elif cur_substate == 1:
            if use_bg:
                post_bg_key_up(target_hwnd, k)
            else:
                pyautogui.keyUp(k)
            next_action_time = now + 0.10
            cur_step_idx += 1
            cur_substate = 0

    # 3. 停頓步驟
    elif stype == "wait":
        dpg.set_value("lbl_status", f"第 {round_idx} 輪 ({cur_step_idx+1}/{len(steps)}): 等待 {step['sec']} 秒")
        next_action_time = now + float(step["sec"])
        cur_step_idx += 1
        cur_substate = 0

    # 4. 技能組合步驟
    elif stype == "combo":
        # 4-1. 目標點擊 (若有)
        if cur_substate == 0:
            if step.get("target"):
                t = step["target"]
                is_rel = t.get("rel", False)
                if use_bg:
                    if is_rel:
                        cx = t["x"] + offset_x
                        cy = t["y"] + offset_y
                    else:
                        pt = POINT(int(t["x"]), int(t["y"]))
                        user32.ScreenToClient(target_hwnd, ctypes.byref(pt))
                        cx = pt.x + offset_x
                        cy = pt.y + offset_y
                    post_bg_down(target_hwnd, cx, cy)
                    cached_click_pos = (cx, cy)
                    dpg.set_value("lbl_status", f"第 {round_idx} 輪: 組合[{step['name']}] 相對點擊:({cx},{cy})")
                else:
                    if is_rel and IS_WINDOWS and target_hwnd:
                        pt = POINT(int(t["x"]), int(t["y"]))
                        user32.ClientToScreen(target_hwnd, ctypes.byref(pt))
                        pyautogui.mouseDown(pt.x, pt.y)
                    else:
                        pyautogui.mouseDown(t["x"], t["y"])
                next_action_time = now + 0.08
                cur_substate = 1
            else:
                cur_substate = 2
                combo_key_idx = 0

        elif cur_substate == 1:
            if use_bg:
                post_bg_up(target_hwnd, cached_click_pos[0], cached_click_pos[1])
            else:
                pyautogui.mouseUp()
            next_action_time = now + 0.12
            cur_substate = 2
            combo_key_idx = 0

        # 4-2. 技能按鍵隊列
        elif cur_substate == 2:
            keys = step.get("keys", [])
            if combo_key_idx < len(keys):
                k = keys[combo_key_idx]
                if use_bg:
                    post_bg_key_down(target_hwnd, k)
                else:
                    pyautogui.keyDown(k)
                next_action_time = now + 0.06
                cur_substate = 3
            else:
                # 按鍵放完，進入 CD 判定
                cur_substate = 4

        elif cur_substate == 3:
            keys = step.get("keys", [])
            k = keys[combo_key_idx]
            if use_bg:
                post_bg_key_up(target_hwnd, k)
            else:
                pyautogui.keyUp(k)
            combo_key_idx += 1
            next_action_time = now + 0.15
            cur_substate = 2

        # 4-3. CD 等待
        elif cur_substate == 4:
            cd_wait = float(step.get("wait", 0))
            if cd_wait > 0:
                dpg.set_value("lbl_status", f"第 {round_idx} 輪: 組合[{step['name']}] CD等待 {cd_wait}s")
            next_action_time = now + cd_wait
            cur_step_idx += 1
            cur_substate = 0
            combo_key_idx = 0

# --- UI 構建與樣式客製化 ---
dpg.create_context()

windir = os.environ.get("WINDIR", "C:\\Windows")
candidate_fonts = [
    os.path.join(windir, "Fonts", "msjh.ttc"),
    os.path.join(windir, "Fonts", "msjhbd.ttc"),
    os.path.join(windir, "Fonts", "msyh.ttc"),
    os.path.join(windir, "Fonts", "mingliu.ttc"),
    "C:\\Windows\\Fonts\\msjh.ttc",
    "C:\\Windows\\Fonts\\msyh.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]
selected_font = next((f for f in candidate_fonts if os.path.exists(f)), None)
if selected_font:
    with dpg.font_registry():
        with dpg.font(selected_font, 14) as default_font:
            dpg.add_font_range_hint(dpg.mvFontRangeHint_Chinese_Full)
        dpg.bind_font(default_font)

with dpg.theme() as global_theme:
    with dpg.theme_component(dpg.mvAll):
        dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 10, 10)
        dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 7, 5)
        dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 7, 6)
        dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 5)
        dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 6)

        dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (21, 23, 28, 255))
        dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (28, 31, 38, 255))
        dpg.add_theme_color(dpg.mvThemeCol_Border, (44, 49, 60, 255))
        dpg.add_theme_color(dpg.mvThemeCol_Text, (241, 245, 249, 255))
        dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (37, 41, 50, 255))
        dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (47, 53, 66, 255))
        dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, (55, 62, 77, 255))
        dpg.add_theme_color(dpg.mvThemeCol_Button, (41, 46, 56, 255))
        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (56, 63, 77, 255))
        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (71, 80, 98, 255))
        dpg.add_theme_color(dpg.mvThemeCol_Header, (37, 99, 235, 160))
        dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (37, 99, 235, 220))
        dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (29, 78, 216, 255))

dpg.bind_theme(global_theme)

with dpg.theme(tag="theme_btn_action"):
    with dpg.theme_component(dpg.mvButton):
        dpg.add_theme_color(dpg.mvThemeCol_Button, (2, 132, 199, 220))
        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (14, 165, 233, 255))
        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (3, 105, 161, 255))

with dpg.theme(tag="theme_btn_danger"):
    with dpg.theme_component(dpg.mvButton):
        dpg.add_theme_color(dpg.mvThemeCol_Button, (185, 28, 28, 180))
        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (220, 38, 38, 255))
        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (153, 27, 27, 255))

with dpg.theme(tag="theme_btn_start"):
    with dpg.theme_component(dpg.mvButton):
        dpg.add_theme_color(dpg.mvThemeCol_Button, (22, 163, 74, 255))
        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (34, 197, 94, 255))
        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (21, 128, 61, 255))

with dpg.theme(tag="theme_btn_stop"):
    with dpg.theme_component(dpg.mvButton):
        dpg.add_theme_color(dpg.mvThemeCol_Button, (220, 38, 38, 255))
        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (239, 68, 68, 255))
        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (185, 28, 28, 255))

# ================= 主介面排版 =================
with dpg.window(tag="primary_window"):
    with dpg.group(horizontal=True):
        
        # [左欄：設定檔 + 技能組合庫]
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

            with dpg.child_window(height=385, border=True):
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

                dpg.add_listbox(tag="combo_listbox", items=[], num_items=8, width=415, callback=on_combo_select)

                with dpg.group(horizontal=True):
                    b_add = dpg.add_button(label="將所選組合加入執行清單", callback=add_combo_to_steps, width=315)
                    dpg.bind_item_theme(b_add, "theme_btn_action")
                    b_del = dpg.add_button(label="刪除組合", callback=delete_selected_combo, width=90)
                    dpg.bind_item_theme(b_del, "theme_btn_danger")

        # [右欄：單獨微步 + 執行順序清單 + 控制]
        with dpg.child_window(width=455, height=545, border=False):
            
            with dpg.child_window(height=100, border=True):
                dpg.add_text("單獨新增微步 (點擊 / 按鍵 / 停頓)", color=(56, 189, 248))
                dpg.add_separator()
                with dpg.group(horizontal=True):
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
                    dpg.add_button(label="上移", callback=move_up, width=95)
                    dpg.add_button(label="下移", callback=move_down, width=95)
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

dpg.create_viewport(title="水滸歷險 巨集助手", width=935, height=585, always_on_top=True, resizable=False)
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.set_primary_window("primary_window", True)

refresh_window_dropdown()

# ================= 單線程純主循環 (零 Background Thread) =================
while dpg.is_dearpygui_running():
    now = time.time()

    # 1. 主線程處理 3 秒倒數取點
    if countdown_active:
        rem = countdown_end_time - now
        if rem > 0:
            sec = int(rem) + 1
            if sec != countdown_last_sec:
                countdown_last_sec = sec
                dpg.set_value("lbl_status", f"請移至目標點... 倒數 {sec} 秒")
        else:
            countdown_active = False
            pos = pyautogui.position()
            use_rel = dpg.get_value("chk_use_relative")

            if countdown_type == "combo":
                if use_rel and IS_WINDOWS and target_hwnd:
                    pt = POINT(int(pos.x), int(pos.y))
                    user32.ScreenToClient(target_hwnd, ctypes.byref(pt))
                    temp_combo_target = {"x": pt.x, "y": pt.y, "rel": True}
                    dpg.set_value("lbl_combo_target", f"相對:({pt.x}, {pt.y})")
                    dpg.set_value("lbl_status", f"已鎖定組合相對目標：({pt.x}, {pt.y})")
                else:
                    temp_combo_target = {"x": pos.x, "y": pos.y, "rel": False}
                    dpg.set_value("lbl_combo_target", f"絕對:({pos.x}, {pos.y})")
                    dpg.set_value("lbl_status", f"已鎖定組合絕對坐標：({pos.x}, {pos.y})")
                dpg.configure_item("btn_combo_target", enabled=True)

            elif countdown_type == "click":
                if use_rel and IS_WINDOWS and target_hwnd:
                    pt = POINT(int(pos.x), int(pos.y))
                    user32.ScreenToClient(target_hwnd, ctypes.byref(pt))
                    steps.insert(countdown_insert_at, {"type": "click", "x": pt.x, "y": pt.y, "rel": True})
                    update_step_list(select_idx=countdown_insert_at)
                    dpg.set_value("lbl_status", f"已插入相對點擊到 #{countdown_insert_at+1}：({pt.x}, {pt.y})")
                else:
                    steps.insert(countdown_insert_at, {"type": "click", "x": pos.x, "y": pos.y, "rel": False})
                    update_step_list(select_idx=countdown_insert_at)
                    dpg.set_value("lbl_status", f"已插入絕對點擊到 #{countdown_insert_at+1}：({pos.x}, {pos.y})")
                dpg.configure_item("btn_add_click", enabled=True)

    # 2. 主線程步進巨集狀態機
    if macro_running:
        if check_failsafe():
            stop_macro("已觸發安全停止（滑鼠甩至左上角）")
        elif now >= next_action_time:
            process_macro_tick(now)

    # 3. 渲染當前幀並控制 CPU 佔用率（5ms 微休眠）
    dpg.render_dearpygui_frame()
    time.sleep(0.005)

dpg.destroy_context()