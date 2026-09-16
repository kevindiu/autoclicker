import sys
import copy
import json
import dataclasses
from dataclasses import dataclass, field


def fast_deepcopy(obj):
    """
    自定義高速深拷貝：原生支援 dataclass、list、dict 的遞迴複製。
    比原生 copy.deepcopy() 避免了 memoization 字典開銷，能大幅降低 CPU 峰值。
    """
    if obj is None:
        return None
    if isinstance(obj, list):
        return [fast_deepcopy(item) for item in obj]
    if isinstance(obj, dict):
        return {k: fast_deepcopy(v) for k, v in obj.items()}
    if dataclasses.is_dataclass(obj):
        kwargs = {f.name: fast_deepcopy(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
        return obj.__class__(**kwargs)
    if isinstance(obj, (int, float, str, bool, tuple)):
        return obj
    return copy.deepcopy(obj)

import json
import threading
from typing import Dict, List, Any, Optional
from models import Variable, Action, Combo, PeriodicTask, ClickAction, KeyAction, WaitAction, CallComboAction, ComboAction


@dataclass
class AppState:
    """全域巨集運作與資料狀態封裝類別
    
    將所有原本散落在模組級的全域變數（編輯器草稿、背景執行期快照、執行緒鎖、事件旗標）
    統一封裝於單一物件實例中，提供乾淨的狀態重設、單元測試隔離以及明確的屬性存取。
    """
    # 1. 編輯器草稿資料 (Draft Data)
    combos: List[Combo] = field(default_factory=list)
    steps: List[Action] = field(default_factory=list)
    variables: Dict[str, Variable] = field(default_factory=dict)
    periodic_tasks: List[PeriodicTask] = field(default_factory=list)

    # 2. 背景運行實例快照 (Active Runtime Snapshots)
    active_steps: List[Action] = field(default_factory=list)
    active_combos: List[Combo] = field(default_factory=list)
    active_variables: Dict[str, Variable] = field(default_factory=dict)
    active_periodic_tasks: List[PeriodicTask] = field(default_factory=list)

    # 3. 試跑專屬唯讀快照 (Test Run Read-Only Snapshots)
    test_steps: List[Action] = field(default_factory=list)
    test_combos: List[Combo] = field(default_factory=list)
    test_variables: Dict[str, Variable] = field(default_factory=dict)

    # 4. 執行期旗標與執行緒同步物件 (Flags & Thread Synchronization)
    running_lock: threading.RLock = field(default_factory=threading.RLock)
    _running: bool = False
    _is_testing: bool = False
    _reload_requested: bool = False

    # 4. 運行環境設定 (Runtime Configuration)
    use_bg: bool = True
    offset_x: int = 0
    offset_y: int = 0

    steps_lock: threading.Lock = field(default_factory=threading.Lock)
    stop_event: threading.Event = field(default_factory=threading.Event)
    target_hwnd: Any = None
    currently_held_keys: set = field(default_factory=set)
    currently_held_keys_lock: threading.Lock = field(default_factory=threading.Lock)
    periodic_timers: dict = field(default_factory=dict)
    periodic_timers_lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        """確保 dataclass 版仍保留舊有初始化語義。"""
        self.stop_event = getattr(self, "stop_event", threading.Event())
        self.steps_lock = getattr(self, "steps_lock", threading.Lock())
        self.currently_held_keys_lock = getattr(self, "currently_held_keys_lock", threading.Lock())
        self.periodic_timers_lock = getattr(self, "periodic_timers_lock", threading.Lock())

    def is_running(self) -> bool:
        """線程安全地檢查巨集是否處於運行狀態"""
        with self.running_lock:
            return self._running

    def set_running(self, val: bool):
        """線程安全地設定巨集運行狀態"""
        with self.running_lock:
            self._running = bool(val)
            if self._running:
                self.stop_event.clear()
            elif not self._is_testing:
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
            if self._is_testing:
                self.stop_event.clear()
            elif not self._running:
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

    @property
    def reload_requested(self) -> bool:
        """保護熱重載旗標：僅在鎖可用時嘗試非阻塞讀取，避免在特定自訂鎖實作下因 acquire 缺失造成例外。"""
        try:
            acquire = getattr(self.steps_lock, "acquire", None)
            if callable(acquire):
                acquired = acquire(blocking=False)
                try:
                    return bool(self._reload_requested)
                finally:
                    if acquired:
                        self.steps_lock.release()
            return bool(self._reload_requested)
        except Exception:
            return bool(self._reload_requested)

    @reload_requested.setter
    def reload_requested(self, value: bool):
        """保護熱重載旗標：若 steps_lock 可用，優先要求在持有鎖的前提下寫入；否則退化成安全寫入。"""
        try:
            acquire = getattr(self.steps_lock, "acquire", None)
            if callable(acquire):
                try:
                    acquired = acquire(blocking=False)
                except Exception:
                    acquired = False
                try:
                    if acquired or getattr(self.steps_lock, "locked", lambda: False)():
                        self._reload_requested = bool(value)
                        return
                finally:
                    if acquired:
                        self.steps_lock.release()
        except Exception:
            pass
        self._reload_requested = bool(value)

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
        
        self.test_steps.clear()
        self.test_combos.clear()
        self.test_variables.clear()

    def reset(self):
        """完全重設狀態 (適用於單元測試環境隔離與全新載入)"""
        self.reset_drafts()
        self.reset_runtime()

    def snapshot_active(self, reload_requested: bool = False):
        """將當前編輯器草稿同步至背景執行快照 (執行緒安全)"""
        with self.steps_lock:
            self.active_steps = fast_deepcopy(self.steps)
            self.active_combos = fast_deepcopy(self.combos)
            self.active_variables = fast_deepcopy(self.variables)
            self.active_periodic_tasks = fast_deepcopy(self.periodic_tasks)
            self.reload_requested = reload_requested

    def to_dict(self) -> dict:
        """將編輯器草稿資料匯出為可序列化字典，並統一透過 dataclass 轉換層保留資料契約。"""
        return {
            "variables": {k: v.to_dict() if hasattr(v, "to_dict") else v for k, v in self.variables.items()},
            "combos": [c.to_dict() if hasattr(c, "to_dict") else c for c in self.combos],
            "steps": [s.to_dict() if hasattr(s, "to_dict") else s for s in self.steps],
            "periodic_tasks": [p.to_dict() if hasattr(p, "to_dict") else p for p in self.periodic_tasks],
        }

    def load_dict(self, data: dict):
        """從字典載入設定資料至編輯器草稿"""
        # load_dict 在 config_manager.py 中已經以 asdict/from_dict 獨立處理
        # 此處僅作為介面保留，實作由外部負責。
        pass

    def get_data_snapshot(self) -> str:
        """獲取當前編輯器資料的序列化字串，用於精確比對未儲存變更"""
        try:
            return json.dumps(self.to_dict(), sort_keys=True)
        except (TypeError, ValueError):
            return ""

    def has_unsaved_changes(self, last_saved_snapshot: str) -> bool:
        """檢查當前編輯器資料相較於最後儲存快照是否有變更"""
        if not last_saved_snapshot:
            return False
        return self.get_data_snapshot() != last_saved_snapshot


# ==============================================================================
# 全域狀態解耦：請透過 Dependency Injection 將 AppState 實例傳遞給需要的元件
# ==============================================================================


# ==============================================================================
# 文字格式化輔助函數
# ==============================================================================
def format_action_summary(app_state_or_act, act=None, index=None, current_variables=None):
    """統一格式化動作或步驟的文字描述。

    兼容兩種呼叫方式：
    - format_action_summary(app_state, act, ...)  # 舊簽名
    - format_action_summary(act, ...)              # 新簽名
    - format_action_summary(removed_item)          # dict/Action 直接傳入
    """
    if act is None:
        act = app_state_or_act
        app_state = None
    else:
        app_state = app_state_or_act

    if act is None:
        return "[空動作]"

    if isinstance(act, dict):
        action_dict = act
        atype = action_dict.get("type")
        var_name = action_dict.get("var_name")
        btn = action_dict.get("btn", "left")
        rel = action_dict.get("rel", True)
        x = action_dict.get("x", 0)
        y = action_dict.get("y", 0)
        key = action_dict.get("key", "")
        sec = action_dict.get("sec", 0)
        target_name = action_dict.get("target_name", "")
        name = action_dict.get("name", "")
        actions = action_dict.get("actions", [])
    else:
        action_dict = getattr(act, "__dict__", {})
        atype = getattr(act, "type", None)
        var_name = getattr(act, "var_name", None)
        btn = getattr(act, "btn", "left")
        rel = getattr(act, "rel", True)
        x = getattr(act, "x", 0)
        y = getattr(act, "y", 0)
        key = getattr(act, "key", "")
        sec = getattr(act, "sec", 0)
        target_name = getattr(act, "target_name", "")
        name = getattr(act, "name", "")
        actions = getattr(act, "actions", [])

    var_dict = current_variables
    if var_dict is None:
        var_dict = getattr(app_state, "variables", {}) if app_state is not None else {}

    if atype == "click":
        if var_name:
            v_info = var_dict.get(var_name) if hasattr(var_dict, "get") else None
            val = getattr(v_info, "value", None) if v_info is not None else None
            btn_key = val.get("btn", btn) if isinstance(val, dict) else btn
            btn_tag = "右鍵" if btn_key == "right" else "左鍵"
            cx = val.get("x", x) if isinstance(val, dict) else x
            cy = val.get("y", y) if isinstance(val, dict) else y
            body = f"[點擊·{btn_tag}] -> 變數:【{var_name}】({cx},{cy})"
        else:
            btn_tag = "右鍵" if btn == "right" else "左鍵"
            prefix = "相對:" if rel else "絕對:"
            body = f"[點擊·{btn_tag}] -> {prefix}({x},{y})"
    elif atype == "key":
        if var_name:
            v_info = var_dict.get(var_name) if hasattr(var_dict, "get") else None
            val = getattr(v_info, "value", None) if v_info is not None else key
            k_str = str(val).upper()
            body = f"[按鍵] -> 變數:【{var_name}】[ {k_str} ]"
        else:
            key_str = str(key).upper()
            body = f"[按鍵] -> [ {key_str} ]"
    elif atype == "wait":
        if var_name:
            v_info = var_dict.get(var_name) if hasattr(var_dict, "get") else None
            val = getattr(v_info, "value", None) if v_info is not None else sec
            body = f"[停頓] -> 變數:【{var_name}】{val} 秒"
        else:
            body = f"[停頓] -> {sec} 秒"
    elif atype == "call_combo":
        body = f"↻ [呼叫] -> 組合:【{target_name}】"
    elif atype == "combo":
        c_name = name if name else "組合"
        act_cnt = len(actions) if isinstance(actions, list) else 0
        body = f"◆ [組合: {c_name}] ({act_cnt}個動作)"
    else:
        body = f"[{atype}]"

    return body

def format_periodic_task_summary(task: PeriodicTask, current_variables=None, max_name_len=18):
    """格式化定時週期任務的顯示字串 (簡短俐落，支援長名稱智能縮略，避免溢出抖動)"""
    enabled = task.enabled
    st_icon = "[✓]" if enabled else "[✕]"
    
    t_mode = getattr(task, "trigger_mode", "interval")
    if t_mode == "round":
        r_val = task.round_interval
        trigger_str = f"每{r_val}輪"
    else:
        sec = task.interval
        try:
            f_sec = float(sec)
            trigger_str = f"{int(f_sec)}s" if f_sec.is_integer() else f"{f_sec}s"
        except (ValueError, TypeError):
            trigger_str = f"{sec}s"

    name = task.name.strip()
    start_str = " (首)" if getattr(task, "run_on_start", False) else ""

    if name:
        disp_name = name if len(name) <= max_name_len else name[:max_name_len - 1] + "…"
        return f"{st_icon} {trigger_str} · {disp_name}{start_str}"

    act = task.action
    if not act:
        return f"{st_icon} {trigger_str} · 空任務{start_str}"

    var_name = act.var_name
    atype = act.type

    if var_name:
        desc = f"變數:【{var_name}】"
    elif atype == "call_combo":
        desc = f"組合:【{act.target_name}】"
    elif atype == "key":
        desc = f"按鍵 [{str(act.key).upper()}]"
    elif atype == "click":
        btn_tag = "右鍵" if act.btn == "right" else "左鍵"
        desc = f"點擊·{btn_tag}"
    elif atype == "wait":
        desc = f"停頓 {act.sec}s"
    else:
        desc = f"[{atype}]"

    disp_desc = desc if len(desc) <= max_name_len else desc[:max_name_len - 1] + "…"
    return f"{st_icon} {trigger_str} · {disp_desc}{start_str}"


