import copy
import pyautogui

import state
from win32_api import (
    IS_WINDOWS,
    execute_click,
    post_bg_key,
    safe_sleep,
    emergency_release_all,
    force_bring_window_to_front
)

# ==============================================================================
# 動作執行調度器與背景巨集引擎
# ==============================================================================

def dispatch_action(app, act, parent_desc, current_vars=None, current_combos=None, depth=0, visited_set=None, is_test=False, round_prefix=""):
    """統一派發並執行單一動作或呼叫組合，含循環呼叫保護與變數求值"""
    if visited_set is None:
        visited_set = set()

    if not is_test:
        if not state.running or state.stop_event.is_set():
            return False
        if current_vars is None:
            current_vars = {}
        if current_combos is None:
            current_combos = []
    else:
        if state.stop_event.is_set():
            return False
        if current_vars is None:
            with state.steps_lock:
                current_vars = copy.deepcopy(state.variables)
        if current_combos is None:
            with state.steps_lock:
                current_combos = copy.deepcopy(state.combos)

    use_bg = getattr(app, "cached_use_bg", True) and IS_WINDOWS and (state.target_hwnd is not None)
    off_x = getattr(app, "cached_offset_x", 0)
    off_y = getattr(app, "cached_offset_y", 0)

    # 若在前台模式且有綁定目標視窗，自動將目標視窗置頂以確保能接收點擊與按鍵
    if not use_bg and IS_WINDOWS and state.target_hwnd:
        force_bring_window_to_front(state.target_hwnd)

    var_name = act.get("var_name")
    v_data = current_vars.get(var_name) if (current_vars and var_name) else None

    atype = act.get("type")
    if atype == "click":
        x, y = act["x"], act["y"]
        btn = act.get("btn", "left")
        if v_data and v_data.get("type") == "coord":
            val = v_data.get("value", {})
            if isinstance(val, dict):
                x, y = val.get("x", x), val.get("y", y)
                btn = val.get("btn", btn)
        msg = execute_click(x, y, act.get("rel"), use_bg, off_x, off_y, btn=btn)
        var_info = f"【{var_name}】" if var_name else ""
        app.set_status(f"{round_prefix}{parent_desc} {var_info}{msg}")
        if not safe_sleep(0.12):
            return False

    elif atype == "key":
        key = act["key"]
        if v_data and v_data.get("type") == "key":
            key = str(v_data.get("value", key))
        if use_bg:
            post_bg_key(state.target_hwnd, key)
        else:
            with state.currently_held_keys_lock:
                state.currently_held_keys.add(("fg", key))
            try:
                pyautogui.keyDown(key)
                if not safe_sleep(0.06):
                    return False
            finally:
                try:
                    pyautogui.keyUp(key)
                except Exception:
                    pass
                with state.currently_held_keys_lock:
                    state.currently_held_keys.discard(("fg", key))
        var_info = f"【{var_name}】" if var_name else ""
        app.set_status(f"{round_prefix}{parent_desc} {var_info}按鍵 [{key.upper()}]")
        if not safe_sleep(0.10):
            return False

    elif atype == "wait":
        sec = float(act.get("sec", 0.5))
        if v_data and v_data.get("type") == "wait":
            try:
                sec = float(v_data.get("value", sec))
            except Exception:
                pass
        var_info = f"【{var_name}】" if var_name else ""
        app.set_status(f"{round_prefix}{parent_desc} {var_info}等待 {sec}s")
        if not safe_sleep(sec):
            return False

    elif atype == "call_combo":
        tgt_name = act.get("target_name")
        if not tgt_name:
            return True
        if depth >= 10:
            app.set_status(f"{round_prefix}呼叫 [{tgt_name}] 超過深度上限")
            return True
        if tgt_name in visited_set:
            app.set_status(f"{round_prefix}循環呼叫 [{tgt_name}]，自動跳過")
            return True

        tgt_combo = next((c for c in current_combos if c["name"] == tgt_name), None)
        if tgt_combo:
            new_visited = visited_set | {tgt_name}
            for sub_idx, sub_act in enumerate(tgt_combo.get("actions", [])):
                if not is_test and (not state.running or state.stop_event.is_set()):
                    return False
                if is_test and state.stop_event.is_set():
                    return False
                sub_desc = f"{parent_desc}->[{tgt_name}#{sub_idx+1}]"
                if not dispatch_action(
                    app,
                    sub_act,
                    sub_desc,
                    current_vars=current_vars,
                    current_combos=current_combos,
                    depth=depth + 1,
                    visited_set=new_visited,
                    is_test=is_test,
                    round_prefix=round_prefix
                ):
                    return False
        else:
            app.set_status(f"{round_prefix}找不到被呼叫的組合 [{tgt_name}]")

    return True

