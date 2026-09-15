import sys
import copy
import json
import dataclasses

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


class AppState:
    """全域巨集運作與資料狀態封裝類別
    
    將所有原本散落在模組級的全域變數（編輯器草稿、背景執行期快照、執行緒鎖、事件旗標）
    統一封裝於單一物件實例中，提供乾淨的狀態重設、單元測試隔離以及明確的屬性存取。
    """
    def __init__(self):
        # 1. 編輯器草稿資料 (Draft Data)
        self.combos: List[Combo] = []
        self.steps: List[Action] = []
        self.variables: Dict[str, Variable] = {}
        self.periodic_tasks: List[PeriodicTask] = []

        # 2. 背景運行實例快照 (Active Runtime Snapshots)
        self.active_steps: List[Action] = []
        self.active_combos: List[Combo] = []
        self.active_variables: Dict[str, Variable] = {}
        self.active_periodic_tasks: List[PeriodicTask] = []
        # 3. 試跑專屬唯讀快照 (Test Run Read-Only Snapshots)
        self.test_steps: List[Action] = []
        self.test_combos: List[Combo] = []
        self.test_variables: Dict[str, Variable] = {}

        # 4. 執行期旗標與執行緒同步物件 (Flags & Thread Synchronization)
        self.running_lock = threading.RLock()
        self._running = False
        self._is_testing = False
        self.reload_requested = False
        
        # 4. 運行環境設定 (Runtime Configuration)
        self.use_bg = True
        self.offset_x = 0
        self.offset_y = 0

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
        """將編輯器草稿資料匯出為字典"""
        return {
            "variables": fast_deepcopy(self.variables),
            "combos": fast_deepcopy(self.combos),
            "steps": fast_deepcopy(self.steps),
            "periodic_tasks": fast_deepcopy(self.periodic_tasks),
        }

    def load_dict(self, data: dict):
        """從字典載入設定資料至編輯器草稿"""
        # load_dict 在 config_manager.py 中已經以 asdict/from_dict 獨立處理
        # 此處僅作為介面保留，實作由外部負責。
        pass

    def get_data_snapshot(self) -> str:
        """獲取當前編輯器資料的序列化字串，用於精確比對未儲存變更"""
        from dataclasses import asdict
        try:
            return json.dumps({
                "variables": {k: asdict(v) for k, v in self.variables.items()},
                "combos": [asdict(c) for c in self.combos],
                "steps": [asdict(s) for s in self.steps],
                "periodic_tasks": [asdict(p) for p in self.periodic_tasks],
            }, sort_keys=True)
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
def format_action_summary(app_state: 'AppState', act: Action, index=None, current_variables=None):
    """統一格式化動作或步驟的文字描述，採用 100% 跨平台相容的通用標籤與符號"""
    var_dict = current_variables if current_variables is not None else app_state.variables
    atype = act.type

    var_name = act.var_name

    if atype == "click":
        if var_name:
            v_info = var_dict.get(var_name)
            val = v_info.value if v_info else None
            btn_key = val.get("btn", act.btn) if isinstance(val, dict) else act.btn
            btn_tag = "右鍵" if btn_key == "right" else "左鍵"
            cx = val.get("x", act.x) if isinstance(val, dict) else act.x
            cy = val.get("y", act.y) if isinstance(val, dict) else act.y
            body = f"[點擊·{btn_tag}] -> 變數:【{var_name}】({cx},{cy})"
        else:
            btn_tag = "右鍵" if act.btn == "right" else "左鍵"
            prefix = "相對:" if act.rel else "絕對:"
            body = f"[點擊·{btn_tag}] -> {prefix}({act.x},{act.y})"
    elif atype == "key":
        if var_name:
            v_info = var_dict.get(var_name)
            val = v_info.value if v_info else act.key
            k_str = str(val).upper()
            body = f"[按鍵] -> 變數:【{var_name}】[ {k_str} ]"
        else:
            key_str = str(act.key).upper()
            body = f"[按鍵] -> [ {key_str} ]"
    elif atype == "wait":
        if var_name:
            v_info = var_dict.get(var_name)
            val = v_info.value if v_info else act.sec
            body = f"[停頓] -> 變數:【{var_name}】{val} 秒"
        else:
            body = f"[停頓] -> {act.sec} 秒"
    elif atype == "call_combo":
        body = f"↻ [呼叫] -> 組合:【{act.target_name}】"
    elif atype == "combo":
        c_name = act.name if act.name else "組合"
        act_cnt = len(act.actions)
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


