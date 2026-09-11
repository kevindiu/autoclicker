import os
import sys
from version import get_window_title, BASE_WINDOW_TITLE, get_app_version, resource_path

WINDOW_TITLE = get_window_title()
CONFIG_EXT = ".shm"

# ==============================================================================
# UI 色彩與樣式主題配置 (保持原有配色一致性)
# ==============================================================================
class UITheme:
    BG_DARK = "#15171c"          # 主背景底色 / 列表底色
    BG_PANEL = "#1c1f26"         # 卡片、側欄、對話框背景
    BG_INPUT = "#2d333b"         # 輸入框底色
    BORDER = "#2d333b"           # 面板邊框
    
    TEXT_MAIN = "#f1f5f9"        # 主文字 (白色系)
    TEXT_MUTED = "#94a3b8"       # 次要/輔助文字 (灰色)
    TEXT_LABEL = "#cbd5e1"       # 標籤文字 (淡灰)
    
    ACCENT_GREEN = "#16a34a"     # 翠綠 (啟動、新增、瞄準點擊)
    ACCENT_GREEN_HOVER = "#15803d"
    
    ACCENT_BLUE = "#2563eb"      # 海軍藍 (載入、儲存、選取、修改)
    ACCENT_BLUE_HOVER = "#1d4ed8"
    
    ACCENT_INDIGO = "#4f46e5"    # 紫青 (試跑、定位視窗)
    ACCENT_INDIGO_HOVER = "#4338ca"
    
    ACCENT_RED = "#dc2626"       # 深紅 (停止、刪除)
    ACCENT_RED_HOVER = "#b91c1c"
    ACCENT_RED_DARK = "#991b1b"  # 暗紅 (清空)
    ACCENT_RED_DARK_HOVER = "#7f1d1d"
    
    BTN_GRAY = "#334155"         # 鐵灰 (輔助按鍵、上移下移、停頓)
    BTN_GRAY_HOVER = "#475569"
    
    CYAN_TITLE = "#38bdf8"       # 天藍標題
    CYAN_SUB = "#7dd3fc"         # 淺天藍副標
    ACCENT_CYAN = "#0284c7"      # 青藍 (展開)
    ACCENT_CYAN_HOVER = "#0369a1"

    # ================= 統一清晰字體系統 (微軟正黑體 UI) =================
    FONT_FAMILY = "Microsoft JhengHei UI" if sys.platform == "win32" else ("PingFang TC" if sys.platform == "darwin" else "Noto Sans CJK TC")
    
    FONT_SMALL = (FONT_FAMILY, 9)
    FONT_SMALL_BOLD = (FONT_FAMILY, 9, "bold")
    FONT_NORMAL = (FONT_FAMILY, 10)
    FONT_NORMAL_BOLD = (FONT_FAMILY, 10, "bold")
    FONT_TITLE = (FONT_FAMILY, 11, "bold")
    FONT_BIG_BTN = (FONT_FAMILY, 12, "bold")
