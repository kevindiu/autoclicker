import sys
import copy
import json
import threading
from contextlib import contextmanager


class AppState:
    """全域巨集運作與資料狀態封裝類別
    
    將所有原本散落在模組級的全域變數（編輯器草稿、背景執行期快照、執行緒鎖、事件旗標）
    統一封裝於單一物件實例中，提供乾淨的狀態重設、單元測試隔離以及明確的屬性存取。
    """
    def __init__(self):
        # 1. 編輯器草稿資料 (Draft Data)
        self.combos = []
        self.steps = []           # 主 UI 編輯器草稿 (Draft)
        self.variables = {}       # 全域變數庫字典: {var_name: {"type": "coord"|"key"|"wait", ...}}
        self.periodic_tasks = []  # 主 UI 定時任務草稿 (Draft)

        # 2. 背景運行實例快照 (Active Runtime Snapshots)
        self.active_steps = []    # 背景運行實例快照 (Active Snapshot)
        self.active_combos = []   # 背景組合運行實例快照 (Active Combo Snapshot)
        self.active_variables = {} # 背景變數運行實例快照 (Active Variables Snapshot)
        self.active_periodic_tasks = [] # 背景定時任務運行實例快照 (Active Periodic Snapshot)

        # 3. 執行期旗標與執行緒同步物件 (Flags & Thread Synchronization)
        self.running_lock = threading.RLock()
        self._running = False
        self._is_testing = False
        self.reload_requested = False
        self.steps_lock = threading.Lock() # 保護 active_steps, active_combos, active_variables 與 active_periodic_tasks
        self.stop_event = threading.Event()
        self.target_hwnd = None
        self.currently_held_keys = set()   # 追蹤當前被按下的按鍵，格式: ("bg", hwnd, vk) 或 ("fg", key_str)
        self.currently_held_keys_lock = threading.Lock()
        self.periodic_timers = {}          # 背景定時任務即時倒數計時器快照: {task_id: {"last_run": float, "interval": float, "enabled": bool, "is_active": bool}}
        self.periodic_timers_lock = threading.Lock()

    def is_running(self) -> bool:
        """線程安全地檢查巨集是否處於運行狀態"""
        with self.running_lock:
            return self._running

    def set_running(self, val: bool):
        """線程安全地設定巨集運行狀態"""
        with self.running_lock:
            self._running = bool(val)
            if not self._running and not self._is_testing:
                self.stop_event.set()

    @property
    def running(self) -> bool:
        """線程安全之運行狀態屬性"""
        return self.is_running()

    @running.setter
    def running(self, val: bool):
        self.set_running(val)

    def is_in_testing(self) -> bool:
        """線程安全地檢查是否處於試跑狀態"""
        with self.running_lock:
            return self._is_testing

    def set_testing(self, val: bool):
        """線程安全地設定試跑狀態"""
        with self.running_lock:
            self._is_testing = bool(val)
            if not self._is_testing and not self._running:
                self.stop_event.set()

    @property
    def is_testing(self) -> bool:
        """線程安全之試跑狀態屬性"""
        with self.running_lock:
            return self._is_testing

    @is_testing.setter
    def is_testing(self, val: bool):
        self.set_testing(val)

    def try_start_testing(self) -> tuple:
        """原子操作：嘗試啟動試跑狀態。
        若巨集正在循環運行中，回傳 (False, "running")；
        若已有試跑任務進行中，回傳 (False, "testing")；
        若均未運行，則原子地設定 _is_testing = True 並回傳 (True, "ok")。
        徹底消除 check-then-act 競態條件。
        """
        with self.running_lock:
            if self._running:
                return False, "running"
            if self._is_testing:
                return False, "testing"
            self._is_testing = True
            return True, "ok"

    def stop_testing(self):
        """線程安全地停止試跑狀態"""
        self.set_testing(False)

    def reset_drafts(self):
        """清空主 UI 編輯器草稿資料"""
        self.combos.clear()
        self.steps.clear()
        self.variables.clear()
        self.periodic_tasks.clear()

    def reset_runtime(self):
        """重設背景執行階段狀態、快照與旗標"""
        with self.running_lock:
            self._running = False
            self._is_testing = False
        self.reload_requested = False
        self.target_hwnd = None
        self.stop_event.clear()
        with self.steps_lock:
            self.active_steps.clear()
            self.active_combos.clear()
            self.active_variables.clear()
            self.active_periodic_tasks.clear()
        with self.currently_held_keys_lock:
            self.currently_held_keys.clear()
        with self.periodic_timers_lock:
            self.periodic_timers.clear()

    def reset(self):
        """完全重設狀態 (適用於單元測試環境隔離與全新載入)"""
        self.reset_drafts()
        self.reset_runtime()

    def snapshot_active(self, reload_requested: bool = False):
        """將當前編輯器草稿同步至背景執行快照 (執行緒安全)"""
        with self.steps_lock:
            self.active_steps = copy.deepcopy(self.steps)
            self.active_combos = copy.deepcopy(self.combos)
            self.active_variables = copy.deepcopy(self.variables)
            self.active_periodic_tasks = copy.deepcopy(self.periodic_tasks)
            self.reload_requested = reload_requested

    def to_dict(self) -> dict:
        """將編輯器草稿資料匯出為字典"""
        return {
            "variables": copy.deepcopy(self.variables),
            "combos": copy.deepcopy(self.combos),
            "steps": copy.deepcopy(self.steps),
            "periodic_tasks": copy.deepcopy(self.periodic_tasks),
        }

    def load_dict(self, data: dict):
        """從字典載入設定資料至編輯器草稿"""
        self.variables.clear()
        self.variables.update(copy.deepcopy(data.get("variables", {})))
        self.combos.clear()
        self.combos.extend(copy.deepcopy(data.get("combos", [])))
        self.steps.clear()
        self.steps.extend(copy.deepcopy(data.get("steps", [])))
        self.periodic_tasks.clear()
        self.periodic_tasks.extend(copy.deepcopy(data.get("periodic_tasks", [])))

    def get_data_snapshot(self) -> str:
        """獲取當前編輯器資料的序列化字串，用於精確比對未儲存變更"""
        try:
            return json.dumps({
                "variables": self.variables,
                "combos": self.combos,
                "steps": self.steps,
                "periodic_tasks": self.periodic_tasks,
            }, sort_keys=True)
        except (TypeError, ValueError):
            return ""

    def has_unsaved_changes(self, last_saved_snapshot: str) -> bool:
        """檢查當前編輯器資料相較於最後儲存快照是否有變更"""
        if not last_saved_snapshot:
            return False
        return self.get_data_snapshot() != last_saved_snapshot


