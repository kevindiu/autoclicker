import sys
import tkinter as tk
from tkinter import ttk
from version import get_window_title, BASE_WINDOW_TITLE, resource_path

WINDOW_TITLE = get_window_title()
CONFIG_EXT = ".shm"

# ==============================================================================
# 日誌 Tag 標準常數 (消除魔法字串與字串啟發式匹配)
# ==============================================================================
class LogTag:
    ALERT = "警示"
    INFO = "系統"
    TEST = "試跑"

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

    TEXT_WHITE = "#ffffff"       # 純白文字 (按鈕前景、高亮字樣)
    SELECT_BG = "#1e3a5f"        # 深藍選取底色 (卡片、表格選中)
    SELECT_BORDER = "#38bdf8"    # 天藍選取邊框

    # ================= 定時週期任務卡片 (Periodic Task Card) 專屬色碼 =================
    CARD_BG_ENABLED = "#1e222b"        # 啟用卡片底色
    CARD_BG_DISABLED = "#17191f"       # 停用卡片底色
    CARD_BORDER_ENABLED = "#2d3544"    # 啟用卡片邊框
    CARD_BORDER_DISABLED = "#23262d"   # 停用卡片邊框
    CARD_HOVER_BG = "#232834"          # 卡片懸停底色
    CARD_HOVER_BORDER = "#3a4454"      # 卡片懸停邊框
    CARD_ACTIVE_BG = "#064e3b"         # 祖母綠深底 (定時任務觸發運行中)
    CARD_ACTIVE_BORDER = "#34d399"     # 亮翠綠邊框 (定時任務觸發運行中)

    # ================= 徽章與狀態標籤 (Badges) 色碼 =================
    BADGE_PURPLE_BG = "#3b0764"        # 輪次觸發徽章底色 (深紫)
    BADGE_PURPLE_FG = "#c084fc"        # 輪次觸發徽章文字 (紫羅蘭)
    BADGE_PURPLE_ACTIVE_BG = "#6b21a8" # 輪次觸發中徽章底色
    BADGE_CYAN_BG = "#0c4a6e"          # 秒數間隔徽章底色 (深天藍)
    BADGE_CYAN_FG = "#38bdf8"          # 秒數間隔徽章文字 (天藍)
    BADGE_CYAN_ACTIVE_BG = "#0284c7"   # 秒數間隔即將觸發徽章底色
    BADGE_GREEN_BG = "#14532d"         # 執行中徽章底色 (深翠綠)
    BADGE_GREEN_FG = "#4ade80"         # 執行中徽章文字 (嫩綠)
    BADGE_IDLE_BG = "#1e293b"          # 待命/未運行徽章底色 (石板暗灰)
    BADGE_IDLE_FG = "#64748b"          # 待命/未運行徽章文字
    BADGE_DISABLED_BG = "#334155"      # 停用狀態徽章底色
    BADGE_DISABLED_FG = "#94a3b8"      # 停用狀態徽章文字
    BADGE_AMBER_BG = "#78350f"         # 首發徽章底色 (深琥珀)
    BADGE_AMBER_FG = "#fbbf24"         # 首發徽章文字 (暖黃)
    BADGE_MUTED_FG = "#475569"         # 停用副文字 (暗灰)

    # ================= 深色滾動條配置 (Dark Scrollbar) =================
    SCROLLBAR_THUMB = "#334155"         # 滑塊底色 (深石板灰)
    SCROLLBAR_THUMB_HOVER = "#475569"   # 滑塊懸停色 (稍亮石板灰)
    SCROLLBAR_THUMB_ACTIVE = "#64748b"  # 滑塊按下/拖曳色
    SCROLLBAR_TROUGH = "#15171c"        # 軌道底色 (與主深色背景一致，完美融入)
    SCROLLBAR_ARROW = "#94a3b8"         # 箭頭符號色
    SCROLLBAR_BORDER = "#15171c"        # 滾動條邊框
    SCROLLBAR_WIDTH = 12                # 滾動條寬度 (精緻窄邊排版)

    # ================= 統一清晰字體系統 (微軟正黑體 UI) =================
    FONT_FAMILY = "Microsoft JhengHei UI" if sys.platform == "win32" else ("PingFang TC" if sys.platform == "darwin" else "Noto Sans CJK TC")
    
    FONT_SMALL = (FONT_FAMILY, 8)
    FONT_SMALL_BOLD = (FONT_FAMILY, 8, "bold")
    FONT_NORMAL = (FONT_FAMILY, 9)
    FONT_NORMAL_BOLD = (FONT_FAMILY, 9, "bold")
    FONT_TITLE = (FONT_FAMILY, 10, "bold")
    FONT_BIG_BTN = (FONT_FAMILY, 12, "bold")

