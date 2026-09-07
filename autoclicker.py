import os
import json
import time
import threading
import pyautogui
import dearpygui.dearpygui as dpg

pyautogui.FAILSAFE = True  # 滑鼠甩到左上角可緊急停止

combos = []   # 存放定義好的技能組合庫
steps = []    # 存放主執行順序清單
running = False
temp_combo_target = None  # 記錄組合專用目標坐標

# --- 組合庫 (Combination) 操作邏輯 ---
def countdown_combo_target():
    dpg.configure_item("btn_combo_target", enabled=False)
    for i in range(3, 0, -1):
        dpg.set_value("lbl_status", f"請移至施法目標... 倒數 {i} 秒")
        time.sleep(1)
    pos = pyautogui.position()
    global temp_combo_target
    temp_combo_target = {"x": pos.x, "y": pos.y}
    dpg.set_value("lbl_combo_target", f"({pos.x}, {pos.y})")
    dpg.set_value("lbl_status", f"已鎖定組合目標：({pos.x}, {pos.y})")
    dpg.configure_item("btn_combo_target", enabled=True)

def record_combo_target():
    threading.Thread(target=countdown_combo_target, daemon=True).start()

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
        t_str = f"[目標:({c['target']['x']},{c['target']['y']})] " if c.get("target") else ""
        k_str = ",".join(c.get("keys", []))
        items.append(f"[{c['name']}] {t_str}[按鍵:{k_str.upper()}] [CD:{c['wait']}秒]")
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
            dpg.set_value("lbl_combo_target", f"({temp_combo_target['x']}, {temp_combo_target['y']})")
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
        name = dpg.get_value("input_combo_name").strip()
        keys = get_keys_from_input(dpg.get_value("input_combo_keys"))
        try:
            wait_sec = float(dpg.get_value("input_combo_wait"))
            if wait_sec < 0: raise ValueError
        except ValueError:
            return

        combos[idx] = {
            "name": name,
            "keys": keys,
            "wait": wait_sec,
            "target": dict(temp_combo_target) if temp_combo_target else None
        }
        update_combo_list(select_idx=idx)
        dpg.set_value("lbl_status", f"已更新組合 #{idx+1}：[{name}]")

def delete_selected_combo():
    selected = dpg.get_value("combo_listbox")
    if not selected: return
    items = dpg.get_item_configuration("combo_listbox")["items"]
    if selected in items:
        idx = items.index(selected)
        del combos[idx]
        update_combo_list()
        dpg.set_value("lbl_status", "已刪除該組合")

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
            items.append(f"#{i+1:02d}  [點擊坐標] -> ({s['x']}, {s['y']})")
        elif s["type"] == "key":
            items.append(f"#{i+1:02d}  [按下按鍵] -> [ {s['key'].upper()} ]")
        elif s["type"] == "wait":
            items.append(f"#{i+1:02d}  [停頓等待] -> {s['sec']} 秒")
        elif s["type"] == "combo":
            t_str = f"[目標:({s['target']['x']},{s['target']['y']})] " if s.get("target") else ""
            k_str = ",".join(s.get("keys", []))
            items.append(f"#{i+1:02d}  [組合:{s['name']}] {t_str}[按鍵:{k_str.upper()}] [CD:{s['wait']}秒]")
    dpg.configure_item("step_listbox", items=items)
    if select_idx is not None and 0 <= select_idx < len(items):
        dpg.set_value("step_listbox", items[select_idx])

def countdown_click(insert_at):
    dpg.configure_item("btn_add_click", enabled=False)
    for i in range(3, 0, -1):
        dpg.set_value("lbl_status", f"請移至目標點... 倒數 {i} 秒")
        time.sleep(1)
    pos = pyautogui.position()
    steps.insert(insert_at, {"type": "click", "x": pos.x, "y": pos.y})
    update_step_list(select_idx=insert_at)
    dpg.set_value("lbl_status", f"已插入點擊到 #{insert_at+1}：({pos.x}, {pos.y})")
    dpg.configure_item("btn_add_click", enabled=True)

def add_click_step():
    threading.Thread(target=countdown_click, args=(get_insert_index(),), daemon=True).start()

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

# --- 執行引擎 ---
def toggle_run():
    global running
    if not running:
        if not steps:
            dpg.set_value("lbl_status", "執行清單是空的，請先加入步驟！")
            return
        running = True
        dpg.configure_item("btn_toggle", label="停止執行 (或甩滑鼠至左上角)")
        dpg.bind_item_theme("btn_toggle", "theme_btn_stop")
        dpg.set_value("lbl_status", "狀態：循環運作中...")
        threading.Thread(target=run_loop, daemon=True).start()
    else:
        running = False
        dpg.configure_item("btn_toggle", label="開始循環執行")
        dpg.bind_item_theme("btn_toggle", "theme_btn_start")
        dpg.set_value("lbl_status", "狀態：已手動停止")

