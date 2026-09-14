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
    force_bring_window_to_front,
    is_window_alive
)

# ==============================================================================
# 動作執行調度器與背景巨集引擎
# ==============================================================================

def dispatch_action(app, act, parent_desc, current_vars=None, current_combos=None, depth=0, visited_set=None, is_test=False, round_prefix=""):
    """統一派發並執行單一動作或呼叫組合，含循環呼叫保護與變數求值"""
    if visited_set is None:
        visited_set = set()

    if not is_test:
        if not state.is_running() or state.stop_event.is_set():
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

    if is_test:
        log_tag = "試跑"
    elif "[定時:" in parent_desc:
        log_tag = "定時"
    elif depth > 0 or ("[" in parent_desc and ("#" in parent_desc or "組合" in parent_desc)):
        log_tag = "組合"
    else:
        log_tag = "流程"

    var_name = act.get("var_name")
    v_data = None
    if var_name:
        with state.steps_lock:
            v_data = state.active_variables.get(var_name)
        if not v_data and current_vars:
            v_data = current_vars.get(var_name)

    atype = act.get("type")
    if atype == "click":
        try:
            x = int(act.get("x", 0))
            y = int(act.get("y", 0))
        except (ValueError, TypeError):
            x, y = 0, 0
        btn = act.get("btn", "left")
        is_rel = act.get("rel")
        if v_data and v_data.get("type") == "coord":
            val = v_data.get("value", {})
            if isinstance(val, dict):
                try:
                    x = int(val.get("x", x))
                    y = int(val.get("y", y))
                except (ValueError, TypeError):
                    pass
                btn = val.get("btn", btn)
                if "rel" in val:
                    is_rel = val.get("rel")
        if is_rel is None:
            is_rel = True if state.target_hwnd else False
        msg = execute_click(x, y, is_rel, use_bg, off_x, off_y, btn=btn)
        var_info = f"【{var_name}】" if var_name else ""
        log_txt = f"{round_prefix}{parent_desc} {var_info}{msg}"
        if hasattr(app, "append_log"):
            app.append_log(log_tag, log_txt)
        if not safe_sleep(0.12):
            return False

    elif atype == "key":
        key = str(act.get("key", "f1"))
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
                except Exception as e:
                    if hasattr(app, "append_log"):
                        app.append_log("警示", f"釋放前台按鍵 [{key}] 失敗: {e}")
                with state.currently_held_keys_lock:
                    state.currently_held_keys.discard(("fg", key))
        var_info = f"【{var_name}】" if var_name else ""
        mode_tag = " (後台)" if use_bg else " (前台)"
        if hasattr(app, "append_log"):
            app.append_log(log_tag, f"{round_prefix}{parent_desc} {var_info}按鍵 [{key.upper()}]{mode_tag}")
        if not safe_sleep(0.10):
            return False

    elif atype == "wait":
        try:
            sec = float(act.get("sec", 0.5))
        except (ValueError, TypeError):
            sec = 0.5
        if v_data and v_data.get("type") == "wait":
            try:
                sec = float(v_data.get("value", sec))
            except (ValueError, TypeError):
                if hasattr(app, "append_log"):
                    app.append_log("警示", f"變數【{var_name}】等待秒數數值格式無效，使用預設值 {sec}s")
        var_info = f"【{var_name}】" if var_name else ""
        log_txt = f"{round_prefix}{parent_desc} {var_info}等待 {sec}s"
        if hasattr(app, "append_log"):
            app.append_log(log_tag, log_txt)
        if not safe_sleep(sec):
            return False

    elif atype == "call_combo":
        tgt_name = act.get("target_name")
        if not tgt_name:
            return True
        if depth >= 10:
            warn_msg = f"{round_prefix}呼叫 [{tgt_name}] 超過深度上限"
            if hasattr(app, "append_log"):
                app.append_log("警示", warn_msg)
            return True
        if tgt_name in visited_set:
            warn_msg = f"{round_prefix}循環呼叫 [{tgt_name}]，自動跳過"
            if hasattr(app, "append_log"):
                app.append_log("警示", warn_msg)
            return True

        tgt_combo = next((c for c in current_combos if c["name"] == tgt_name), None)
        if tgt_combo:
            new_visited = visited_set | {tgt_name}
            sub_actions = tgt_combo.get("actions", [])
            sub_total = len(sub_actions)
            for sub_idx, sub_act in enumerate(sub_actions):
                if not is_test and (not state.is_running() or state.stop_event.is_set()):
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
            warn_msg = f"{round_prefix}找不到被呼叫的組合 [{tgt_name}]"
            if hasattr(app, "append_log"):
                app.append_log("警示", warn_msg)

    return True

