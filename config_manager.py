import os
import sys
import json
import time
import copy
import uuid
import state
from models import Variable, Action, Combo, PeriodicTask
from theme import CONFIG_EXT

# ==============================================================================
# 設定檔管理 (Config Manager)
# 負責 .shm 設定檔之檔案列表讀取、資料序列化儲存、載入與 Schema 向後相容補齊
# ==============================================================================

# 確保設定檔存放在與執行檔 (.exe) 或主腳本同一目錄下 (相容 PyInstaller 打包與源碼執行)
if getattr(sys, "frozen", False):
    _DEFAULT_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _DEFAULT_DIR = os.path.dirname(os.path.abspath(__file__))

def sanitize_profile_name(name: str) -> str:
    """過濾 Windows 與常見作業系統之非法檔名字元"""
    s = name.strip()
    for ch in r'<>:"/\|?*':
        s = s.replace(ch, "")
    return s.strip()

def get_profile_files(ext=CONFIG_EXT, dir_path=_DEFAULT_DIR) -> list:
    """獲取指定目錄下所有設定檔名稱列表 (已去除副檔名並排序)"""
    try:
        return sorted([f[:-len(ext)] for f in os.listdir(dir_path) if f.endswith(ext)])
    except OSError:
        return []

def ensure_default_profile(ext=CONFIG_EXT, dir_path=_DEFAULT_DIR):
    """若無任何設定檔則建立預設 default 設定檔 (原子寫入)"""
    fn = os.path.join(dir_path, f"default{ext}")
    if not os.path.exists(fn):
        temp_fn = os.path.join(dir_path, f"default{ext}.tmp")
        try:
            with open(temp_fn, "w", encoding="utf-8") as f:
                json.dump({"variables": {}, "combos": [], "steps": [], "periodic_tasks": []}, f, ensure_ascii=False, indent=2)
            os.replace(temp_fn, fn)
        except OSError:
            if os.path.exists(temp_fn):
                try:
                    os.remove(temp_fn)
                except OSError:
                    pass

def _resolve_target_state(target_state=None, **kwargs):
    """解析並返回正確的 AppState 實例，強制要求傳入有效實例以貫徹依賴注入"""
    if target_state is None and "app_state" in kwargs:
        target_state = kwargs["app_state"]
    if target_state is None:
        raise ValueError("必須明確提供目標的 AppState 實例！")
    if hasattr(target_state, "app_state"):
        return target_state.app_state
    return target_state

def save_profile_file(name: str, target_state=None, ext=CONFIG_EXT, dir_path=_DEFAULT_DIR, **kwargs) -> str:
    """將狀態資料儲存為 .shm 設定檔 (採用暫存檔 + 原子替換保護，防止寫入中斷損毀)"""
    target_state = _resolve_target_state(target_state, **kwargs)
    safe_name = sanitize_profile_name(name)
    if not safe_name:
        raise ValueError("無效的設定檔名稱！")
    fn = os.path.join(dir_path, f"{safe_name}{ext}")
    temp_fn = os.path.join(dir_path, f"{safe_name}{ext}.tmp")

    if hasattr(target_state, "to_dict"):
        data = target_state.to_dict()
    else:
        from dataclasses import asdict
        data = {
            "variables": {k: asdict(v) for k, v in target_state.variables.items()},
            "combos": [asdict(c) for c in target_state.combos],
            "steps": [asdict(s) for s in target_state.steps],
            "periodic_tasks": [asdict(p) for p in target_state.periodic_tasks]
        }

    if any(hasattr(v, "__dict__") and not isinstance(v, (dict, list, tuple, str, int, float, bool, type(None))) for v in [data]):
        from dataclasses import asdict
        data = asdict(target_state) if hasattr(target_state, "__dataclass_fields__") else data

    try:
        with open(temp_fn, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_fn, fn)
    except Exception:
        if os.path.exists(temp_fn):
            try:
                os.remove(temp_fn)
            except OSError:
                pass
        raise

    return fn

