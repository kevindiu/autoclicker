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

# ==============================================================================
# 1. UI Tags 常數宣告
# ==============================================================================
class Tags:
    PRIMARY_WINDOW = "win_primary"
    
    CFG_NAME = "input_cfg_name"
    CHK_USE_BG = "chk_use_bg"
    CHK_USE_REL = "chk_use_relative"
    OFFSET_X = "input_offset_x"
    OFFSET_Y = "input_offset_y"
    WINDOW_SELECT = "combo_window_select"
    
    COMBO_NAME = "input_combo_name"
    COMBO_KEYS = "input_combo_keys"
    COMBO_WAIT = "input_combo_wait"
    COMBO_TARGET_LBL = "lbl_combo_target"
    COMBO_TARGET_BTN = "btn_combo_target"
    COMBO_LIST = "combo_listbox"
    
    STEP_CLICK_BTN = "btn_step_add_click"
    STEP_KEY = "input_step_key"
    STEP_WAIT = "input_step_wait"
    
    STEP_LIST = "step_listbox"
    STATUS_LBL = "lbl_status"
    RUN_BTN = "btn_toggle_run"
    
    THEME_ACTION = "theme_btn_action"
    THEME_DANGER = "theme_btn_danger"
    THEME_START = "theme_btn_start"
    THEME_STOP = "theme_btn_stop"


# ==============================================================================
# 2. 核心狀態與內存快取 (Zero-Lock Memory Cache)
# ==============================================================================
combos = []
steps = []
temp_combo_target = None
running = False
stop_event = threading.Event()
worker_thread = None

# 純 Python 內存快取，避免背景線程向 DPG 索取數值造成卡死
app_state = {
    "use_bg": True,
    "use_rel": True,
    "offset_x": 0,
    "offset_y": 0,
    "target_hwnd": None,
}

IS_WINDOWS = hasattr(ctypes, "windll")

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

if IS_WINDOWS:
    try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try: ctypes.windll.user32.SetProcessDPIAware()
        except Exception: pass

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
for i in range(10): VK_MAP[str(i)] = 0x30 + i
for c in range(ord('a'), ord('z') + 1): VK_MAP[chr(c)] = 0x41 + (c - ord('a'))


# ==============================================================================
# 3. UI 集中更新輔助器
# ==============================================================================
class UI:
    @staticmethod
    def set_status(msg: str):
        try: dpg.set_value(Tags.STATUS_LBL, msg)
        except Exception: pass

    @staticmethod
    def set_running_ui(is_running: bool):
        try:
            if is_running:
                dpg.configure_item(Tags.RUN_BTN, label="停止執行 (或甩滑鼠至左上角)")
                dpg.bind_item_theme(Tags.RUN_BTN, Tags.THEME_STOP)
            else:
                dpg.configure_item(Tags.RUN_BTN, label="開始循環執行")
                dpg.bind_item_theme(Tags.RUN_BTN, Tags.THEME_START)
        except Exception: pass


def sync_ui_to_state(sender=None, app_data=None, user_data=None):
    """UI 控件變化時主動同步至 Python 內存，背景線程直接讀內存"""
    try:
        app_state["use_bg"] = dpg.get_value(Tags.CHK_USE_BG)
        app_state["use_rel"] = dpg.get_value(Tags.CHK_USE_REL)
        app_state["offset_x"] = int(dpg.get_value(Tags.OFFSET_X) or 0)
        app_state["offset_y"] = int(dpg.get_value(Tags.OFFSET_Y) or 0)
    except Exception:
        pass


# ==============================================================================
# 4. 底層輸入與背景訊號驅動
# ==============================================================================
def check_failsafe():
    try:
        pos = pyautogui.position()
        return pos.x < 25 and pos.y < 25
    except Exception:
        return False

def interruptible_sleep(seconds: float):
    end_time = time.time() + seconds
    while time.time() < end_time:
        if stop_event.is_set() or not running:
            return False
        if check_failsafe():
            stop_event.set()
            return False
        time.sleep(0.02)
    return True