# ==============================================================================
# 預設全域狀態單例與管理函式
# ==============================================================================
app_state = AppState()

def get_state() -> AppState:
    """取得當前作用中的 AppState 實例"""
    return app_state

def set_state(new_state: AppState):
    """設定當前作用中的 AppState 實例"""
    global app_state
    if not isinstance(new_state, AppState):
        raise TypeError("new_state 必須是 AppState 的實例")
    app_state = new_state

@contextmanager
def use_state(temp_state: AppState):
    """上下文管理器：在區塊內臨時切換為指定的 AppState 實例 (單元測試極為便利)"""
    prev_state = app_state
    set_state(temp_state)
    try:
        yield temp_state
    finally:
        set_state(prev_state)

def is_running() -> bool:
    """線程安全地檢查巨集是否處於運行狀態 (向後相容捷徑)"""
    return app_state.is_running()

def set_running(val: bool):
    """線程安全地設定巨集運行狀態 (向後相容捷徑)"""
    app_state.set_running(val)

def is_in_testing() -> bool:
    """線程安全地檢查是否處於試跑狀態 (向後相容捷徑)"""
    return app_state.is_in_testing()

def set_testing(val: bool):
    """線程安全地設定試跑狀態 (向後相容捷徑)"""
    app_state.set_testing(val)

def try_start_testing() -> tuple:
    """原子操作：嘗試啟動試跑狀態 (向後相容捷徑)"""
    return app_state.try_start_testing()

def stop_testing():
    """線程安全地停止試跑狀態 (向後相容捷徑)"""
    app_state.stop_testing()

def reset():
    """完全重設當前全域狀態 (保證只進行原地修改，絕不重新賦值新物件)"""
    app_state.reset()

def get_data_snapshot(target_state=None) -> str:
    """獲取資料快照字串 (向後相容捷徑，唯一委派至 AppState)"""
    s = target_state if target_state is not None else app_state
    if hasattr(s, "get_data_snapshot"):
        return s.get_data_snapshot()
    return app_state.get_data_snapshot()

def has_unsaved_changes(last_saved_snapshot: str, target_state=None) -> bool:
    """檢查是否有未儲存變更 (向後相容捷徑，唯一委派至 AppState)"""
    s = target_state if target_state is not None else app_state
    if hasattr(s, "has_unsaved_changes"):
        return s.has_unsaved_changes(last_saved_snapshot)
    return app_state.has_unsaved_changes(last_saved_snapshot)


# ==============================================================================
# 文字格式化輔助函數
# ==============================================================================
def format_action_summary(act, index=None, current_variables=None):
    """統一格式化動作或步驟的文字描述，採用 100% 跨平台相容的通用標籤與符號"""
    var_dict = current_variables if current_variables is not None else app_state.variables
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
    
    t_mode = task.get("trigger_mode", "interval")
    if t_mode == "round":
        try:
            r_val = int(task.get("round_interval", 1))
        except (ValueError, TypeError):
            r_val = 1
        trigger_str = f"每{r_val}輪"
    else:
        sec = task.get("interval", 1.0)
        try:
            f_sec = float(sec)
            trigger_str = f"{int(f_sec)}s" if f_sec.is_integer() else f"{f_sec}s"
        except (ValueError, TypeError):
            trigger_str = f"{sec}s"

    name = task.get("name", "").strip()
    start_str = " (首)" if task.get("run_on_start", False) else ""

    if name:
        disp_name = name if len(name) <= max_name_len else name[:max_name_len - 1] + "…"
        return f"{st_icon} {trigger_str} · {disp_name}{start_str}"

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
    return f"{st_icon} {trigger_str} · {disp_desc}{start_str}"


# ==============================================================================
# 模組自訂類別包裝 (唯一狀態代理：將模組層級屬性讀寫統一且動態委派至作用中的 app_state 實例)
# ==============================================================================
class _StateModule(sys.modules[__name__].__class__):
    """自訂模組類別，統一攔截模組屬性讀寫，保證模組層級存取與 app_state 保持 100% 雙向動態同步"""
    @property
    def running(self):
        return app_state.running

    @running.setter
    def running(self, val):
        app_state.running = val

    @property
    def is_testing(self):
        return app_state.is_testing

    @is_testing.setter
    def is_testing(self, val):
        app_state.is_testing = val

    def __getattr__(self, name):
        if hasattr(app_state, name):
            return getattr(app_state, name)
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    def __setattr__(self, name, value):
        if name in ("app_state", "__class__"):
            super().__setattr__(name, value)
        elif hasattr(app_state, name):
            setattr(app_state, name, value)
        else:
            super().__setattr__(name, value)

    def __dir__(self):
        return sorted(set(super().__dir__() + dir(app_state)))

sys.modules[__name__].__class__ = _StateModule