def setup_dark_theme(root=None):
    """配置全域 ttk 深色樣式（深色滾動條、深色下拉選單等），徹底消除 Windows 原生刺眼白色滾動條"""
    try:
        style = ttk.Style(root)
        available = style.theme_names()
        if "clam" in available:
            style.theme_use("clam")

        # 深色垂直滾動條樣式 (Dark.Vertical.TScrollbar)
        style.configure(
            "Dark.Vertical.TScrollbar",
            gripcount=0,
            background=UITheme.SCROLLBAR_THUMB,
            darkcolor=UITheme.SCROLLBAR_TROUGH,
            lightcolor=UITheme.SCROLLBAR_TROUGH,
            troughcolor=UITheme.SCROLLBAR_TROUGH,
            bordercolor=UITheme.SCROLLBAR_BORDER,
            arrowcolor=UITheme.SCROLLBAR_ARROW,
            arrowsize=11,
            width=UITheme.SCROLLBAR_WIDTH
        )
        style.map(
            "Dark.Vertical.TScrollbar",
            background=[("active", UITheme.SCROLLBAR_THUMB_HOVER), ("pressed", UITheme.SCROLLBAR_THUMB_ACTIVE)],
            arrowcolor=[("active", UITheme.TEXT_MAIN), ("pressed", UITheme.CYAN_TITLE)]
        )

        # 深色水平滾動條樣式 (Dark.Horizontal.TScrollbar)
        style.configure(
            "Dark.Horizontal.TScrollbar",
            gripcount=0,
            background=UITheme.SCROLLBAR_THUMB,
            darkcolor=UITheme.SCROLLBAR_TROUGH,
            lightcolor=UITheme.SCROLLBAR_TROUGH,
            troughcolor=UITheme.SCROLLBAR_TROUGH,
            bordercolor=UITheme.SCROLLBAR_BORDER,
            arrowcolor=UITheme.SCROLLBAR_ARROW,
            arrowsize=11,
            width=UITheme.SCROLLBAR_WIDTH
        )
        style.map(
            "Dark.Horizontal.TScrollbar",
            background=[("active", UITheme.SCROLLBAR_THUMB_HOVER), ("pressed", UITheme.SCROLLBAR_THUMB_ACTIVE)],
            arrowcolor=[("active", UITheme.TEXT_MAIN), ("pressed", UITheme.CYAN_TITLE)]
        )

        # 深色 Combobox 樣式 (微調避免原生白色突兀)
        style.configure(
            "TCombobox",
            font=UITheme.FONT_NORMAL,
            fieldbackground=UITheme.BG_INPUT,
            background=UITheme.BG_INPUT,
            foreground=UITheme.TEXT_MAIN,
            arrowcolor=UITheme.CYAN_TITLE,
            bordercolor=UITheme.BORDER,
            darkcolor=UITheme.BORDER,
            lightcolor=UITheme.BORDER
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", UITheme.BG_INPUT)],
            selectbackground=[("readonly", UITheme.BG_INPUT)],
            selectforeground=[("readonly", UITheme.TEXT_MAIN)],
            background=[("readonly", UITheme.BG_INPUT), ("active", UITheme.BTN_GRAY)]
        )
    except tk.TclError:
        pass