def validate_profile_data(data: dict) -> dict:
    """驗證設定檔資料型別並做向後相容修正，避免舊資料或手動編輯下的型別錯誤造成後續資料損毀。"""
    if not isinstance(data, dict):
        return {
            "variables": {},
            "combos": [],
            "steps": [],
            "periodic_tasks": [],
        }

    variables = data.get("variables") if isinstance(data.get("variables"), dict) else {}
    combos = data.get("combos") if isinstance(data.get("combos"), list) else []
    steps = data.get("steps") if isinstance(data.get("steps"), list) else []
    periodic_tasks = data.get("periodic_tasks") if isinstance(data.get("periodic_tasks"), list) else []

    normalized = {
        "variables": {},
        "combos": [],
        "steps": [],
        "periodic_tasks": [],
    }

    for name, item in variables.items():
        if not isinstance(item, dict):
            continue
        v_type = item.get("type", "coord")
        if v_type == "coord":
            value = item.get("value")
            if not isinstance(value, dict):
                value = {"x": 0, "y": 0, "btn": "left", "rel": True}
            normalized["variables"][name] = {
                "type": "coord",
                "value": {
                    "x": int(value.get("x", 0)),
                    "y": int(value.get("y", 0)),
                    "btn": str(value.get("btn", "left")),
                    "rel": bool(value.get("rel", True)),
                },
            }
        elif v_type == "key":
            normalized["variables"][name] = {"type": "key", "value": str(item.get("value", ""))}
        elif v_type == "wait":
            try:
                wait_val = float(item.get("value", 1.0))
            except (TypeError, ValueError):
                wait_val = 1.0
            normalized["variables"][name] = {"type": "wait", "value": wait_val}
        else:
            normalized["variables"][name] = {"type": "coord", "value": {"x": 0, "y": 0, "btn": "left", "rel": True}}

    for combo in combos:
        if not isinstance(combo, dict):
            continue
        normalized["combos"].append({
            "name": str(combo.get("name", "")),
            "actions": [
                action for action in (combo.get("actions") or [])
                if isinstance(action, dict)
            ],
        })

    for step in steps:
        if isinstance(step, dict):
            normalized["steps"].append(step)

    for task in periodic_tasks:
        if not isinstance(task, dict):
            continue
        normalized_task = dict(task)
        if not normalized_task.get("id"):
            normalized_task["id"] = f"pt_{int(time.time()*1000)}_{len(normalized['periodic_tasks'])}"
        if not normalized_task.get("name"):
            normalized_task["name"] = f"定時任務_{len(normalized['periodic_tasks']) + 1}"
        try:
            normalized_task["interval"] = float(normalized_task.get("interval", 1.0))
        except (TypeError, ValueError):
            normalized_task["interval"] = 1.0
        normalized_task["round_interval"] = int(normalized_task.get("round_interval", 1)) if isinstance(normalized_task.get("round_interval"), int) else 1
        normalized_task["enabled"] = bool(normalized_task.get("enabled", True))
        normalized_task["run_on_start"] = bool(normalized_task.get("run_on_start", False))
        if "action" in normalized_task and not isinstance(normalized_task["action"], dict):
            normalized_task["action"] = None
        normalized["periodic_tasks"].append(normalized_task)

    return normalized


def load_profile_file(name: str, target_state=None, ext=CONFIG_EXT, dir_path=_DEFAULT_DIR, **kwargs) -> dict:
    """從 .shm 設定檔載入設定資料，並自動補齊缺失之欄位與 ID (具備 null 值防禦)"""
    target_state = _resolve_target_state(target_state, **kwargs)
    safe_name = sanitize_profile_name(name)
    fn = os.path.join(dir_path, f"{safe_name}{ext}")
    if not os.path.exists(fn):
        raise FileNotFoundError(f"找不到檔案：{fn}")

    with open(fn, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"設定檔格式錯誤 (非 JSON 物件)：{fn}")

    data = validate_profile_data(data)

    target_state.variables.clear()
    target_state.variables.update({k: Variable.from_dict(v) for k, v in (data.get("variables") or {}).items()})

    target_state.combos.clear()
    target_state.combos.extend([Combo.from_dict(c) for c in (data.get("combos") or []) if isinstance(c, dict)])

    target_state.steps.clear()
    target_state.steps.extend([Action.from_dict(s) for s in (data.get("steps") or []) if isinstance(s, dict)])

    target_state.periodic_tasks.clear()
    periodic_tasks_raw = data.get("periodic_tasks") or []
    for p_idx, pt in enumerate(periodic_tasks_raw):
        if not isinstance(pt, dict):
            continue
        pt = dict(pt)
        if not pt.get("id"):
            pt["id"] = f"pt_{int(time.time()*1000)}_{p_idx}_{uuid.uuid4().hex[:6]}"
        if not pt.get("name"):
            pt["name"] = f"定時任務_{p_idx + 1}"
        if not isinstance(pt.get("interval", 1.0), (int, float)):
            pt["interval"] = 1.0
        if not isinstance(pt.get("round_interval", 1), int):
            pt["round_interval"] = 1
        target_state.periodic_tasks.append(PeriodicTask.from_dict(pt))

    return data