def execute_single_action(app, act, desc):
    """執行單一動作（試跑用途）"""
    dispatch_action(app, act, desc, is_test=True)

def sync_periodic_timers(periodic_tasks_runtime, active_task_id=None):
    """線程安全地同步背景定時任務當前計時器快照至 state.periodic_timers 供 UI 即時倒數與設定值展示"""
    timers = {}
    for idx, pt in enumerate(periodic_tasks_runtime):
        pt_id = pt.get("id") or f"pt_idx_{idx}"
        try:
            interval = float(pt.get("interval", 1.0))
        except (ValueError, TypeError):
            interval = 1.0
        timers[pt_id] = {
            "last_run": pt.get("last_run", 0.0),
            "interval": interval,
            "enabled": pt.get("enabled", True),
            "is_active": (pt_id == active_task_id)
        }
    with state.periodic_timers_lock:
        state.periodic_timers = timers

def check_and_run_due_periodic_tasks(app, periodic_tasks_runtime, current_vars, current_combos, round_prefix="", next_step_idx=None):
    """檢查是否有已到期的定時任務；若有，安全依序執行並更新上次執行時間戳記"""
    if not periodic_tasks_runtime:
        return True

    for idx, pt in enumerate(periodic_tasks_runtime):
        if not pt.get("enabled", True):
            continue
        try:
            interval = float(pt.get("interval", 1.0))
        except (ValueError, TypeError):
            interval = 1.0
        if interval <= 0:
            interval = 1.0

        now = time.time()
        last_run = pt.get("last_run", 0.0)
        if now - last_run >= interval:
            if not state.is_running() or state.stop_event.is_set():
                return False
            if IS_WINDOWS and state.target_hwnd and not is_window_alive(state.target_hwnd):
                return False
            task_name = pt.get("name", "").strip() or "定時任務"
            pt_id = pt.get("id") or f"pt_idx_{idx}"
            act = pt.get("action", {})
            if hasattr(app, "append_log"):
                app.append_log("定時", f"{round_prefix}任務【{task_name}】到期觸發 (每 {interval}s)")

            # 定時任務執行期間：
            # 1. 若有指定下一動 (next_step_idx)，在主畫面流程清單中以待命暖金色標記即將接續執行的動作，
            #    讓使用者一眼看清定時任務完結後會執行邊個動作；否則清除高亮
            if next_step_idx is not None and hasattr(app, "highlight_pending_step"):
                app.highlight_pending_step(next_step_idx)
            elif hasattr(app, "clear_active_step_highlight"):
                app.clear_active_step_highlight()

            # 2. 高亮當前執行的定時任務卡片
            if hasattr(app, "highlight_active_periodic_task"):
                app.highlight_active_periodic_task(idx)

            sync_periodic_timers(periodic_tasks_runtime, active_task_id=pt_id)

            try:
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
            finally:
                if hasattr(app, "clear_active_periodic_task_highlight"):
                    app.clear_active_periodic_task_highlight()
            pt["last_run"] = time.time()
            sync_periodic_timers(periodic_tasks_runtime, active_task_id=None)
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
    sync_periodic_timers(periodic_tasks_runtime)

    try:
        # 首輪開始前：若有設定「啟動時立即首發」的定時任務，先檢查執行一次
        with state.steps_lock:
            init_vars = copy.deepcopy(state.active_variables)
            init_combos = copy.deepcopy(state.active_combos)
        first_next_idx = 0 if state.active_steps else None
        if not check_and_run_due_periodic_tasks(app, periodic_tasks_runtime, init_vars, init_combos, round_prefix="啟動首發: ", next_step_idx=first_next_idx):
            return

        while state.is_running() and not state.stop_event.is_set():
            if IS_WINDOWS and state.target_hwnd and not is_window_alive(state.target_hwnd):
                msg = "目標遊戲視窗已關閉或崩潰，巨集已自動安全停止！"
                if hasattr(app, "append_log"):
                    app.append_log("警示", f"✕ {msg}")
                state.set_running(False)
                break

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
                sync_periodic_timers(periodic_tasks_runtime)
                msg = f"第 {round_idx} 輪: 已自動套用最新流程與定時任務！"
                if hasattr(app, "append_log"):
                    app.append_log("系統", f"⚡ {msg}")

            has_enabled_periodic = any(pt.get("enabled", True) for pt in periodic_tasks_runtime)
            if not current_steps and not has_enabled_periodic:
                msg = "掛機流程清單與定時任務均為空，巨集已自動停止！"
                if hasattr(app, "append_log"):
                    app.append_log("警示", msg)
                state.set_running(False)
                break

            if not current_steps:
                # 若主流程為空但有啟用的定時任務，進行待命定時輪詢
                if not check_and_run_due_periodic_tasks(app, periodic_tasks_runtime, current_variables, current_combos, round_prefix=""):
                    break
                if not safe_sleep(0.1):
                    break
                continue

            if hasattr(app, "append_log"):
                app.append_log("系統", f"--- 開始第 {round_idx} 輪循環 ---")

            for idx, step in enumerate(current_steps):
                if not state.is_running() or state.stop_event.is_set():
                    break

                if IS_WINDOWS and state.target_hwnd and not is_window_alive(state.target_hwnd):
                    msg = "目標遊戲視窗已關閉或崩潰，巨集已自動安全停止！"
                    if hasattr(app, "append_log"):
                        app.append_log("警示", f"✕ {msg}")
                    state.set_running(False)
                    break

                app.highlight_active_step(idx)
                pfx = f"第 {round_idx} 輪: "

                stype = step.get("type")
                step_ok = True
                if stype == "combo":
                    c_name = step.get("name", "組合")
                    sub_actions = step.get("actions", [])
                    sub_total = len(sub_actions)
                    for a_idx, act in enumerate(sub_actions):
                        if not state.is_running() or state.stop_event.is_set():
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

                if not step_ok or not state.is_running() or state.stop_event.is_set():
                    break

                # 當前步驟或 COMBO 已完全執行結束！安全檢查並執行到期的定時任務
                next_step = (idx + 1) if (idx + 1 < len(current_steps)) else 0
                if not check_and_run_due_periodic_tasks(app, periodic_tasks_runtime, current_variables, current_combos, round_prefix=pfx, next_step_idx=next_step):
                    break

            # 輪次銜接時亦進行一次定時任務檢查
            next_step = 0 if current_steps else None
            if not check_and_run_due_periodic_tasks(app, periodic_tasks_runtime, current_variables, current_combos, round_prefix=f"第 {round_idx} 輪結束: ", next_step_idx=next_step):
                break

            round_idx += 1
            if not safe_sleep(0.05):
                break
    except Exception as e:
        if hasattr(app, "append_log"):
            app.append_log("警示", f"✕ 異常中斷: {e}")
    finally:
        state.set_running(False)
        with state.periodic_timers_lock:
            state.periodic_timers.clear()
        emergency_release_all()
        app.set_running_ui(False)
        if hasattr(app, "append_log"):
            completed = round_idx - 1 if round_idx > 1 else (1 if round_idx == 1 and not state.stop_event.is_set() else 0)
            app.append_log("系統", f"⏹ 巨集循環結束 (累計運行 {completed} 輪)")

