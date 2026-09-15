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

    target_state.variables.clear()
    target_state.variables.update({k: Variable.from_dict(v) for k, v in (data.get("variables") or {}).items()})

    target_state.combos.clear()
    target_state.combos.extend([Combo.from_dict(c) for c in (data.get("combos") or [])])

    target_state.steps.clear()
    target_state.steps.extend([Action.from_dict(s) for s in (data.get("steps") or []) if s])

    target_state.periodic_tasks.clear()
    for p_idx, pt in enumerate(data.get("periodic_tasks") or []):
        if not pt.get("id"):
            pt["id"] = f"pt_{int(time.time()*1000)}_{p_idx}_{uuid.uuid4().hex[:6]}"
        target_state.periodic_tasks.append(PeriodicTask.from_dict(pt))

    return data
