import os
import json
import time
import uuid
import state
from theme import CONFIG_EXT

# ==============================================================================
# 設定檔管理 (Config Manager)
# 負責 .shm 設定檔之檔案列表讀取、資料序列化儲存、載入與 Schema 向後相容補齊
# ==============================================================================

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
            pass

def save_profile_file(name: str, app_state=None, ext=CONFIG_EXT, dir_path=_DEFAULT_DIR) -> str:
    """將狀態資料儲存為 .shm 設定檔 (採用暫存檔 + 原子替換保護，防止寫入中斷損毀)"""
    target_state = app_state if app_state is not None else state
    safe_name = sanitize_profile_name(name)
    if not safe_name:
        raise ValueError("無效的設定檔名稱！")
    fn = os.path.join(dir_path, f"{safe_name}{ext}")
    temp_fn = os.path.join(dir_path, f"{safe_name}{ext}.tmp")
    data = {
        "variables": target_state.variables,
        "combos": target_state.combos,
        "steps": target_state.steps,
        "periodic_tasks": target_state.periodic_tasks
    }
    with open(temp_fn, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp_fn, fn)
    return fn

def load_profile_file(name: str, app_state=None, ext=CONFIG_EXT, dir_path=_DEFAULT_DIR) -> dict:
    """從 .shm 設定檔載入設定資料，並自動補齊缺失之欄位與 ID (具備 null 值防禦)"""
    target_state = app_state if app_state is not None else state
    safe_name = sanitize_profile_name(name)
    fn = os.path.join(dir_path, f"{safe_name}{ext}")
    if not os.path.exists(fn):
        raise FileNotFoundError(f"找不到檔案：{fn}")

    with open(fn, "r", encoding="utf-8") as f:
        data = json.load(f)

    target_state.variables.clear()
    target_state.variables.update(data.get("variables") or {})

    target_state.combos.clear()
    target_state.combos.extend(data.get("combos") or [])

    target_state.steps.clear()
    target_state.steps.extend(data.get("steps") or [])

    target_state.periodic_tasks.clear()
    for p_idx, pt in enumerate(data.get("periodic_tasks") or []):
        if not pt.get("id"):
            pt["id"] = f"pt_{int(time.time()*1000)}_{p_idx}_{uuid.uuid4().hex[:6]}"
        target_state.periodic_tasks.append(pt)

    return data

def get_data_snapshot(app_state=None) -> str:
    """獲取當前設定資料的序列化字串 (唯一實現委派至 AppState.get_data_snapshot，避免重複與分歧)"""
    target = app_state if app_state is not None else state.get_state()
    if hasattr(target, "get_data_snapshot"):
        return target.get_data_snapshot()
    return state.get_state().get_data_snapshot()

def has_unsaved_changes(last_saved_snapshot: str, app_state=None) -> bool:
    """檢查當前記憶體中的設定相較於最後儲存狀態是否有更新 (委派至 AppState 唯一實現)"""
    target = app_state if app_state is not None else state.get_state()
    if hasattr(target, "has_unsaved_changes"):
        return target.has_unsaved_changes(last_saved_snapshot)
    if not last_saved_snapshot:
        return False
    return get_data_snapshot(target) != last_saved_snapshot
