import threading

# ==============================================================================
# 全域資料狀態與執行緒同步物件
# ==============================================================================
combos = []
steps = []           # 主 UI 編輯器草稿 (Draft)
variables = {}       # 全域變數庫字典: {var_name: {"type": "coord"|"key"|"wait", ...}}
periodic_tasks = []  # 主 UI 定時任務草稿 (Draft)
active_steps = []    # 背景運行實例快照 (Active Snapshot)
active_combos = []   # 背景組合運行實例快照 (Active Combo Snapshot)
active_variables = {} # 背景變數運行實例快照 (Active Variables Snapshot)
active_periodic_tasks = [] # 背景定時任務運行實例快照 (Active Periodic Snapshot)

running = False
is_testing = False
reload_requested = False
steps_lock = threading.Lock() # 保護 active_steps, active_combos, active_variables 與 active_periodic_tasks
stop_event = threading.Event()
target_hwnd = None
currently_held_keys = set()   # 追蹤當前被按下的按鍵，格式: ("bg", hwnd, vk) 或 ("fg", key_str)
currently_held_keys_lock = threading.Lock()

def format_action_summary(act, index=None, current_variables=None):
    """統一格式化動作或步驟的文字描述，採用 100% 跨平台相容的通用標籤與符號"""
    var_dict = current_variables if current_variables is not None else variables
    atype = act.get("type", "")

    var_name = act.get("var_name")

    if atype == "click":
        if var_name:
            v_info = var_dict.get(var_name, {})
            val = v_info.get("value") if isinstance(v_info.get("value"), dict) else v_info
            btn_key = val.get("btn", act.get("btn", "left")) if isinstance(val, dict) else act.get("btn", "left")
            btn_tag = "右鍵" if btn_key == "right" else "左鍵"
            cx = val.get("x", act.get("x", 0)) if isinstance(val, dict) else act.get("x", 0)
            cy = val.get("y", act.get("y", 0)) if isinstance(val, dict) else act.get("y", 0)
            body = f"[點擊·{btn_tag}] -> 變數:【{var_name}】({cx},{cy})"
        else:
            btn_tag = "右鍵" if act.get("btn") == "right" else "左鍵"
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

    return body

def format_periodic_task_summary(task, current_variables=None, max_name_len=18):
    """格式化定時週期任務的顯示字串 (簡短俐落，支援長名稱智能縮略，避免溢出抖動)"""
    enabled = task.get("enabled", True)
    st_icon = "[✓]" if enabled else "[✕]"
    sec = task.get("interval", 1.0)
    try:
        f_sec = float(sec)
        sec_str = f"{int(f_sec)}s" if f_sec.is_integer() else f"{f_sec}s"
    except Exception:
        sec_str = f"{sec}s"

    name = task.get("name", "").strip()
    start_str = " (首)" if task.get("run_on_start", False) else ""

    if name:
        disp_name = name if len(name) <= max_name_len else name[:max_name_len - 1] + "…"
        return f"{st_icon} {sec_str} · {disp_name}{start_str}"

    act = task.get("action", {})
    var_name = act.get("var_name")
    atype = act.get("type", "")

    if var_name:
        desc = f"變數:【{var_name}】"
    elif atype == "call_combo":
        desc = f"組合:【{act.get('target_name', '')}】"
    elif atype == "key":
        desc = f"按鍵 [{str(act.get('key', '')).upper()}]"
    elif atype == "click":
        btn_tag = "右鍵" if act.get("btn") == "right" else "左鍵"
        desc = f"點擊·{btn_tag}"
    elif atype == "wait":
        desc = f"停頓 {act.get('sec', 0)}s"
    else:
        desc = f"[{atype}]"

    disp_desc = desc if len(desc) <= max_name_len else desc[:max_name_len - 1] + "…"
    return f"{st_icon} {sec_str} · {disp_desc}{start_str}"