def run_loop():
    global running
    round_idx = 1
    try:
        while running:
            for idx, step in enumerate(steps):
                if not running: break
                s_name = f"[{step['name']}]" if step["type"] == "combo" else step["type"]
                dpg.set_value("lbl_status", f"第 {round_idx} 輪 ({idx+1}/{len(steps)}): {s_name}")

                if step["type"] == "click":
                    pyautogui.click(step["x"], step["y"])
                    time.sleep(0.12)

                elif step["type"] == "key":
                    pyautogui.keyDown(step["key"])
                    time.sleep(0.06)
                    pyautogui.keyUp(step["key"])
                    time.sleep(0.1)

                elif step["type"] == "wait":
                    chunks = int(step["sec"] * 10)
                    for _ in range(chunks):
                        if not running: break
                        time.sleep(0.1)

                elif step["type"] == "combo":
                    if step.get("target"):
                        pyautogui.click(step["target"]["x"], step["target"]["y"])
                        time.sleep(0.12)
                    for k in step.get("keys", []):
                        if not running: break
                        pyautogui.keyDown(k)
                        time.sleep(0.06)
                        pyautogui.keyUp(k)
                        time.sleep(0.15)
                    chunks = int(float(step.get("wait", 0)) * 10)
                    for _ in range(chunks):
                        if not running: break
                        time.sleep(0.1)

            round_idx += 1
            time.sleep(0.05)
    except pyautogui.FailSafeException:
        running = False
        dpg.configure_item("btn_toggle", label="開始循環執行")
        dpg.bind_item_theme("btn_toggle", "theme_btn_start")
        dpg.set_value("lbl_status", "已觸發安全停止（滑鼠甩至左上角）")

# --- UI 構建與樣式客製化 ---
dpg.create_context()

# === 跨平台字型偵測（支援 Windows 與 macOS） ===
windir = os.environ.get("WINDIR", "C:\\Windows")
candidate_fonts = [
    # Windows 繁體中文與簡體中文字型
    os.path.join(windir, "Fonts", "msjh.ttc"),      # 微軟正黑體 (首選)
    os.path.join(windir, "Fonts", "msjhbd.ttc"),    # 微軟正黑體 粗體
    os.path.join(windir, "Fonts", "msyh.ttc"),      # 微軟雅黑
    os.path.join(windir, "Fonts", "mingliu.ttc"),   # 新細明體
    os.path.join(windir, "Fonts", "simsun.ttc"),    # 宋體
    "C:\\Windows\\Fonts\\msjh.ttc",
    "C:\\Windows\\Fonts\\msyh.ttc",
    # macOS 中文字型
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
]

selected_font = next((f for f in candidate_fonts if os.path.exists(f)), None)
if selected_font:
    with dpg.font_registry():
        with dpg.font(selected_font, 14) as default_font:
            dpg.add_font_range_hint(dpg.mvFontRangeHint_Chinese_Full)
        dpg.bind_font(default_font)

# 全域深色主題
with dpg.theme() as global_theme:
    with dpg.theme_component(dpg.mvAll):
        dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 12, 12)
        dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 5)
        dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 8)
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

# 特殊按鈕色彩樣式
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

    # 1. 頂部存檔工具列
    with dpg.child_window(height=48, border=True):
        with dpg.group(horizontal=True):
            dpg.add_text("設定檔名:", color=(148, 163, 184))
            dpg.add_input_text(tag="input_config_name", default_value="sh_macro.json", width=190)
            dpg.add_button(label="儲存", callback=save_config, width=65)
            dpg.add_button(label="載入", callback=load_config, width=65)

    dpg.add_spacer(height=2)

    # 2. 技能組合預設
    with dpg.child_window(height=245, border=True):
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

        dpg.add_listbox(tag="combo_listbox", items=[], num_items=3, width=400, callback=on_combo_select)

        with dpg.group(horizontal=True):
            b_add = dpg.add_button(label="將組合加入執行清單", callback=add_combo_to_steps, width=305)
            dpg.bind_item_theme(b_add, "theme_btn_action")
            b_del = dpg.add_button(label="刪除組合", callback=delete_selected_combo, width=85)
            dpg.bind_item_theme(b_del, "theme_btn_danger")

    dpg.add_spacer(height=2)

    # 3. 折疊式單步微調
    with dpg.collapsing_header(label="單獨新增微步 (點擊 / 單鍵 / 停頓)", default_open=False):
        with dpg.child_window(height=80, border=True):
            with dpg.group(horizontal=True):
                dpg.add_button(label="記錄點擊坐標 (3秒)", tag="btn_add_click", callback=add_click_step, width=380)
            with dpg.group(horizontal=True):
                dpg.add_text("按鍵:")
                dpg.add_input_text(tag="input_key", default_value="f1", width=70)
                dpg.add_button(label="加按鍵", callback=add_key_step, width=80)
                dpg.add_text("停頓:")
                dpg.add_input_text(tag="input_wait", default_value="1.0", width=50)
                dpg.add_button(label="加停頓", callback=add_wait_step, width=80)

    dpg.add_spacer(height=2)

    # 4. 主執行順序清單
    with dpg.child_window(height=225, border=True):
        dpg.add_text("執行順序清單 (由上至下循環)", color=(56, 189, 248))
        dpg.add_separator()

        dpg.add_listbox(tag="step_listbox", items=[], num_items=5, width=400)

        with dpg.group(horizontal=True):
            dpg.add_button(label="上移", callback=move_up, width=88)
            dpg.add_button(label="下移", callback=move_down, width=88)
            b_del_step = dpg.add_button(label="刪除所選", callback=delete_selected, width=100)
            dpg.bind_item_theme(b_del_step, "theme_btn_danger")
            b_clear = dpg.add_button(label="清空清單", callback=clear_all, width=100)
            dpg.bind_item_theme(b_clear, "theme_btn_danger")

    dpg.add_spacer(height=4)

    # 5. 底部狀態列與執行按鈕
    with dpg.group(horizontal=True):
        dpg.add_text("狀態:", color=(148, 163, 184))
        dpg.add_text("已就緒", tag="lbl_status", color=(255, 255, 255))

    btn_start = dpg.add_button(label="開始循環執行", tag="btn_toggle", callback=toggle_run, width=400, height=44)
    dpg.bind_item_theme(btn_start, "theme_btn_start")

dpg.create_viewport(title="水滸歷險 巨集助手", width=435, height=730, always_on_top=True, resizable=False)
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.set_primary_window("primary_window", True)
dpg.start_dearpygui()
dpg.destroy_context()
