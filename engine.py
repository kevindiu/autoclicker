import copy
import time
from typing import Optional, Set, Dict, List, Tuple

import constants
import state
from events import EventBus, AppEvents
from state import ActionDict, ComboDict, VariableDict
from win32_api import (
    IS_WINDOWS,
    execute_click,
    post_bg_key,
    safe_sleep,
    emergency_release_all,
    force_bring_window_to_front,
    is_window_alive,
    _get_pyautogui
)

# ==============================================================================
# 動作執行調度器與背景巨集引擎
# ==============================================================================

def _handle_click(act, parent_desc, current_vars, current_combos, depth, visited_set, is_test, round_prefix, use_bg, off_x, off_y, log_tag, var_name, v_data):
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
        is_rel = True if state.app_state.target_hwnd else False
    msg = execute_click(x, y, is_rel, use_bg, off_x, off_y, btn=btn)
    var_info = f"【{var_name}】" if var_name else ""
    log_txt = f"{round_prefix}{parent_desc} {var_info}{msg}"
    EventBus.emit(AppEvents.LOG_MESSAGE, log_tag, log_txt)
    if not safe_sleep(constants.SLEEP_CLICK):
        return False
    return True

def _handle_key(act, parent_desc, current_vars, current_combos, depth, visited_set, is_test, round_prefix, use_bg, off_x, off_y, log_tag, var_name, v_data):
    key = str(act.get("key", "f1"))
    if v_data and v_data.get("type") == "key":
        key = str(v_data.get("value", key))
    if use_bg:
        post_bg_key(state.app_state.target_hwnd, key)
    else:
        with state.app_state.currently_held_keys_lock:
            state.app_state.currently_held_keys.add(("fg", key))
        try:
            # 統一透過 _get_pyautogui() 取得實例，確保 FAILSAFE/PAUSE 設定必定已套用
            _get_pyautogui().keyDown(key)
            if not safe_sleep(constants.SLEEP_KEY_FG):
                return False
        finally:
            try:
                _get_pyautogui().keyUp(key)
            except Exception as e:
                EventBus.emit(AppEvents.LOG_MESSAGE, "警示", f"釋放前台按鍵 [{key}] 失敗: {e}")
            with state.app_state.currently_held_keys_lock:
                state.app_state.currently_held_keys.discard(("fg", key))
    var_info = f"【{var_name}】" if var_name else ""
    mode_tag = " (後台)" if use_bg else " (前台)"
    EventBus.emit(AppEvents.LOG_MESSAGE, log_tag, f"{round_prefix}{parent_desc} {var_info}按鍵 [{key.upper()}]{mode_tag}")
    if not safe_sleep(constants.SLEEP_KEY_AFTER):
        return False
    return True

def _handle_wait(act, parent_desc, current_vars, current_combos, depth, visited_set, is_test, round_prefix, use_bg, off_x, off_y, log_tag, var_name, v_data):
    try:
        sec = float(act.get("sec", 0.5))
    except (ValueError, TypeError):
        sec = 0.5
    if v_data and v_data.get("type") == "wait":
        try:
            sec = float(v_data.get("value", sec))
        except (ValueError, TypeError):
            EventBus.emit(AppEvents.LOG_MESSAGE, "警示", f"變數【{var_name}】等待秒數數值格式無效，使用預設值 {sec}s")
    var_info = f"【{var_name}】" if var_name else ""
    log_txt = f"{round_prefix}{parent_desc} {var_info}等待 {sec}s"
    EventBus.emit(AppEvents.LOG_MESSAGE, log_tag, log_txt)
    if not safe_sleep(sec):
        return False
    return True

