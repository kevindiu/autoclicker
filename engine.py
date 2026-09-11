import copy
import time
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
            with state.steps_lock:
                current_vars = copy.deepcopy(state.active_variables)
        if current_combos is None:
            with state.steps_lock:
                current_combos = copy.deepcopy(state.active_combos)
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
    v_data = None
    if var_name:
        with state.steps_lock:
            v_data = state.active_variables.get(var_name)
        if not v_data and current_vars:
            v_data = current_vars.get(var_name)

    atype = act.get("type")
    if atype == "click":
        x = act.get("x", 0)
        y = act.get("y", 0)
        btn = act.get("btn", "left")
        is_rel = act.get("rel")
        if v_data and v_data.get("type") == "coord":
            val = v_data.get("value", {})
            if isinstance(val, dict):
                x = val.get("x", x)
                y = val.get("y", y)
                btn = val.get("btn", btn)
                if "rel" in val:
                    is_rel = val.get("rel")
        if is_rel is None:
            is_rel = True if state.target_hwnd else False
        msg = execute_click(x, y, is_rel, use_bg, off_x, off_y, btn=btn)
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
            sub_actions = tgt_combo.get("actions", [])
            sub_total = len(sub_actions)
            for sub_idx, sub_act in enumerate(sub_actions):
                if not is_test and (not state.running or state.stop_event.is_set()):
                    return False
                if is_test and state.stop_event.is_set():
                    return False
                sub_desc = f"{parent_desc}->[{tgt_name}#{sub_idx+1}/{sub_total}]"
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

def check_and_run_due_periodic_tasks(app, periodic_tasks_runtime, current_vars, current_combos, round_prefix=""):
    """檢查是否有已到期的定時任務；若有，安全依序執行並更新上次執行時間戳記"""
    if not periodic_tasks_runtime:
        return True

    now = time.time()
    for pt in periodic_tasks_runtime:
        if not pt.get("enabled", True):
            continue
        try:
            interval = float(pt.get("interval", 1.0))
        except Exception:
            interval = 1.0
        if interval <= 0:
            interval = 1.0

        last_run = pt.get("last_run", 0.0)
        if now - last_run >= interval:
            if not state.running or state.stop_event.is_set():
                return False
            task_name = pt.get("name", "").strip() or "定時任務"
            act = pt.get("action", {})
            app.set_status(f"{round_prefix}[定時] {task_name}")

            # 統一透過 dispatch_action 執行
            ok = dispatch_action(
                app,
                act,
                f"[定時:{task_name}]",
                current_vars=current_vars,
                current_combos=current_combos,
                depth=0,
                visited_set=set(),
                is_test=False,
                round_prefix=round_prefix
            )
            pt["last_run"] = time.time()
            if not ok:
                return False
            if not safe_sleep(0.05):
                return False
    return True

def macro_worker_loop(app):
    """背景巨集循環執行緒主迴圈"""
    round_idx = 1
    with state.steps_lock:
        active_pts = copy.deepcopy(state.active_periodic_tasks)

    start_time = time.time()
    periodic_tasks_runtime = []
    for pt in active_pts:
        pt_copy = copy.deepcopy(pt)
        # 若勾選「啟動時立即首發一次」，則設定 last_run 為 0，首度檢查時即觸發；否則設為 start_time，待滿 interval 秒後首發
        pt_copy["last_run"] = 0.0 if pt.get("run_on_start", False) else start_time
        periodic_tasks_runtime.append(pt_copy)

    try:
        # 首輪開始前：若有設定「啟動時立即首發」的定時任務，先檢查執行一次
        with state.steps_lock:
            init_vars = copy.deepcopy(state.active_variables)
            init_combos = copy.deepcopy(state.active_combos)
        if not check_and_run_due_periodic_tasks(app, periodic_tasks_runtime, init_vars, init_combos, round_prefix="啟動首發: "):
            return

        while state.running and not state.stop_event.is_set():
            with state.steps_lock:
                current_steps = copy.deepcopy(state.active_steps)
                current_combos = copy.deepcopy(state.active_combos)
                current_variables = copy.deepcopy(state.active_variables)
                was_reloaded = state.reload_requested
                state.reload_requested = False
                if was_reloaded:
                    latest_pts = copy.deepcopy(state.active_periodic_tasks)

            if was_reloaded:
                # 平滑套用熱更新，保留進行中定時任務的上次執行計時
                existing_timers = {pt.get("id"): pt.get("last_run") for pt in periodic_tasks_runtime if pt.get("id")}
                new_runtime = []
                now = time.time()
                for pt in latest_pts:
                    pt_copy = copy.deepcopy(pt)
                    pt_id = pt_copy.get("id")
                    if pt_id in existing_timers:
                        pt_copy["last_run"] = existing_timers[pt_id]
                    else:
                        pt_copy["last_run"] = 0.0 if pt.get("run_on_start", False) else now
                    new_runtime.append(pt_copy)
                periodic_tasks_runtime = new_runtime
                app.set_status(f"第 {round_idx} 輪: 已自動套用最新流程與定時任務！")

            has_enabled_periodic = any(pt.get("enabled", True) for pt in periodic_tasks_runtime)
            if not current_steps and not has_enabled_periodic:
                app.set_status("掛機流程清單與定時任務均為空，巨集已自動停止！")
                state.running = False
                break

            if not current_steps:
                # 若主流程為空但有啟用的定時任務，進行待命定時輪詢
                if not check_and_run_due_periodic_tasks(app, periodic_tasks_runtime, current_variables, current_combos, round_prefix=""):
                    break
                if not safe_sleep(0.1):
                    break
                continue

            for idx, step in enumerate(current_steps):
                if not state.running or state.stop_event.is_set():
                    break

                app.highlight_active_step(idx)
                pfx = f"第 {round_idx} 輪: "

                stype = step["type"]
                step_ok = True
                if stype == "combo":
                    c_name = step.get("name", "組合")
                    sub_actions = step.get("actions", [])
                    sub_total = len(sub_actions)
                    for a_idx, act in enumerate(sub_actions):
                        if not state.running or state.stop_event.is_set():
                            step_ok = False
                            break
                        app.highlight_active_step(idx, sub_idx=a_idx)
                        if not dispatch_action(
                            app,
                            act,
                            f"[{c_name}#{a_idx+1}/{sub_total}]",
                            current_vars=current_variables,
                            current_combos=current_combos,
                            depth=0,
                            visited_set={c_name},
                            is_test=False,
                            round_prefix=pfx
                        ):
                            step_ok = False
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
                        step_ok = False

                if not step_ok or not state.running or state.stop_event.is_set():
                    break

                # 當前步驟或 COMBO 已完全執行結束！安全檢查並執行到期的定時任務
                if not check_and_run_due_periodic_tasks(app, periodic_tasks_runtime, current_variables, current_combos, round_prefix=pfx):
                    break

            # 輪次銜接時亦進行一次定時任務檢查
            if not check_and_run_due_periodic_tasks(app, periodic_tasks_runtime, current_variables, current_combos, round_prefix=f"第 {round_idx} 輪結束: "):
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
