import sys
import time
import ctypes
from ctypes import wintypes
import pyautogui

import state

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

# ==============================================================================
# Win32 底層 API 封裝與溢位防護
# ==============================================================================
IS_WINDOWS = hasattr(ctypes, "windll")

def to_lparam(val):
    """安全轉換整數為 C 語言 signed LPARAM 範圍，防止 32-bit / 64-bit ctypes 溢位"""
    val = int(val) & 0xFFFFFFFF
    return val if val < 0x80000000 else val - 0x100000000

HWND_TOPMOST = ctypes.c_void_p(-1)
HWND_NOTOPMOST = ctypes.c_void_p(-2)

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

if IS_WINDOWS:
    for fn in (lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2), lambda: ctypes.windll.user32.SetProcessDPIAware()):
        try: fn(); break
        except Exception: pass

    user32 = ctypes.windll.user32
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
    user32.ScreenToClient.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.FlashWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
    user32.FlashWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    user32.MapVirtualKeyW.restype = wintypes.UINT
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
else:
    user32 = None
    WNDENUMPROC = None

VK_MAP = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "tab": 0x09, "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
}

# ==============================================================================
# 動作執行與安全輔助函數
# ==============================================================================
def safe_sleep(seconds):
    """具備中止感知的安全等待"""
    end = time.time() + float(seconds)
    while time.time() < end:
        if state.stop_event.is_set():
            return False
        if not state.is_testing and not state.running:
            return False
        time.sleep(0.02)
    return True

def emergency_release_all():
    """全面釋放背景與前台的所有可能卡住的滑鼠與鍵盤狀態"""
    # 1. 釋放背景滑鼠
    if IS_WINDOWS and state.target_hwnd and user32:
        try:
            user32.PostMessageW(state.target_hwnd, 0x0202, 0, 0)
            user32.PostMessageW(state.target_hwnd, 0x0205, 0, 0)
        except Exception:
            pass

    # 2. 釋放登記中的背景與前台按鍵
    with state.currently_held_keys_lock:
        for item in list(state.currently_held_keys):
            try:
                if item[0] == "bg" and IS_WINDOWS and user32:
                    _, h, vk = item
                    user32.PostMessageW(h, 0x0101, vk, to_lparam(0xC0000001))
                elif item[0] == "fg":
                    _, k = item
                    pyautogui.keyUp(k)
            except Exception:
                pass
        state.currently_held_keys.clear()

    # 3. 前台滑鼠防禦性釋放
    try:
        pyautogui.mouseUp(button="left")
        pyautogui.mouseUp(button="right")
    except Exception:
        pass

def post_bg_click(hwnd, client_x, client_y, offset_x=0, offset_y=0, btn="left"):
    """向指定視窗背景發送點擊訊息"""
    if not IS_WINDOWS or not hwnd or not user32:
        pyautogui.click(client_x, client_y, button=btn)
        return int(client_x), int(client_y)
    cx, cy = int(client_x) + offset_x, int(client_y) + offset_y
    lparam = to_lparam(((int(cy) & 0xFFFF) << 16) | (int(cx) & 0xFFFF))

    down_msg = 0x0204 if btn == "right" else 0x0201
    down_wparam = 0x0002 if btn == "right" else 0x0001
    up_msg = 0x0205 if btn == "right" else 0x0202

    # 連續立即發送 WM_MOUSEMOVE 與 WM_LBUTTONDOWN，絕不停頓，保證訊息原子性連續被遊戲處理，防止硬體滑鼠訊息插隊
    user32.PostMessageW(hwnd, 0x0200, 0, lparam)
    user32.PostMessageW(hwnd, down_msg, down_wparam, lparam)
    if safe_sleep(0.04):
        try:
            user32.PostMessageW(hwnd, up_msg, 0, lparam)
        except Exception:
            pass
    return cx, cy

def post_bg_key(hwnd, key_str):
    """向指定視窗背景發送按鍵按下與放開訊息"""
    if not IS_WINDOWS or not hwnd or not user32:
        with state.currently_held_keys_lock:
            state.currently_held_keys.add(("fg", key_str))
        try:
            pyautogui.keyDown(key_str)
            safe_sleep(0.06)
        finally:
            try: pyautogui.keyUp(key_str)
            except Exception: pass
            with state.currently_held_keys_lock:
                state.currently_held_keys.discard(("fg", key_str))
        return
    vk = VK_MAP.get(key_str.lower()) or (ord(key_str.upper()) if len(key_str) == 1 else None)
    if vk is not None:
        scan_code = 0
        try:
            scan_code = user32.MapVirtualKeyW(vk, 0)
        except Exception:
            pass
        lparam_down = to_lparam(1 | (scan_code << 16))
        lparam_up = to_lparam(1 | (scan_code << 16) | 0xC0000000)
        with state.currently_held_keys_lock:
            state.currently_held_keys.add(("bg", hwnd, vk))
        try:
            user32.PostMessageW(hwnd, 0x0100, vk, lparam_down)
            safe_sleep(0.06)
        finally:
            user32.PostMessageW(hwnd, 0x0101, vk, lparam_up)
            with state.currently_held_keys_lock:
                state.currently_held_keys.discard(("bg", hwnd, vk))

def execute_click(x, y, is_rel, use_bg, off_x, off_y, btn="left", target_hwnd=None):
    """統一派發前台或背景點擊"""
    hwnd = target_hwnd if target_hwnd is not None else state.target_hwnd
    btn_cn = "右鍵" if btn == "right" else "左鍵"
    if use_bg:
        if not is_rel and IS_WINDOWS and hwnd and user32:
            pt = POINT(int(x), int(y))
            user32.ScreenToClient(hwnd, ctypes.byref(pt))
            x, y = pt.x, pt.y
        cx, cy = post_bg_click(hwnd, x, y, off_x, off_y, btn=btn)
        return f"後台{btn_cn}相對:({cx},{cy})"
    else:
        if is_rel and IS_WINDOWS and hwnd and user32:
            pt = POINT(int(x), int(y))
            user32.ClientToScreen(hwnd, ctypes.byref(pt))
            pyautogui.click(pt.x, pt.y, button=btn)
            return f"前台追蹤{btn_cn} ({pt.x},{pt.y})"
        pyautogui.click(x, y, button=btn)
        return f"前台{btn_cn} ({x},{y})"

def force_bring_window_to_front(hwnd):
    """強制喚醒並將目標視窗置頂最前"""
    if not IS_WINDOWS or not hwnd or not user32:
        return
    try:
        if user32.GetForegroundWindow() == hwnd:
            return  # 目標已在前台，不重複執行置頂與敲擊 Alt 鍵
        user32.ShowWindow(hwnd, 9)
        SWP_FLAGS = 0x0001 | 0x0002 | 0x0040
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_FLAGS)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_FLAGS)

        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)

        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
    except Exception:
        pass
