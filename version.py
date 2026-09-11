import os
import sys
import subprocess

# 預設備用版本號 (當無法讀取 git 亦非打包環境時的終極回退)
__version__ = ""
BASE_WINDOW_TITLE = "水滸歷險 巨集助手"

def resource_path(relative_path):
    """獲取資源絕對路徑 (相容 PyInstaller 單一執行檔打包與原始碼執行)"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    base_dir = os.path.abspath(os.path.dirname(__file__)) if '__file__' in globals() else os.path.abspath(".")
    return os.path.join(base_dir, relative_path)

def get_app_version():
    """動態獲取應用程式版本號（100% 全自動，免手動維護任何版本檔）：
    1. 【打包發佈環境 (.exe / .app)】：由 GitHub Actions 在 CI 打包時自動注入當次 Tag 至臨時 VERSION 檔並封裝進 exe。
    2. 【本地開發環境 (源碼執行)】：自動直接透過 git 讀取當前 repo 最新 Tag，打 tag 即時生效！
    3. 【離線或無 git 環境】：回退至 __version__ 靜態版號。
    """
    # 1. 打包環境：檢查 PyInstaller 運行時解壓目錄 (sys._MEIPASS)
    if hasattr(sys, '_MEIPASS'):
        try:
            ver_file = os.path.join(sys._MEIPASS, "VERSION")
            if os.path.exists(ver_file):
                with open(ver_file, "r", encoding="utf-8") as f:
                    v = f.read().strip()
                    if v:
                        return v
        except Exception:
            pass

    # 2. 本地開發環境：自動直接讀取當前 git 最新 tag (例如 v7.1)
    try:
        out = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        if out:
            return out
    except Exception:
        pass

    try:
        out = subprocess.check_output(
            ["git", "describe", "--tags", "--always"],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        if out:
            return out
    except Exception:
        pass

    # 3. 備用回退
    return __version__

def get_window_title():
    """產生包含版本號的應用程式完整視窗標題"""
    ver = get_app_version()
    return f"{BASE_WINDOW_TITLE} {ver}" if ver else BASE_WINDOW_TITLE
