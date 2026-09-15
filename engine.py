import copy
import time
import traceback
from typing import Dict, List, Any, Optional, Set, Tuple
from contextlib import contextmanager

import constants
from models import Variable, Action, Combo, PeriodicTask, ClickAction, KeyAction, WaitAction, CallComboAction, ComboAction
import state
from events import EventBus, AppEvents

from win32_api import (
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

class ExecutionContext:
    """封裝動作執行期間的所有狀態與依賴，減少參數傳遞數量並方便單元測試 mock"""
    def __init__(self, app_state: 'state.AppState', current_vars: Dict[str, Variable], current_combos: List[Combo],
                 depth: int, visited_set: Set[str], is_test: bool, round_prefix: str,
                 use_bg: bool, off_x: int, off_y: int, log_tag: str):
        self.app_state = app_state
        self.current_vars = current_vars
        self.current_combos = current_combos
        self.depth = depth
        self.visited_set = visited_set
        self.is_test = is_test
        self.round_prefix = round_prefix
        self.use_bg = use_bg
        self.off_x = off_x
        self.off_y = off_y
        self.log_tag = log_tag

class ActionStrategy:
    def execute(self, act: Action, ctx: ExecutionContext, parent_desc: str, var_name: str, v_data: Optional[Variable]) -> bool:
        raise NotImplementedError

class ClickActionStrategy(ActionStrategy):
    def execute(self, act: Action, ctx: ExecutionContext, parent_desc: str, var_name: str, v_data: Optional[Variable]) -> bool:
        try:
            x = int(act.x)
            y = int(act.y)
        except (ValueError, TypeError):
            x, y = 0, 0
        btn = act.btn
        is_rel = act.rel
        if v_data and v_data.type == "coord":
            val = v_data.value
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
            is_rel = True if ctx.app_state.target_hwnd else False
        msg = execute_click(ctx.app_state, x, y, is_rel, ctx.use_bg, ctx.off_x, ctx.off_y, btn=btn)
        var_info = f"【{var_name}】" if var_name else ""
        log_txt = f"{ctx.round_prefix}{parent_desc} {var_info}{msg}"
        EventBus.emit(AppEvents.LOG_MESSAGE, ctx.log_tag, log_txt)
        if not safe_sleep(ctx.app_state, constants.SLEEP_CLICK, ctx.app_state.stop_event):
            return False
        return True

class KeyActionStrategy(ActionStrategy):
    def execute(self, act: Action, ctx: ExecutionContext, parent_desc: str, var_name: str, v_data: Optional[Variable]) -> bool:
        key = str(act.key)
        if v_data and v_data.type == "key":
            key = str(v_data.value)
        if ctx.use_bg:
            post_bg_key(ctx.app_state, ctx.app_state.target_hwnd, key)
        else:
            with ctx.app_state.currently_held_keys_lock:
                ctx.app_state.currently_held_keys.add(("fg", key))
            try:
                _get_pyautogui().keyDown(key)
                if not safe_sleep(ctx.app_state, constants.SLEEP_KEY_FG, ctx.app_state.stop_event):
                    return False
            finally:
                try:
                    _get_pyautogui().keyUp(key)
                except Exception as e:
                    EventBus.emit(AppEvents.LOG_MESSAGE, "警示", f"釋放前台按鍵 [{key}] 失敗: {e}")
                with ctx.app_state.currently_held_keys_lock:
                    ctx.app_state.currently_held_keys.discard(("fg", key))
        var_info = f"【{var_name}】" if var_name else ""
        mode_tag = " (後台)" if ctx.use_bg else " (前台)"
        EventBus.emit(AppEvents.LOG_MESSAGE, ctx.log_tag, f"{ctx.round_prefix}{parent_desc} {var_info}按鍵 [{key.upper()}]{mode_tag}")
        if not safe_sleep(ctx.app_state, constants.SLEEP_KEY_AFTER, ctx.app_state.stop_event):
            return False
        return True

class WaitActionStrategy(ActionStrategy):
    def execute(self, act: Action, ctx: ExecutionContext, parent_desc: str, var_name: str, v_data: Optional[Variable]) -> bool:
        try:
            sec = float(act.sec)
        except (ValueError, TypeError):
            sec = 0.5
        if v_data and v_data.type == "wait":
            try:
                sec = float(v_data.value)
            except (ValueError, TypeError):
                EventBus.emit(AppEvents.LOG_MESSAGE, "警示", f"變數【{var_name}】等待秒數數值格式無效，使用預設值 {sec}s")
        var_info = f"【{var_name}】" if var_name else ""
        log_txt = f"{ctx.round_prefix}{parent_desc} {var_info}等待 {sec}s"
        EventBus.emit(AppEvents.LOG_MESSAGE, ctx.log_tag, log_txt)
        if not safe_sleep(ctx.app_state, sec, ctx.app_state.stop_event):
            return False
        return True

class CallComboActionStrategy(ActionStrategy):
    def execute(self, act: Action, ctx: ExecutionContext, parent_desc: str, var_name: str, v_data: Optional[Variable]) -> bool:
        tgt_name = act.target_name
        if not tgt_name:
            return True
        if ctx.depth >= constants.MAX_COMBO_DEPTH:
            warn_msg = f"{ctx.round_prefix}呼叫 [{tgt_name}] 超過深度上限"
            EventBus.emit(AppEvents.LOG_MESSAGE, "警示", warn_msg)
            return True
        if tgt_name in ctx.visited_set:
            warn_msg = f"{ctx.round_prefix}循環呼叫 [{tgt_name}]，自動跳過"
            EventBus.emit(AppEvents.LOG_MESSAGE, "警示", warn_msg)
            return True

        tgt_combo = next((c for c in ctx.current_combos if c.name == tgt_name), None)
        if tgt_combo:
            new_visited = ctx.visited_set | {tgt_name}
            sub_actions = tgt_combo.actions
            sub_total = len(sub_actions)
            for sub_idx, sub_act in enumerate(sub_actions):
                if not ctx.is_test and (not ctx.app_state.is_running() or ctx.app_state.stop_event.is_set()):
                    return False
                if ctx.is_test and ctx.app_state.stop_event.is_set():
                    return False
                sub_desc = f"{parent_desc}->[{tgt_name}#{sub_idx+1}/{sub_total}]"
                if not dispatch_action(
                    ctx.app_state,
                    sub_act,
                    sub_desc,
                    current_vars=ctx.current_vars,
                    current_combos=ctx.current_combos,
                    depth=ctx.depth + 1,
                    visited_set=new_visited,
                    is_test=ctx.is_test,
                    round_prefix=ctx.round_prefix
                ):
                    return False
        else:
            warn_msg = f"{ctx.round_prefix}找不到被呼叫的組合 [{tgt_name}]"
            EventBus.emit(AppEvents.LOG_MESSAGE, "警示", warn_msg)

        return True

ACTION_HANDLERS = {
    "click": ClickActionStrategy(),
    "key": KeyActionStrategy(),
    "wait": WaitActionStrategy(),
    "call_combo": CallComboActionStrategy()
}

def dispatch_action(
    app_state: 'state.AppState',
    act: Action,
    parent_desc: str,
    current_vars: Optional[Dict[str, Variable]] = None,
    current_combos: Optional[List[Combo]] = None,
    depth: int = 0,
    visited_set: Optional[Set[str]] = None,
    is_test: bool = False,
    round_prefix: str = ""
) -> bool:
    """統一派發並執行單一動作或呼叫組合，含循環呼叫保護與變數求值"""
    if visited_set is None:
        visited_set = set()

    if not is_test:
        if not app_state.is_running() or app_state.stop_event.is_set():
            return False
        if current_vars is None:
            with app_state.steps_lock:
                current_vars = copy.deepcopy(app_state.active_variables)
        if current_combos is None:
            with app_state.steps_lock:
                current_combos = copy.deepcopy(app_state.active_combos)
    else:
        if app_state.stop_event.is_set():
            return False
        if current_vars is None:
            current_vars = app_state.test_variables
        if current_combos is None:
            current_combos = app_state.test_combos

    use_bg = app_state.use_bg and (app_state.target_hwnd is not None)
    off_x = app_state.offset_x
    off_y = app_state.offset_y

    # 若在前台模式且有綁定目標視窗，自動將目標視窗置頂以確保能接收點擊與按鍵
    if not use_bg and app_state.target_hwnd:
        force_bring_window_to_front(app_state.target_hwnd)

    if is_test:
        log_tag = "試跑"
    elif "[定時:" in parent_desc:
        log_tag = "定時"
    elif depth > 0 or ("[" in parent_desc and ("#" in parent_desc or "組合" in parent_desc)):
        log_tag = "組合"
    else:
        log_tag = "流程"

    var_name = act.var_name
    v_data = None
    if var_name:
        with app_state.steps_lock:
            v_data = app_state.active_variables.get(var_name)
        if not v_data and current_vars:
            v_data = current_vars.get(var_name)

    atype = act.type
    strategy = ACTION_HANDLERS.get(atype)
    if strategy:
        ctx = ExecutionContext(app_state, current_vars, current_combos, depth, visited_set, is_test, round_prefix, use_bg, off_x, off_y, log_tag)
        return strategy.execute(act, ctx, parent_desc, var_name, v_data)
    
    return True

def execute_single_action(app_state: 'state.AppState', act, desc):
    """執行單一動作（試跑用途）"""
    dispatch_action(app_state, act, desc, is_test=True)

def sync_periodic_timers(app_state: 'state.AppState', periodic_tasks_runtime: List[PeriodicTask], active_task_id=None, current_round=0):
    """線程安全地同步背景定時任務當前計時器快照至 app_state.periodic_timers 供 UI 即時倒數與設定值展示"""
    timers = {}
    for idx, pt in enumerate(periodic_tasks_runtime):
        pt_id = pt.id or f"pt_idx_{idx}"
        interval = pt.interval
        round_interval = pt.round_interval
        # We need to maintain last_run state in the dataclass itself, but since dataclass instance is passed around, we can inject these runtime states or store them in a runtime dict.
        # Let's assume the pt object receives these fields during runtime via setattr
        timers[pt_id] = {
            "trigger_mode": pt.trigger_mode,
            "last_run": getattr(pt, "last_run", 0.0),
            "interval": interval,
            "round_interval": round_interval,
            "last_run_round": getattr(pt, "last_run_round", 0),
            "current_round": current_round,
            "enabled": pt.enabled,
            "is_active": (pt_id == active_task_id)
        }
    with app_state.periodic_timers_lock:
        app_state.periodic_timers = timers

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
    def is_due(self, task: PeriodicTask, context):
        if context.is_startup:
            return task.run_on_start
        interval = task.interval
        if interval <= 0: interval = 1.0
        return time.time() - getattr(task, "last_run", 0.0) >= interval

    def get_log_message(self, task: PeriodicTask, context, round_prefix=""):
        task_name = task.name.strip() or "定時任務"
        interval = task.interval
        return f"{round_prefix}任務【{task_name}】到期觸發 (每 {interval}s)"

class RoundTriggerStrategy(TriggerStrategy):
    def is_due(self, task: PeriodicTask, context):
        if context.is_startup:
            return task.run_on_start
        if not context.is_round_end:
            return False
        round_interval = task.round_interval
        if round_interval < 1: round_interval = 1
        return context.current_round - getattr(task, "last_run_round", 0) >= round_interval

    def get_log_message(self, task: PeriodicTask, context, round_prefix=""):
        task_name = task.name.strip() or "定時任務"
        if context.is_startup:
            return f"{round_prefix}任務【{task_name}】啟動首發"
        round_interval = task.round_interval
        return f"{round_prefix}任務【{task_name}】達到第 {context.current_round} 輪觸發 (每 {round_interval} 輪)"

def get_trigger_strategy(trigger_mode):
    if trigger_mode == "round":
        return RoundTriggerStrategy()
    return IntervalTriggerStrategy()

def check_and_run_due_periodic_tasks(
    app_state: 'state.AppState',
    periodic_tasks_runtime: List[PeriodicTask],
    current_vars: Optional[Dict[str, Variable]],
    current_combos: Optional[List[Combo]],
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
        if not pt.enabled:
            continue

        strategy = get_trigger_strategy(pt.trigger_mode)
        
        if strategy.is_due(pt, ctx):
            if not app_state.is_running() or app_state.stop_event.is_set():
                return False
            if app_state.target_hwnd and not is_window_alive(app_state.target_hwnd):
                return False
            task_name = getattr(pt, "name", "定時任務").strip() or "定時任務"
            pt_id = getattr(pt, "id", f"pt_idx_{idx}")
            act = getattr(pt, "action", {})
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

            sync_periodic_timers(app_state, periodic_tasks_runtime, active_task_id=pt_id, current_round=current_round)

            try:
                # 統一透過 dispatch_action 執行
                ok = dispatch_action(
                    app_state,
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
            sync_periodic_timers(app_state, periodic_tasks_runtime, active_task_id=None, current_round=current_round)
            if not ok:
                return False
            if not safe_sleep(app_state, constants.SLEEP_TEST_MODE, app_state.stop_event):
                return False
    return True

def _apply_hot_reload(app_state: 'state.AppState', round_idx: int, periodic_tasks_runtime: List[PeriodicTask]) -> Tuple[List[Action], List[Combo], Dict[str, Variable]]:
    """套用熱更新，並回傳最新的 steps, combos, variables"""
    app_state.reload_requested = False
    current_steps = state.fast_deepcopy(app_state.active_steps)
    current_combos = state.fast_deepcopy(app_state.active_combos)
    current_variables = state.fast_deepcopy(app_state.active_variables)
    latest_pts = state.fast_deepcopy(app_state.active_periodic_tasks)

    # 平滑套用熱更新，保留進行中定時任務的上次執行計時與輪次
    existing_timers = {
        getattr(pt, "id", None): (getattr(pt, "last_run", 0.0), getattr(pt, "last_run_round", 0))
        for pt in periodic_tasks_runtime if getattr(pt, "id", None)
    }
    new_runtime = []
    now = time.time()
    for pt in latest_pts:
        pt_copy = copy.deepcopy(pt)
        pt_id = getattr(pt_copy, "id", None)
        if pt_id in existing_timers:
            setattr(pt_copy, "last_run", existing_timers[pt_id][0])
            setattr(pt_copy, "last_run_round", existing_timers[pt_id][1])
        else:
            setattr(pt_copy, "last_run", 0.0 if getattr(pt, "run_on_start", False) else now)
            setattr(pt_copy, "last_run_round", round_idx)
        new_runtime.append(pt_copy)
    periodic_tasks_runtime[:] = new_runtime
    sync_periodic_timers(app_state, periodic_tasks_runtime, current_round=round_idx)
    msg = f"第 {round_idx} 輪: 已自動套用最新流程與定時任務！"
    EventBus.emit(AppEvents.LOG_MESSAGE, "系統", f"⚡ {msg}")
    
    return current_steps, current_combos, current_variables

def _execute_round_steps(
    app_state: 'state.AppState',
    current_steps: List[Action],
    current_variables: Dict[str, Variable],
    current_combos: List[Combo],
    periodic_tasks_runtime: List[PeriodicTask],
    round_idx: int
) -> bool:
    """執行一輪的所有步驟，回傳是否應繼續執行"""
    EventBus.emit(AppEvents.LOG_MESSAGE, "系統", f"--- 開始第 {round_idx} 輪循環 ---")
    sync_periodic_timers(app_state, periodic_tasks_runtime, current_round=round_idx)

    for idx, step in enumerate(current_steps):
        if not app_state.is_running() or app_state.stop_event.is_set():
            return False

        if app_state.target_hwnd and not is_window_alive(app_state.target_hwnd):
            msg = "目標遊戲視窗已關閉或崩潰，巨集已自動安全停止！"
            EventBus.emit(AppEvents.LOG_MESSAGE, "警示", f"✕ {msg}")
            app_state.set_running(False)
            return False

        EventBus.emit(AppEvents.HIGHLIGHT_STEP, idx)
        pfx = f"第 {round_idx} 輪: "

        stype = getattr(step, "type", None)
        step_ok = True
        if stype == "combo":
            c_name = getattr(step, "name", "組合")
            sub_actions = getattr(step, "actions", [])
            sub_total = len(sub_actions)
            for a_idx, act in enumerate(sub_actions):
                if not app_state.is_running() or app_state.stop_event.is_set():
                    step_ok = False
                    break
                EventBus.emit(AppEvents.HIGHLIGHT_STEP, idx, sub_idx=a_idx)
                if not dispatch_action(
                    app_state,
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
                app_state,
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

        if not step_ok or not app_state.is_running() or app_state.stop_event.is_set():
            return False

        # 當前步驟或 COMBO 已完全執行結束！安全檢查並執行到期的定時任務（非每輪結束，僅 interval 任務判定）
        next_step = (idx + 1) if (idx + 1 < len(current_steps)) else 0
        if not check_and_run_due_periodic_tasks(app_state, periodic_tasks_runtime, current_variables, current_combos, round_prefix=pfx, next_step_idx=next_step, current_round=round_idx, is_round_end=False):
            return False

    return True

def macro_worker_loop(app_state: 'state.AppState') -> None:
    """背景巨集循環執行緒主迴圈"""
    round_idx = 1
    with app_state.steps_lock:
        active_pts = state.fast_deepcopy(app_state.active_periodic_tasks)
        current_steps = state.fast_deepcopy(app_state.active_steps)
        current_combos = state.fast_deepcopy(app_state.active_combos)
        current_variables = state.fast_deepcopy(app_state.active_variables)

    start_time = time.time()
    periodic_tasks_runtime = []
    for pt in active_pts:
        pt_copy = copy.deepcopy(pt)
        # 若勾選「啟動時立即首發一次」，則設定 last_run 為 0，首度檢查時即觸發；否則設為 start_time，待滿 interval 秒後首發
        pt_copy["last_run"] = 0.0 if pt.get("run_on_start", False) else start_time
        pt_copy["last_run_round"] = 0
        periodic_tasks_runtime.append(pt_copy)
    sync_periodic_timers(app_state, periodic_tasks_runtime, current_round=0)

    try:
        # 首輪開始前：若有設定「啟動時立即首發」的定時任務，先檢查執行一次
        first_next_idx = 0 if current_steps else None
        if not check_and_run_due_periodic_tasks(
            app_state,
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

        while app_state.is_running() and not app_state.stop_event.is_set():
            if app_state.target_hwnd and not is_window_alive(app_state.target_hwnd):
                msg = "目標遊戲視窗已關閉或崩潰，巨集已自動安全停止！"
                EventBus.emit(AppEvents.LOG_MESSAGE, "警示", f"✕ {msg}")
                app_state.set_running(False)
                break

            with app_state.steps_lock:
                was_reloaded = app_state.reload_requested

            if was_reloaded:
                with app_state.steps_lock:
                    current_steps, current_combos, current_variables = _apply_hot_reload(app_state, round_idx, periodic_tasks_runtime)

            has_enabled_periodic = any(pt.get("enabled", True) for pt in periodic_tasks_runtime)
            if not current_steps and not has_enabled_periodic:
                msg = "掛機流程清單與定時任務均為空，巨集已自動停止！"
                EventBus.emit(AppEvents.LOG_MESSAGE, "警示", msg)
                app_state.set_running(False)
                break

            if not current_steps:
                # 若主流程為空但有啟用的定時任務，進行待命定時輪詢
                if not check_and_run_due_periodic_tasks(app_state, periodic_tasks_runtime, current_variables, current_combos, round_prefix="", current_round=round_idx, is_round_end=False):
                    break
                if not safe_sleep(app_state, 0.1, app_state.stop_event):
                    break
                continue

            if not _execute_round_steps(app_state, current_steps, current_variables, current_combos, periodic_tasks_runtime, round_idx):
                break

            # 輪次銜接時亦進行一次定時任務檢查（is_round_end=True，round 與 interval 任務皆判定）
            next_step = 0 if current_steps else None
            if not check_and_run_due_periodic_tasks(app_state, periodic_tasks_runtime, current_variables, current_combos, round_prefix=f"第 {round_idx} 輪結束: ", next_step_idx=next_step, current_round=round_idx, is_round_end=True):
                break

            round_idx += 1
            if not safe_sleep(app_state, constants.SLEEP_TEST_MODE, app_state.stop_event):
                break
    except Exception as e:
        EventBus.emit(AppEvents.LOG_MESSAGE, "警示", f"✕ 異常中斷: {e}")
    finally:
        app_state.set_running(False)
        with app_state.periodic_timers_lock:
            app_state.periodic_timers.clear()
        emergency_release_all(app_state)
        
        completed = round_idx - 1 if round_idx > 1 else (1 if round_idx == 1 and not app_state.stop_event.is_set() else 0)
        EventBus.emit(AppEvents.LOG_MESSAGE, "系統", f"⏹ 巨集循環結束 (累計運行 {completed} 輪)")
        EventBus.emit(AppEvents.MACRO_STOPPED)

def test_run_execution_flow_worker(app_state: 'state.AppState'):
    """一次性試跑整個掛機執行流程的背景工作函式"""
    try:
        steps_copy = app_state.test_steps
        combos_copy = app_state.test_combos
        vars_copy = app_state.test_variables

        for idx, step in enumerate(steps_copy):
            if app_state.stop_event.is_set():
                break
            if app_state.target_hwnd and not is_window_alive(app_state.target_hwnd):
                msg = "目標遊戲視窗已關閉，試跑流程中止！"
                EventBus.emit(AppEvents.LOG_MESSAGE, "警示", f"✕ {msg}")
                break
            EventBus.emit(AppEvents.HIGHLIGHT_STEP, idx)
            pfx = "[試跑流程] "
            stype = getattr(step, "type", None)
            if stype == "combo":
                c_name = getattr(step, "name", "組合")
                sub_actions = getattr(step, "actions", [])
                if not sub_actions:
                    EventBus.emit(AppEvents.LOG_MESSAGE, "試跑", f"[試跑流程] 步驟 #{idx+1} 組合 [{c_name}] 內無動作，跳過")
                    continue
                for a_idx, act in enumerate(sub_actions):
                    if app_state.stop_event.is_set():
                        return
                    EventBus.emit(AppEvents.HIGHLIGHT_STEP, idx, sub_idx=a_idx)
                    if not dispatch_action(
                        app_state,
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
                    app_state,
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