def emergency_release():
    try: pyautogui.mouseUp()
    except Exception: pass
    for k in ["shift", "ctrl", "alt", "space", "enter", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12"]:
        try: pyautogui.keyUp(k)
        except Exception: pass
    target_hwnd = app_state.get("target_hwnd")
    if IS_WINDOWS and target_hwnd:
        try: user32.PostMessageW(target_hwnd, 0x0202, 0, 0)
        except Exception: pass
        for vk in VK_MAP.values():
            try: user32.PostMessageW(target_hwnd, 0x0101, vk, 0xC0000001)
            except Exception: pass

def post_bg_click(hwnd, client_x, client_y, offset_x=0, offset_y=0):
    if not IS_WINDOWS or not hwnd:
        pyautogui.click(client_x, client_y)
        return int(client_x), int(client_y)

    cx = int(client_x) + offset_x
    cy = int(client_y) + offset_y
    lparam = ((int(cy) & 0xFFFF) << 16) | (int(cx) & 0xFFFF)

    user32.PostMessageW(hwnd, 0x0200, 0, lparam)
    if not interruptible_sleep(0.02):
        user32.PostMessageW(hwnd, 0x0202, 0, lparam)
        return cx, cy

    user32.PostMessageW(hwnd, 0x0201, 0x0001, lparam)
    if not interruptible_sleep(0.06):
        user32.PostMessageW(hwnd, 0x0202, 0, lparam)
        return cx, cy

    user32.PostMessageW(hwnd, 0x0202, 0, lparam)
    return cx, cy

def post_bg_key(hwnd, key_str):
    if not IS_WINDOWS or not hwnd:
        pyautogui.keyDown(key_str)
        if not interruptible_sleep(0.05):
            try: pyautogui.keyUp(key_str)
            except Exception: pass
            return
        pyautogui.keyUp(key_str)
        return

    vk = VK_MAP.get(key_str.lower()) or (ord(key_str.upper()) if len(key_str) == 1 else None)
    if vk is not None:
        user32.PostMessageW(hwnd, 0x0100, vk, 0)
        if not interruptible_sleep(0.05):
            user32.PostMessageW(hwnd, 0x0101, vk, 0xC0000001)
            return
        user32.PostMessageW(hwnd, 0x0101, vk, 0xC0000001)

def get_window_list():
    if not IS_WINDOWS: return []
    windows = []
    def enum_proc(hwnd, lParam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value.strip()
                if title: windows.append((hwnd, title))
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    user32.EnumWindows(WNDENUMPROC(enum_proc), 0)
    return windows

def refresh_window_dropdown():
    win_list = get_window_list()
    items = []
    target_idx = 0
    for i, (hwnd, title) in enumerate(win_list):
        items.append(f"[{hwnd}] {title}")
        if "水滸" in title or "online" in title.lower(): target_idx = i

    if not items:
        items = ["未偵測到任何視窗 (非 Windows/Wine 環境)"]

    dpg.configure_item(Tags.WINDOW_SELECT, items=items)
    if items and items[0] != "未偵測到任何視窗 (非 Windows/Wine 環境)":
        dpg.set_value(Tags.WINDOW_SELECT, items[target_idx])
        on_window_select(None, items[target_idx])

def on_window_select(sender, app_data):
    val = dpg.get_value(Tags.WINDOW_SELECT)
    if val and val.startswith("["):
        try:
            hwnd_str = val.split("]")[0].replace("[", "")
            app_state["target_hwnd"] = int(hwnd_str)
            UI.set_status(f"已綁定目標視窗 HWND: {app_state['target_hwnd']}")
        except Exception:
            app_state["target_hwnd"] = None


# ==============================================================================
# 5. 組合庫與步驟清單操作邏輯
# ==============================================================================
def countdown_combo_worker():
    dpg.configure_item(Tags.COMBO_TARGET_BTN, enabled=False)
    for i in range(3, 0, -1):
        UI.set_status(f"請移至施法目標... 倒數 {i} 秒")
        time.sleep(1)
    pos = pyautogui.position()
    global temp_combo_target
    
    target_hwnd = app_state.get("target_hwnd")
    use_rel = app_state.get("use_rel", True)
    if use_rel and IS_WINDOWS and target_hwnd:
        pt = POINT(int(pos.x), int(pos.y))
        user32.ScreenToClient(target_hwnd, ctypes.byref(pt))
        temp_combo_target = {"x": pt.x, "y": pt.y, "rel": True}
        dpg.set_value(Tags.COMBO_TARGET_LBL, f"相對:({pt.x}, {pt.y})")
        UI.set_status(f"已鎖定組合相對目標：({pt.x}, {pt.y})")
    else:
        temp_combo_target = {"x": pos.x, "y": pos.y, "rel": False}
        dpg.set_value(Tags.COMBO_TARGET_LBL, f"絕對:({pos.x}, {pos.y})")
        UI.set_status(f"已鎖定組合絕對坐標：({pos.x}, {pos.y})")
    dpg.configure_item(Tags.COMBO_TARGET_BTN, enabled=True)

def record_combo_target():
    threading.Thread(target=countdown_combo_worker, daemon=True).start()

def clear_combo_target():
    global temp_combo_target
    temp_combo_target = None
    dpg.set_value(Tags.COMBO_TARGET_LBL, "無 (原地)")
    UI.set_status("已清除目標坐標")

def get_keys_from_input(text):
    raw = text.replace("，", ",").split(",")
    return [k.strip().lower() for k in raw if k.strip()]

def update_combo_list(select_idx=None):
    items = []
    for c in combos:
        t = c.get("target")
        t_tag = f" [{'相對' if t.get('rel', False) else '絕對'}目標]" if t else ""
        k_str = ",".join(c.get("keys", [])).upper()
        items.append(f"{c['name']} ({k_str} / {c['wait']}s){t_tag}")
    
    dpg.configure_item(Tags.COMBO_LIST, items=items)
    if select_idx is not None and 0 <= select_idx < len(items):
        dpg.set_value(Tags.COMBO_LIST, items[select_idx])

def on_combo_select(sender, app_data):
    selected = dpg.get_value(Tags.COMBO_LIST)
    if not selected: return
    items = dpg.get_item_configuration(Tags.COMBO_LIST)["items"]
    if selected in items:
        idx = items.index(selected)
        c = combos[idx]
        dpg.set_value(Tags.COMBO_NAME, c["name"])
        dpg.set_value(Tags.COMBO_KEYS, ",".join(c["keys"]))
        dpg.set_value(Tags.COMBO_WAIT, str(c["wait"]))
        global temp_combo_target
        temp_combo_target = c.get("target")
        if temp_combo_target:
            prefix = "相對:" if temp_combo_target.get("rel", False) else "絕對:"
            dpg.set_value(Tags.COMBO_TARGET_LBL, f"{prefix}({temp_combo_target['x']}, {temp_combo_target['y']})")
        else:
            dpg.set_value(Tags.COMBO_TARGET_LBL, "無 (原地)")

def save_new_combo():
    name = dpg.get_value(Tags.COMBO_NAME).strip()
    if not name:
        UI.set_status("請輸入組合名稱！")
        return
    keys = get_keys_from_input(dpg.get_value(Tags.COMBO_KEYS))
    if not keys:
        UI.set_status("請至少輸入一個按鍵！")
        return
    try:
        wait_sec = float(dpg.get_value(Tags.COMBO_WAIT))
        if wait_sec < 0: raise ValueError
    except ValueError:
        UI.set_status("CD等待時間請填大於或等於 0 的數字")
        return

    combos.append({
        "name": name,
        "keys": keys,
        "wait": wait_sec,
        "target": dict(temp_combo_target) if temp_combo_target else None
    })
    update_combo_list(select_idx=len(combos)-1)
    UI.set_status(f"已建立新組合：[{name}]")

def update_selected_combo():
    selected = dpg.get_value(Tags.COMBO_LIST)
    if not selected:
        UI.set_status("請先在清單點選要修改的組合！")
        return
    items = dpg.get_item_configuration(Tags.COMBO_LIST)["items"]
    if selected in items:
        idx = items.index(selected)
        old_name = combos[idx]["name"]
        name = dpg.get_value(Tags.COMBO_NAME).strip()
        keys = get_keys_from_input(dpg.get_value(Tags.COMBO_KEYS))
        try:
            wait_sec = float(dpg.get_value(Tags.COMBO_WAIT))
            if wait_sec < 0: raise ValueError
        except ValueError:
            return

        new_target = dict(temp_combo_target) if temp_combo_target else None
        combos[idx] = {"name": name, "keys": keys, "wait": wait_sec, "target": new_target}
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

        UI.set_status(f"已更新組合 [{name}]，並同步刷新清單內 {sync_count} 個步驟！")

def delete_selected_combo():
    selected = dpg.get_value(Tags.COMBO_LIST)
    if not selected: return
    items = dpg.get_item_configuration(Tags.COMBO_LIST)["items"]
    if selected in items:
        del combos[items.index(selected)]
        update_combo_list()
        UI.set_status("已刪除該組合 (執行清單保留原有步驟)")

def get_insert_index():
    selected = dpg.get_value(Tags.STEP_LIST)
    if not selected: return len(steps)
    try:
        idx = int(selected.split(" ")[0].replace("#", "")) - 1
        if 0 <= idx < len(steps): return idx + 1
    except Exception: pass
    return len(steps)

def add_combo_to_steps():
    selected = dpg.get_value(Tags.COMBO_LIST)
    c_data = None
    if selected:
        items = dpg.get_item_configuration(Tags.COMBO_LIST)["items"]
        if selected in items:
            c_data = combos[items.index(selected)]
    
    if not c_data:
        name = dpg.get_value(Tags.COMBO_NAME).strip()
        keys = get_keys_from_input(dpg.get_value(Tags.COMBO_KEYS))
        try: wait_sec = float(dpg.get_value(Tags.COMBO_WAIT))
        except ValueError: wait_sec = 1.0
        if name and keys:
            c_data = {"name": name, "keys": keys, "wait": wait_sec, "target": temp_combo_target}

    if not c_data:
        UI.set_status("請先選擇或填寫組合內容！")
        return

    insert_at = get_insert_index()
    steps.insert(insert_at, {
        "type": "combo",
        "name": c_data["name"],
        "keys": list(c_data["keys"]),
        "wait": c_data["wait"],
        "target": dict(c_data["target"]) if c_data.get("target") else None
    })
    update_step_list(select_idx=insert_at)
    UI.set_status(f"已加入清單 #{insert_at+1}: [{c_data['name']}]")

def generate_step_display_list():
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
            t_str = f"[{'相對:' if t.get('rel', False) else '絕對:'}({t['x']},{t['y']})] " if t else ""
            k_str = ",".join(s.get("keys", []))
            items.append(f"#{i+1:02d}  [{s['name']}] {t_str}[{k_str.upper()}] [CD:{s['wait']}s]")
    return items

def update_step_list(select_idx=None):
    items = generate_step_display_list()
    dpg.configure_item(Tags.STEP_LIST, items=items)
    if select_idx is not None and 0 <= select_idx < len(items):
        dpg.set_value(Tags.STEP_LIST, items[select_idx])

def countdown_click_worker(insert_at):
    dpg.configure_item(Tags.STEP_CLICK_BTN, enabled=False)
    for i in range(3, 0, -1):
        UI.set_status(f"請移至目標點... 倒數 {i} 秒")
        time.sleep(1)
    pos = pyautogui.position()
    
    target_hwnd = app_state.get("target_hwnd")
    use_rel = app_state.get("use_rel", True)
    if use_rel and IS_WINDOWS and target_hwnd:
        pt = POINT(int(pos.x), int(pos.y))
        user32.ScreenToClient(target_hwnd, ctypes.byref(pt))
        steps.insert(insert_at, {"type": "click", "x": pt.x, "y": pt.y, "rel": True})
        update_step_list(select_idx=insert_at)
        UI.set_status(f"已插入相對點擊到 #{insert_at+1}：({pt.x}, {pt.y})")
    else:
        steps.insert(insert_at, {"type": "click", "x": pos.x, "y": pos.y, "rel": False})
        update_step_list(select_idx=insert_at)
        UI.set_status(f"已插入絕對點擊到 #{insert_at+1}：({pos.x}, {pos.y})")
    dpg.configure_item(Tags.STEP_CLICK_BTN, enabled=True)

def add_click_step():
    threading.Thread(target=countdown_click_worker, args=(get_insert_index(),), daemon=True).start()

def add_key_step():
    key = dpg.get_value(Tags.STEP_KEY).strip().lower()
    if not key: return
    insert_at = get_insert_index()
    steps.insert(insert_at, {"type": "key", "key": key})
    update_step_list(select_idx=insert_at)
    UI.set_status(f"已插入按鍵到 #{insert_at+1}：[{key.upper()}]")

def add_wait_step():
    try:
        sec = float(dpg.get_value(Tags.STEP_WAIT))
        if sec <= 0: raise ValueError
    except ValueError: return
    insert_at = get_insert_index()
    steps.insert(insert_at, {"type": "wait", "sec": sec})
    update_step_list(select_idx=insert_at)
    UI.set_status(f"已插入等待到 #{insert_at+1}：{sec} 秒")

def move_up():
    selected = dpg.get_value(Tags.STEP_LIST)
    if not selected: return
    try:
        idx = int(selected.split(" ")[0].replace("#", "")) - 1
        if idx > 0:
            steps[idx - 1], steps[idx] = steps[idx], steps[idx - 1]
            update_step_list(select_idx=idx - 1)
    except Exception: pass

def move_down():
    selected = dpg.get_value(Tags.STEP_LIST)
    if not selected: return
    try:
        idx = int(selected.split(" ")[0].replace("#", "")) - 1
        if 0 <= idx < len(steps) - 1:
            steps[idx + 1], steps[idx] = steps[idx], steps[idx + 1]
            update_step_list(select_idx=idx + 2)
    except Exception: pass

def delete_selected():
    selected = dpg.get_value(Tags.STEP_LIST)
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
    UI.set_status("已清空執行清單")

def save_config():
    filename = dpg.get_value(Tags.CFG_NAME).strip() or "macro_config.json"
    if not filename.endswith(".json"): filename += ".json"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump({"combos": combos, "steps": steps}, f, ensure_ascii=False, indent=2)
        UI.set_status(f"已成功儲存至 {filename}")
    except Exception as e:
        UI.set_status(f"儲存失敗: {str(e)}")

def load_config():
    filename = dpg.get_value(Tags.CFG_NAME).strip() or "macro_config.json"
    if not filename.endswith(".json"): filename += ".json"
    if not os.path.exists(filename):
        UI.set_status(f"找不到檔案：{filename}")
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
        UI.set_status(f"成功載入設定檔：{filename}")
    except Exception as e:
        UI.set_status(f"載入失敗: {str(e)}")


# ==============================================================================
# 6. 非同步無阻塞執行引擎 (Zero-Lock Engine)
# ==============================================================================
def toggle_run():
    global running, worker_thread
    if running:
        # 非阻塞停止：發送信號並瞬間交還控制權，完全不 join() 卡死 UI
        running = False
        stop_event.set()
        emergency_release()
        UI.set_running_ui(False)
        UI.set_status("狀態：已手動停止")
    else:
        if not steps:
            UI.set_status("執行清單是空的，請先加入步驟！")
            return

        sync_ui_to_state()
        emergency_release()
        stop_event.clear()
        running = True
        UI.set_running_ui(True)
        UI.set_status("狀態：循環運作中...")
        worker_thread = threading.Thread(target=macro_worker_loop, daemon=True)
        worker_thread.start()

def macro_worker_loop():
    global running
    round_idx = 1
    stopped_by_failsafe = False
    display_items = generate_step_display_list()
    last_highlight_idx = -1

    try:
        while running and not stop_event.is_set():
            # 直接讀取 Python 字典，0 次 DPG 跨線程呼叫
            use_bg = app_state["use_bg"] and IS_WINDOWS and (app_state["target_hwnd"] is not None)
            target_hwnd = app_state["target_hwnd"]
            offset_x = app_state["offset_x"]
            offset_y = app_state["offset_y"]

            for idx, step in enumerate(steps):
                if stop_event.is_set() or not running: break
                if check_failsafe():
                    stopped_by_failsafe = True
                    stop_event.set()
                    break

                # 只有步驟真正推進時才更新一次 Listbox，杜絕高頻搶 Lock
                if idx != last_highlight_idx and 0 <= idx < len(display_items):
                    try:
                        dpg.set_value(Tags.STEP_LIST, display_items[idx])
                        last_highlight_idx = idx
                    except Exception: pass

                stype = step["type"]
                if stype == "click":
                    is_rel = step.get("rel", False)
                    if use_bg:
                        if is_rel:
                            cx, cy = post_bg_click(target_hwnd, step["x"], step["y"], offset_x, offset_y)
                        else:
                            pt = POINT(int(step["x"]), int(step["y"]))
                            user32.ScreenToClient(target_hwnd, ctypes.byref(pt))
                            cx, cy = post_bg_click(target_hwnd, pt.x, pt.y, offset_x, offset_y)
                        UI.set_status(f"第 {round_idx} 輪 ({idx+1}/{len(steps)}): 後台點擊相對:({cx},{cy})")
                    else:
                        if is_rel and IS_WINDOWS and target_hwnd:
                            pt = POINT(int(step["x"]), int(step["y"]))
                            user32.ClientToScreen(target_hwnd, ctypes.byref(pt))
                            pyautogui.click(pt.x, pt.y)
                            UI.set_status(f"第 {round_idx} 輪: 前台追蹤點擊 ({pt.x},{pt.y})")
                        else:
                            pyautogui.click(step["x"], step["y"])
                            UI.set_status(f"第 {round_idx} 輪: 前台點擊 ({step['x']},{step['y']})")
                    if not interruptible_sleep(0.12): break

                elif stype == "key":
                    if use_bg:
                        post_bg_key(target_hwnd, step["key"])
                    else:
                        pyautogui.keyDown(step["key"])
                        if not interruptible_sleep(0.05):
                            try: pyautogui.keyUp(step["key"])
                            except Exception: pass
                            break
                        pyautogui.keyUp(step["key"])
                    UI.set_status(f"第 {round_idx} 輪 ({idx+1}/{len(steps)}): 按鍵 [{step['key'].upper()}]")
                    if not interruptible_sleep(0.10): break

                elif stype == "wait":
                    if not interruptible_sleep(float(step["sec"])): break

                elif stype == "combo":
                    if step.get("target"):
                        t = step["target"]
                        is_rel = t.get("rel", False)
                        if use_bg:
                            if is_rel:
                                cx, cy = post_bg_click(target_hwnd, t["x"], t["y"], offset_x, offset_y)
                            else:
                                pt = POINT(int(t["x"]), int(t["y"]))
                                user32.ScreenToClient(target_hwnd, ctypes.byref(pt))
                                cx, cy = post_bg_click(target_hwnd, pt.x, pt.y, offset_x, offset_y)
                            UI.set_status(f"第 {round_idx} 輪: 組合[{step['name']}] 後台點擊:({cx},{cy})")
                        else:
                            if is_rel and IS_WINDOWS and target_hwnd:
                                pt = POINT(int(t["x"]), int(t["y"]))
                                user32.ClientToScreen(target_hwnd, ctypes.byref(pt))
                                pyautogui.click(pt.x, pt.y)
                            else:
                                pyautogui.click(t["x"], t["y"])
                        if not interruptible_sleep(0.12): break

                    for k in step.get("keys", []):
                        if stop_event.is_set() or not running or check_failsafe():
                            stop_event.set()
                            break
                        if use_bg:
                            post_bg_key(target_hwnd, k)
                        else:
                            pyautogui.keyDown(k)
                            if not interruptible_sleep(0.05):
                                try: pyautogui.keyUp(k)
                                except Exception: pass
                                break
                            pyautogui.keyUp(k)
                        if not interruptible_sleep(0.12): break

                    if stop_event.is_set() or not running: break

                    cd_wait = float(step.get("wait", 0))
                    if cd_wait > 0 and not interruptible_sleep(cd_wait): break

            round_idx += 1
            if not interruptible_sleep(0.05): break

    except Exception as e:
        UI.set_status(f"異常中斷: {str(e)}")
    finally:
        running = False
        emergency_release()
        try:
            UI.set_running_ui(False)
            if stopped_by_failsafe:
                UI.set_status("已觸發安全停止（滑鼠甩至左上角）")
        except Exception: pass


# ==============================================================================
# 7. 視圖構建
# ==============================================================================
def setup_themes():
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

    colors = [
        (Tags.THEME_ACTION, (2, 132, 199), (14, 165, 233), (3, 105, 161)),
        (Tags.THEME_DANGER, (185, 28, 28), (220, 38, 38), (153, 27, 27)),
        (Tags.THEME_START,  (22, 163, 74), (34, 197, 94), (21, 128, 61)),
        (Tags.THEME_STOP,   (220, 38, 38), (239, 68, 68), (185, 28, 28))
    ]
    for tag, norm, hov, act in colors:
        with dpg.theme(tag=tag):
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (*norm, 220 if tag != Tags.THEME_START else 255))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (*hov, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (*act, 255))

def build_left_column():
    with dpg.child_window(width=445, height=545, border=False):
        with dpg.child_window(height=130, border=True):
            dpg.add_text("設定與 Win32 後台綁定", color=(56, 189, 248))
            dpg.add_separator()
            with dpg.group(horizontal=True):
                dpg.add_text("設定檔:")
                dpg.add_input_text(tag=Tags.CFG_NAME, default_value="sh_macro.json", width=180)
                dpg.add_button(label="儲存", callback=save_config, width=65)
                dpg.add_button(label="載入", callback=load_config, width=65)

            with dpg.group(horizontal=True):
                dpg.add_checkbox(label="Win32後台", tag=Tags.CHK_USE_BG, default_value=True, callback=sync_ui_to_state)
                dpg.add_checkbox(label="相對坐標 (Relative)", tag=Tags.CHK_USE_REL, default_value=True, callback=sync_ui_to_state)
                dpg.add_text("微調X:")
                dpg.add_input_text(tag=Tags.OFFSET_X, default_value="0", width=35, callback=sync_ui_to_state)
                dpg.add_text("Y:")
                dpg.add_input_text(tag=Tags.OFFSET_Y, default_value="0", width=35, callback=sync_ui_to_state)

            with dpg.group(horizontal=True):
                dpg.add_text("目標視窗:")
                dpg.add_combo(tag=Tags.WINDOW_SELECT, items=[], width=240, callback=on_window_select)
                dpg.add_button(label="重新整理", callback=refresh_window_dropdown, width=65)

        dpg.add_spacer(height=2)

        with dpg.child_window(height=385, border=True):
            dpg.add_text("技能組合預設 (Combinations)", color=(56, 189, 248))
            dpg.add_separator()
            with dpg.group(horizontal=True):
                dpg.add_text("名稱:")
                dpg.add_input_text(tag=Tags.COMBO_NAME, default_value="F4補血CD", width=120)
                dpg.add_text("按鍵:")
                dpg.add_input_text(tag=Tags.COMBO_KEYS, default_value="f4", width=80)
                dpg.add_text("CD(秒):")
                dpg.add_input_text(tag=Tags.COMBO_WAIT, default_value="10.0", width=45)

            with dpg.group(horizontal=True):
                dpg.add_text("目標:")
                dpg.add_text("無 (原地)", tag=Tags.COMBO_TARGET_LBL, color=(125, 211, 252))
                dpg.add_button(label="記錄目標 (3秒)", tag=Tags.COMBO_TARGET_BTN, callback=record_combo_target, width=105)
                dpg.add_button(label="清除", callback=clear_combo_target, width=45)
                dpg.add_button(label="新增組合", callback=save_new_combo, width=70)
                dpg.add_button(label="更新", callback=update_selected_combo, width=50)

            dpg.add_listbox(tag=Tags.COMBO_LIST, items=[], num_items=8, width=415, callback=on_combo_select)

            with dpg.group(horizontal=True):
                b_add = dpg.add_button(label="將所選組合加入執行清單", callback=add_combo_to_steps, width=315)
                dpg.bind_item_theme(b_add, Tags.THEME_ACTION)
                b_del = dpg.add_button(label="刪除組合", callback=delete_selected_combo, width=90)
                dpg.bind_item_theme(b_del, Tags.THEME_DANGER)

def build_right_column():
    with dpg.child_window(width=455, height=545, border=False):
        with dpg.child_window(height=100, border=True):
            dpg.add_text("單獨新增微步 (點擊 / 按鍵 / 停頓)", color=(56, 189, 248))
            dpg.add_separator()
            dpg.add_button(label="記錄點擊坐標 (3秒)", tag=Tags.STEP_CLICK_BTN, callback=add_click_step, width=410)
            with dpg.group(horizontal=True):
                dpg.add_text("按鍵:")
                dpg.add_input_text(tag=Tags.STEP_KEY, default_value="f1", width=65)
                dpg.add_button(label="加按鍵", callback=add_key_step, width=80)
                dpg.add_text("停頓:")
                dpg.add_input_text(tag=Tags.STEP_WAIT, default_value="1.0", width=45)
                dpg.add_button(label="加停頓", callback=add_wait_step, width=80)

        dpg.add_spacer(height=2)

        with dpg.child_window(height=340, border=True):
            dpg.add_text("執行順序清單 (由上至下循環)", color=(56, 189, 248))
            dpg.add_separator()
            dpg.add_listbox(tag=Tags.STEP_LIST, items=[], num_items=11, width=425)
            with dpg.group(horizontal=True):
                dpg.add_button(label="上移", callback=move_up, width=95)
                dpg.add_button(label="下移", callback=move_down, width=95)
                b_del_step = dpg.add_button(label="刪除所選", callback=delete_selected, width=110)
                dpg.bind_item_theme(b_del_step, Tags.THEME_DANGER)
                b_clear = dpg.add_button(label="清空清單", callback=clear_all, width=110)
                dpg.bind_item_theme(b_clear, Tags.THEME_DANGER)

        dpg.add_spacer(height=2)

        with dpg.group(horizontal=True):
            dpg.add_text("狀態:", color=(148, 163, 184))
            dpg.add_text("已就緒", tag=Tags.STATUS_LBL, color=(255, 255, 255))

        btn_start = dpg.add_button(label="開始循環執行", tag=Tags.RUN_BTN, callback=toggle_run, width=435, height=42)
        dpg.bind_item_theme(btn_start, Tags.THEME_START)


# ==============================================================================
# 8. 程式主入口
# ==============================================================================
def main():
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

    setup_themes()

    with dpg.window(tag=Tags.PRIMARY_WINDOW):
        with dpg.group(horizontal=True):
            build_left_column()
            build_right_column()

    dpg.create_viewport(title="水滸歷險 巨集助手", width=935, height=585, always_on_top=True, resizable=False)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window(Tags.PRIMARY_WINDOW, True)

    refresh_window_dropdown()
    sync_ui_to_state()
    dpg.start_dearpygui()
    dpg.destroy_context()

if __name__ == "__main__":
    main()