def execute_single_action(app, act, desc):
    """執行單一動作（試跑用途）"""
    dispatch_action(app, act, desc, is_test=True)

def macro_worker_loop(app):
    """背景巨集循環執行緒主迴圈"""
    round_idx = 1
    try:
        while state.running and not state.stop_event.is_set():
            with state.steps_lock:
                current_steps = copy.deepcopy(state.active_steps)
                current_combos = copy.deepcopy(state.active_combos)
                current_variables = copy.deepcopy(state.active_variables)
                was_reloaded = state.reload_requested
                state.reload_requested = False

            if was_reloaded:
                app.pending_track_resync = False
                app.list_was_edited = False
                app.set_status(f"第 {round_idx} 輪: 已套用最新熱更新流程並恢復追蹤！")

            for idx, step in enumerate(current_steps):
                if not state.running or state.stop_event.is_set():
                    break

                app.highlight_active_step(idx)
                pfx = f"第 {round_idx} 輪: "

                stype = step["type"]
                if stype == "combo":
                    c_name = step.get("name", "組合")
                    for a_idx, act in enumerate(step.get("actions", [])):
                        if not state.running or state.stop_event.is_set():
                            break
                        app.highlight_active_step(idx, sub_idx=a_idx)
                        if not dispatch_action(
                            app,
                            act,
                            f"[{c_name}#{a_idx+1}]",
                            current_vars=current_variables,
                            current_combos=current_combos,
                            depth=0,
                            visited_set={c_name},
                            is_test=False,
                            round_prefix=pfx
                        ):
                            break
                else:
                    if not dispatch_action(
                        app,
                        step,
                        f"步驟#{idx+1}",
                        current_vars=current_variables,
                        current_combos=current_combos,
                        depth=0,
                        visited_set=set(),
                        is_test=False,
                        round_prefix=pfx
                    ):
                        break

            round_idx += 1
            if not safe_sleep(0.05):
                break
    except Exception as e:
        app.set_status(f"異常中斷: {e}")
    finally:
        state.running = False
        emergency_release_all()
        app.set_running_ui(False)

def test_run_execution_flow_worker(app):
    """一次性試跑整個掛機執行流程的背景工作函式"""
    with state.steps_lock:
        steps_copy = copy.deepcopy(state.steps)
        combos_copy = copy.deepcopy(state.combos)
        vars_copy = copy.deepcopy(state.variables)

    for idx, step in enumerate(steps_copy):
        if state.stop_event.is_set():
            break
        app.highlight_active_step(idx)
        pfx = "[試跑流程] "
        stype = step.get("type")
        if stype == "combo":
            c_name = step.get("name", "組合")
            sub_actions = step.get("actions", [])
            if not sub_actions:
                app.set_status(f"[試跑流程] 步驟 #{idx+1} 組合 [{c_name}] 內無動作，跳過")
                continue
            for a_idx, act in enumerate(sub_actions):
                if state.stop_event.is_set():
                    return
                app.highlight_active_step(idx, sub_idx=a_idx)
                if not dispatch_action(
                    app,
                    act,
                    f"[{c_name}#{a_idx+1}]",
                    current_vars=vars_copy,
                    current_combos=combos_copy,
                    depth=0,
                    visited_set={c_name},
                    is_test=True,
                    round_prefix=pfx
                ):
                    return
        else:
            if not dispatch_action(
                app,
                step,
                f"步驟#{idx+1}",
                current_vars=vars_copy,
                current_combos=combos_copy,
                depth=0,
                visited_set=set(),
                is_test=True,
                round_prefix=pfx
            ):
                return