def test_run_execution_flow_worker(app):
    """一次性試跑整個掛機執行流程的背景工作函式"""
    try:
        with state.steps_lock:
            steps_copy = copy.deepcopy(state.steps)
            combos_copy = copy.deepcopy(state.combos)
            vars_copy = copy.deepcopy(state.variables)

        for idx, step in enumerate(steps_copy):
            if state.stop_event.is_set():
                break
            if IS_WINDOWS and state.target_hwnd and not is_window_alive(state.target_hwnd):
                msg = "目標遊戲視窗已關閉，試跑流程中止！"
                if hasattr(app, "append_log"):
                    app.append_log("警示", f"✕ {msg}")
                break
            app.highlight_active_step(idx)
            pfx = "[試跑流程] "
            stype = step.get("type")
            if stype == "combo":
                c_name = step.get("name", "組合")
                sub_actions = step.get("actions", [])
                if not sub_actions:
                    if hasattr(app, "append_log"):
                        app.append_log("試跑", f"[試跑流程] 步驟 #{idx+1} 組合 [{c_name}] 內無動作，跳過")
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
    except Exception as e:
        if hasattr(app, "append_log"):
            app.append_log("警示", f"✕ 試跑流程異常: {e}")
    finally:
        if hasattr(app, "clear_active_step_highlight"):
            app.clear_active_step_highlight()