def _handle_call_combo(act, parent_desc, current_vars, current_combos, depth, visited_set, is_test, round_prefix, use_bg, off_x, off_y, log_tag, var_name, v_data):
    tgt_name = act.get("target_name")
    if not tgt_name:
        return True
    if depth >= constants.MAX_COMBO_DEPTH:
        warn_msg = f"{round_prefix}呼叫 [{tgt_name}] 超過深度上限"
        EventBus.emit(AppEvents.LOG_MESSAGE, "警示", warn_msg)
        return True
    if tgt_name in visited_set:
        warn_msg = f"{round_prefix}循環呼叫 [{tgt_name}]，自動跳過"
        EventBus.emit(AppEvents.LOG_MESSAGE, "警示", warn_msg)
        return True

    tgt_combo = next((c for c in current_combos if c["name"] == tgt_name), None)
    if tgt_combo:
        new_visited = visited_set | {tgt_name}
        sub_actions = tgt_combo.get("actions", [])
        sub_total = len(sub_actions)
        for sub_idx, sub_act in enumerate(sub_actions):
            if not is_test and (not state.is_running() or state.app_state.stop_event.is_set()):
                return False
            if is_test and state.app_state.stop_event.is_set():
                return False
            sub_desc = f"{parent_desc}->[{tgt_name}#{sub_idx+1}/{sub_total}]"
            if not dispatch_action(
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
        EventBus.emit(AppEvents.LOG_MESSAGE, "警示", warn_msg)

    return True

ACTION_HANDLERS = {
    "click": _handle_click,
    "key": _handle_key,
    "wait": _handle_wait,
    "call_combo": _handle_call_combo
}

def dispatch_action(
    act: ActionDict,
    parent_desc: str,
    current_vars: Optional[Dict[str, VariableDict]] = None,
    current_combos: Optional[List[ComboDict]] = None,
    depth: int = 0,
    visited_set: Optional[Set[str]] = None,
    is_test: bool = False,
    round_prefix: str = ""
) -> bool:
    """統一派發並執行單一動作或呼叫組合，含循環呼叫保護與變數求值"""
    if visited_set is None:
        visited_set = set()

    if not is_test:
        if not state.is_running() or state.app_state.stop_event.is_set():
            return False
        if current_vars is None:
            with state.app_state.steps_lock:
                current_vars = copy.deepcopy(state.app_state.active_variables)
        if current_combos is None:
            with state.app_state.steps_lock:
                current_combos = copy.deepcopy(state.app_state.active_combos)
    else:
        if state.app_state.stop_event.is_set():
            return False
        if current_vars is None:
            current_vars = state.app_state.test_variables
        if current_combos is None:
            current_combos = state.app_state.test_combos

    use_bg = state.app_state.use_bg and IS_WINDOWS and (state.app_state.target_hwnd is not None)
    off_x = state.app_state.offset_x
    off_y = state.app_state.offset_y

    # 若在前台模式且有綁定目標視窗，自動將目標視窗置頂以確保能接收點擊與按鍵
    if not use_bg and IS_WINDOWS and state.app_state.target_hwnd:
        force_bring_window_to_front(state.app_state.target_hwnd)

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
        with state.app_state.steps_lock:
            v_data = state.app_state.active_variables.get(var_name)
        if not v_data and current_vars:
            v_data = current_vars.get(var_name)

    atype = act.get("type")
    handler = ACTION_HANDLERS.get(atype)
    if handler:
        return handler(act, parent_desc, current_vars, current_combos, depth, visited_set, is_test, round_prefix, use_bg, off_x, off_y, log_tag, var_name, v_data)
    
    return True

def execute_single_action(act, desc):
    """執行單一動作（試跑用途）"""
    dispatch_action(act, desc, is_test=True)

def sync_periodic_timers(periodic_tasks_runtime, active_task_id=None, current_round=0):
    """線程安全地同步背景定時任務當前計時器快照至 state.app_state.periodic_timers 供 UI 即時倒數與設定值展示"""
    timers = {}
    for idx, pt in enumerate(periodic_tasks_runtime):
        pt_id = pt.get("id") or f"pt_idx_{idx}"
        try:
            interval = float(pt.get("interval", 1.0))
        except (ValueError, TypeError):
            interval = 1.0
        try:
            round_interval = int(pt.get("round_interval", 1))
        except (ValueError, TypeError):
            round_interval = 1
        timers[pt_id] = {
            "trigger_mode": pt.get("trigger_mode", "interval"),
            "last_run": pt.get("last_run", 0.0),
            "interval": interval,
            "round_interval": round_interval,
            "last_run_round": pt.get("last_run_round", 0),
            "current_round": current_round,
            "enabled": pt.get("enabled", True),
            "is_active": (pt_id == active_task_id)
        }
    with state.app_state.periodic_timers_lock:
        state.app_state.periodic_timers = timers

class TriggerContext:
    def __init__(self, current_round, is_round_end, is_startup):
        self.current_round = current_round
        self.is_round_end = is_round_end
        self.is_startup = is_startup

class TriggerStrategy:
    def is_due(self, task, context):
        return False
    def get_log_message(self, task, context, round_prefix=""):
        return ""

class IntervalTriggerStrategy(TriggerStrategy):
    def is_due(self, task, context):
        if context.is_startup:
            return task.get("run_on_start", False)
        try:
            interval = float(task.get("interval", 1.0))
        except (ValueError, TypeError):
            interval = 1.0
        if interval <= 0: interval = 1.0
        return time.time() - task.get("last_run", 0.0) >= interval

    def get_log_message(self, task, context, round_prefix=""):
        task_name = task.get("name", "").strip() or "定時任務"
        interval = task.get("interval", 1.0)
        return f"{round_prefix}任務【{task_name}】到期觸發 (每 {interval}s)"

class RoundTriggerStrategy(TriggerStrategy):
    def is_due(self, task, context):
        if context.is_startup:
            return task.get("run_on_start", False)
        if not context.is_round_end:
            return False
        try:
            round_interval = int(task.get("round_interval", 1))
        except (ValueError, TypeError):
            round_interval = 1
        if round_interval < 1: round_interval = 1
        return context.current_round - task.get("last_run_round", 0) >= round_interval

    def get_log_message(self, task, context, round_prefix=""):
        task_name = task.get("name", "").strip() or "定時任務"
        if context.is_startup:
            return f"{round_prefix}任務【{task_name}】啟動首發"
        round_interval = task.get("round_interval", 1)
        return f"{round_prefix}任務【{task_name}】達到第 {context.current_round} 輪觸發 (每 {round_interval} 輪)"

def get_trigger_strategy(trigger_mode):
    if trigger_mode == "round":
        return RoundTriggerStrategy()
    return IntervalTriggerStrategy()

def check_and_run_due_periodic_tasks(
    periodic_tasks_runtime: List[Dict],
    current_vars: Optional[Dict[str, VariableDict]],
    current_combos: Optional[List[ComboDict]],
    round_prefix: str = "",
    next_step_idx: Optional[int] = None,
    current_round: int = 0,
    is_round_end: bool = False,
    is_startup: bool = False
) -> bool:
    """檢查是否有已到期的定時任務（支援時間間隔與循環輪次雙觸發模式）；若有，安全依序執行並更新時間/輪次戳記"""
    if not periodic_tasks_runtime:
        return True

    ctx = TriggerContext(current_round, is_round_end, is_startup)

    for idx, pt in enumerate(periodic_tasks_runtime):
        if not pt.get("enabled", True):
            continue

        strategy = get_trigger_strategy(pt.get("trigger_mode", "interval"))
        
        if strategy.is_due(pt, ctx):
            if not state.is_running() or state.app_state.stop_event.is_set():
                return False
            if IS_WINDOWS and state.app_state.target_hwnd and not is_window_alive(state.app_state.target_hwnd):
                return False
            task_name = pt.get("name", "").strip() or "定時任務"
            pt_id = pt.get("id") or f"pt_idx_{idx}"
            act = pt.get("action", {})
            log_msg = strategy.get_log_message(pt, ctx, round_prefix)
            EventBus.emit(AppEvents.LOG_MESSAGE, "定時", log_msg)
            # 定時任務執行期間：
            # 1. 若有指定下一動 (next_step_idx)，在主畫面流程清單中以待命暖金色標記即將接續執行的動作，
            #    讓使用者一眼看清定時任務完結後會執行邊個動作；否則清除高亮
            if next_step_idx is not None:
                EventBus.emit(AppEvents.HIGHLIGHT_PENDING_STEP, next_step_idx)
            else:
                EventBus.emit(AppEvents.CLEAR_HIGHLIGHT_STEP)

            # 2. 高亮當前執行的定時任務卡片
            EventBus.emit(AppEvents.HIGHLIGHT_PERIODIC_TASK, idx)

            sync_periodic_timers(periodic_tasks_runtime, active_task_id=pt_id, current_round=current_round)

            try:
                # 統一透過 dispatch_action 執行
                ok = dispatch_action(
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
                EventBus.emit(AppEvents.CLEAR_HIGHLIGHT_PERIODIC_TASK)
            pt["last_run"] = time.time()
            pt["last_run_round"] = current_round
            sync_periodic_timers(periodic_tasks_runtime, active_task_id=None, current_round=current_round)
            if not ok:
                return False
            if not safe_sleep(constants.SLEEP_TEST_MODE):
                return False
    return True

def _apply_hot_reload(round_idx: int, periodic_tasks_runtime: List[Dict]) -> Tuple[List[Dict], List[ComboDict], Dict[str, VariableDict]]:
    """套用熱更新，並回傳最新的 steps, combos, variables"""
    state.app_state.reload_requested = False
    current_steps = state.fast_deepcopy(state.app_state.active_steps)
    current_combos = state.fast_deepcopy(state.app_state.active_combos)
    current_variables = state.fast_deepcopy(state.app_state.active_variables)
    latest_pts = state.fast_deepcopy(state.app_state.active_periodic_tasks)

    # 平滑套用熱更新，保留進行中定時任務的上次執行計時與輪次
    existing_timers = {
        pt.get("id"): (pt.get("last_run"), pt.get("last_run_round", 0))
        for pt in periodic_tasks_runtime if pt.get("id")
    }
    new_runtime = []
    now = time.time()
    for pt in latest_pts:
        pt_copy = copy.deepcopy(pt)
        pt_id = pt_copy.get("id")
        if pt_id in existing_timers:
            pt_copy["last_run"], pt_copy["last_run_round"] = existing_timers[pt_id]
        else:
            pt_copy["last_run"] = 0.0 if pt.get("run_on_start", False) else now
            pt_copy["last_run_round"] = round_idx
        new_runtime.append(pt_copy)
    periodic_tasks_runtime[:] = new_runtime
    sync_periodic_timers(periodic_tasks_runtime, current_round=round_idx)
    msg = f"第 {round_idx} 輪: 已自動套用最新流程與定時任務！"
    EventBus.emit(AppEvents.LOG_MESSAGE, "系統", f"⚡ {msg}")
    
    return current_steps, current_combos, current_variables

def _execute_round_steps(
    current_steps: List[Dict],
    current_variables: Dict[str, VariableDict],
    current_combos: List[ComboDict],
    periodic_tasks_runtime: List[Dict],
    round_idx: int
) -> bool:
    """執行一輪的所有步驟，回傳是否應繼續執行"""
    EventBus.emit(AppEvents.LOG_MESSAGE, "系統", f"--- 開始第 {round_idx} 輪循環 ---")
    sync_periodic_timers(periodic_tasks_runtime, current_round=round_idx)

    for idx, step in enumerate(current_steps):
        if not state.is_running() or state.app_state.stop_event.is_set():
            return False

        if IS_WINDOWS and state.app_state.target_hwnd and not is_window_alive(state.app_state.target_hwnd):
            msg = "目標遊戲視窗已關閉或崩潰，巨集已自動安全停止！"
            EventBus.emit(AppEvents.LOG_MESSAGE, "警示", f"✕ {msg}")
            state.set_running(False)
            return False

        EventBus.emit(AppEvents.HIGHLIGHT_STEP, idx)
        pfx = f"第 {round_idx} 輪: "

        stype = step.get("type")
        step_ok = True
        if stype == "combo":
            c_name = step.get("name", "組合")
            sub_actions = step.get("actions", [])
            sub_total = len(sub_actions)
            for a_idx, act in enumerate(sub_actions):
                if not state.is_running() or state.app_state.stop_event.is_set():
                    step_ok = False
                    break
                EventBus.emit(AppEvents.HIGHLIGHT_STEP, idx, sub_idx=a_idx)
                if not dispatch_action(
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

        if not step_ok or not state.is_running() or state.app_state.stop_event.is_set():
            return False

        # 當前步驟或 COMBO 已完全執行結束！安全檢查並執行到期的定時任務（非每輪結束，僅 interval 任務判定）
        next_step = (idx + 1) if (idx + 1 < len(current_steps)) else 0
        if not check_and_run_due_periodic_tasks(periodic_tasks_runtime, current_variables, current_combos, round_prefix=pfx, next_step_idx=next_step, current_round=round_idx, is_round_end=False):
            return False

    return True

def macro_worker_loop() -> None:
    """背景巨集循環執行緒主迴圈"""
    round_idx = 1
    with state.app_state.steps_lock:
        active_pts = state.fast_deepcopy(state.app_state.active_periodic_tasks)
        current_steps = state.fast_deepcopy(state.app_state.active_steps)
        current_combos = state.fast_deepcopy(state.app_state.active_combos)
        current_variables = state.fast_deepcopy(state.app_state.active_variables)

    start_time = time.time()
    periodic_tasks_runtime = []
    for pt in active_pts:
        pt_copy = copy.deepcopy(pt)
        # 若勾選「啟動時立即首發一次」，則設定 last_run 為 0，首度檢查時即觸發；否則設為 start_time，待滿 interval 秒後首發
        pt_copy["last_run"] = 0.0 if pt.get("run_on_start", False) else start_time
        pt_copy["last_run_round"] = 0
        periodic_tasks_runtime.append(pt_copy)
    sync_periodic_timers(periodic_tasks_runtime, current_round=0)

    try:
        # 首輪開始前：若有設定「啟動時立即首發」的定時任務，先檢查執行一次
        first_next_idx = 0 if current_steps else None
        if not check_and_run_due_periodic_tasks(
            periodic_tasks_runtime,
            current_variables,
            current_combos,
            round_prefix="啟動首發: ",
            next_step_idx=first_next_idx,
            current_round=0,
            is_round_end=False,
            is_startup=True
        ):
            return

        while state.is_running() and not state.app_state.stop_event.is_set():
            if IS_WINDOWS and state.app_state.target_hwnd and not is_window_alive(state.app_state.target_hwnd):
                msg = "目標遊戲視窗已關閉或崩潰，巨集已自動安全停止！"
                EventBus.emit(AppEvents.LOG_MESSAGE, "警示", f"✕ {msg}")
                state.set_running(False)
                break

            with state.app_state.steps_lock:
                was_reloaded = state.app_state.reload_requested

            if was_reloaded:
                with state.app_state.steps_lock:
                    current_steps, current_combos, current_variables = _apply_hot_reload(round_idx, periodic_tasks_runtime)

            has_enabled_periodic = any(pt.get("enabled", True) for pt in periodic_tasks_runtime)
            if not current_steps and not has_enabled_periodic:
                msg = "掛機流程清單與定時任務均為空，巨集已自動停止！"
                EventBus.emit(AppEvents.LOG_MESSAGE, "警示", msg)
                state.set_running(False)
                break

            if not current_steps:
                # 若主流程為空但有啟用的定時任務，進行待命定時輪詢
                if not check_and_run_due_periodic_tasks(periodic_tasks_runtime, current_variables, current_combos, round_prefix="", current_round=round_idx, is_round_end=False):
                    break
                if not safe_sleep(0.1):
                    break
                continue

            if not _execute_round_steps(current_steps, current_variables, current_combos, periodic_tasks_runtime, round_idx):
                break

            # 輪次銜接時亦進行一次定時任務檢查（is_round_end=True，round 與 interval 任務皆判定）
            next_step = 0 if current_steps else None
            if not check_and_run_due_periodic_tasks(periodic_tasks_runtime, current_variables, current_combos, round_prefix=f"第 {round_idx} 輪結束: ", next_step_idx=next_step, current_round=round_idx, is_round_end=True):
                break

            round_idx += 1
            if not safe_sleep(constants.SLEEP_TEST_MODE):
                break
    except Exception as e:
        EventBus.emit(AppEvents.LOG_MESSAGE, "警示", f"✕ 異常中斷: {e}")
    finally:
        state.set_running(False)
        with state.app_state.periodic_timers_lock:
            state.app_state.periodic_timers.clear()
        emergency_release_all()
        
        completed = round_idx - 1 if round_idx > 1 else (1 if round_idx == 1 and not state.app_state.stop_event.is_set() else 0)
        EventBus.emit(AppEvents.LOG_MESSAGE, "系統", f"⏹ 巨集循環結束 (累計運行 {completed} 輪)")
        EventBus.emit(AppEvents.MACRO_STOPPED)

def test_run_execution_flow_worker():
    """一次性試跑整個掛機執行流程的背景工作函式"""
    try:
        steps_copy = state.app_state.test_steps
        combos_copy = state.app_state.test_combos
        vars_copy = state.app_state.test_variables

        for idx, step in enumerate(steps_copy):
            if state.app_state.stop_event.is_set():
                break
            if IS_WINDOWS and state.app_state.target_hwnd and not is_window_alive(state.app_state.target_hwnd):
                msg = "目標遊戲視窗已關閉，試跑流程中止！"
                EventBus.emit(AppEvents.LOG_MESSAGE, "警示", f"✕ {msg}")
                break
            EventBus.emit(AppEvents.HIGHLIGHT_STEP, idx)
            pfx = "[試跑流程] "
            stype = step.get("type")
            if stype == "combo":
                c_name = step.get("name", "組合")
                sub_actions = step.get("actions", [])
                if not sub_actions:
                    EventBus.emit(AppEvents.LOG_MESSAGE, "試跑", f"[試跑流程] 步驟 #{idx+1} 組合 [{c_name}] 內無動作，跳過")
                    continue
                for a_idx, act in enumerate(sub_actions):
                    if state.app_state.stop_event.is_set():
                        return
                    EventBus.emit(AppEvents.HIGHLIGHT_STEP, idx, sub_idx=a_idx)
                    if not dispatch_action(
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
        EventBus.emit(AppEvents.LOG_MESSAGE, "警示", f"✕ 試跑流程異常: {e}")
    finally:
        EventBus.emit(AppEvents.CLEAR_HIGHLIGHT_STEP)
        EventBus.emit(AppEvents.MACRO_STOPPED)
