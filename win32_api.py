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

# ==============================================================================
# Win32 訊息與系統旗標常數定義 (Windows Messages & System Constants)
# ==============================================================================
# 滑鼠訊息 (Mouse Messages)
WM_MOUSEMOVE     = 0x0200
WM_LBUTTONDOWN   = 0x0201
WM_LBUTTONUP     = 0x0202
WM_RBUTTONDOWN   = 0x0204
WM_RBUTTONUP     = 0x0205

# 鍵盤訊息 (Keyboard Messages)
WM_KEYDOWN       = 0x0100
WM_KEYUP         = 0x0101

# 滑鼠按鍵按壓狀態旗標 (Mouse Button wParam Flags)
MK_LBUTTON       = 0x0001
MK_RBUTTON       = 0x0002

# 鍵盤釋放轉換狀態遮罩 (Key Release LPARAM Masks)
KEY_RELEASE_LPARAM_MASK    = 0xC0000000  # bits 30 & 31: Previous key state & Transition state
KEY_RELEASE_DEFAULT_LPARAM = 0xC0000001  # Repeat count 1 + bits 30 & 31

# 虛擬按鍵碼 (Virtual Key Codes)
VK_BACK          = 0x08
VK_TAB           = 0x09
VK_RETURN        = 0x0D
VK_SHIFT         = 0x10
VK_CONTROL       = 0x11
VK_MENU          = 0x12  # Alt key
VK_CAPITAL       = 0x14  # Caps Lock
VK_ESCAPE        = 0x1B
VK_SPACE         = 0x20
VK_PRIOR         = 0x21  # Page Up
VK_NEXT          = 0x22  # Page Down
VK_END           = 0x23
VK_HOME          = 0x24
VK_LEFT          = 0x25
VK_UP            = 0x26
VK_RIGHT         = 0x27
VK_DOWN          = 0x28
VK_INSERT        = 0x2D
VK_DELETE        = 0x2E

# GetAsyncKeyState 狀態遮罩
KEY_PRESSED_MASK = 0x8000

# keybd_event 事件旗標
KEYEVENTF_KEYUP  = 0x0002

# ShowWindow 命令常數
SW_RESTORE       = 9

# SetWindowPos 旗標 (Window Sizing & Positioning Flags)
SWP_NOSIZE       = 0x0001
SWP_NOMOVE       = 0x0002
SWP_SHOWWINDOW   = 0x0040

HWND_TOPMOST     = ctypes.c_void_p(-1)
HWND_NOTOPMOST   = ctypes.c_void_p(-2)

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

if IS_WINDOWS:
    for fn in (lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2), lambda: ctypes.windll.user32.SetProcessDPIAware()):
        try: fn(); break
        except (AttributeError, OSError): pass

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
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    user32.MapVirtualKeyW.restype = wintypes.UINT
    user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
    user32.VkKeyScanW.restype = ctypes.c_short
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
else:
    user32 = None
    WNDENUMPROC = None

VK_MAP = {
    "space": VK_SPACE, "enter": VK_RETURN, "return": VK_RETURN, "esc": VK_ESCAPE, "escape": VK_ESCAPE,
    "tab": VK_TAB, "shift": VK_SHIFT, "ctrl": VK_CONTROL, "alt": VK_MENU,
    "backspace": VK_BACK, "delete": VK_DELETE, "del": VK_DELETE, "insert": VK_INSERT, "ins": VK_INSERT,
    "home": VK_HOME, "end": VK_END, "pageup": VK_PRIOR, "pgup": VK_PRIOR, "pagedown": VK_NEXT, "pgdn": VK_NEXT,
    "capslock": VK_CAPITAL,
    "up": VK_UP, "down": VK_DOWN, "left": VK_LEFT, "right": VK_RIGHT,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
    # OEM 標點符號鍵 (防止 ord() 誤轉為錯誤之系統功能鍵)
    "-": 0xBD, "_": 0xBD,
    "=": 0xBB, "+": 0xBB,
    "[": 0xDB, "{": 0xDB,
    "]": 0xDD, "}": 0xDD,
    ";": 0xBA, ":": 0xBA,
    "'": 0xDE, '"': 0xDE,
    ",": 0xBC, "<": 0xBC,
    ".": 0xBE, ">": 0xBE,
    "/": 0xBF, "?": 0xBF,
    "\\": 0xDC, "|": 0xDC,
    "`": 0xC0, "~": 0xC0,
    # 九宮格數字鍵盤 (Numpad)
    **{f"num{i}": 0x60 + i for i in range(10)},
    **{f"numpad{i}": 0x60 + i for i in range(10)},
    "num*": 0x6A, "num+": 0x6B, "num-": 0x6D, "num.": 0x6E, "num/": 0x6F,
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
        if not state.is_testing and not state.is_running():
            return False
        time.sleep(0.02)
    return True

def emergency_release_all():
    """全面釋放背景與前台的所有可能卡住的滑鼠與鍵盤狀態"""
    # 1. 釋放背景滑鼠
    if IS_WINDOWS and state.target_hwnd and user32:
        try:
            user32.PostMessageW(state.target_hwnd, WM_LBUTTONUP, 0, 0)
            user32.PostMessageW(state.target_hwnd, WM_RBUTTONUP, 0, 0)
        except (OSError, ctypes.ArgumentError):
            pass

    # 2. 釋放登記中的背景與前台按鍵
    with state.currently_held_keys_lock:
        for item in list(state.currently_held_keys):
            try:
                if item[0] == "bg" and IS_WINDOWS and user32:
                    _, h, vk = item
                    user32.PostMessageW(h, WM_KEYUP, vk, to_lparam(KEY_RELEASE_DEFAULT_LPARAM))
                elif item[0] == "fg":
                    _, k = item
                    pyautogui.keyUp(k)
            except (OSError, ctypes.ArgumentError, pyautogui.PyAutoGUIException, ValueError):
                pass
        state.currently_held_keys.clear()

    # 3. 前台滑鼠防禦性釋放
    try:
        pyautogui.mouseUp(button="left")
        pyautogui.mouseUp(button="right")
    except (pyautogui.PyAutoGUIException, OSError, ValueError):
        pass

def post_bg_click(hwnd, client_x, client_y, offset_x=0, offset_y=0, btn="left"):
    """向指定視窗背景發送點擊訊息"""
    if not IS_WINDOWS or not hwnd or not user32:
        pyautogui.click(client_x, client_y, button=btn)
        return int(client_x), int(client_y)
    cx, cy = int(client_x) + offset_x, int(client_y) + offset_y
    lparam = to_lparam(((int(cy) & 0xFFFF) << 16) | (int(cx) & 0xFFFF))

    down_msg = WM_RBUTTONDOWN if btn == "right" else WM_LBUTTONDOWN
    down_wparam = MK_RBUTTON if btn == "right" else MK_LBUTTON
    up_msg = WM_RBUTTONUP if btn == "right" else WM_LBUTTONUP

    # 連續立即發送 WM_MOUSEMOVE 與 WM_LBUTTONDOWN / WM_RBUTTONDOWN，絕不停頓，保證訊息原子性連續被遊戲處理，防止硬體滑鼠訊息插隊
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
    user32.PostMessageW(hwnd, down_msg, down_wparam, lparam)
    try:
        safe_sleep(0.04)
    finally:
        try:
            user32.PostMessageW(hwnd, up_msg, 0, lparam)
        except (OSError, ctypes.ArgumentError):
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
            except (pyautogui.PyAutoGUIException, OSError, ValueError): pass
            with state.currently_held_keys_lock:
                state.currently_held_keys.discard(("fg", key_str))
        return

    k_lower = key_str.lower()
    vk = VK_MAP.get(k_lower)
    if vk is None and len(key_str) == 1:
        if IS_WINDOWS and user32:
            try:
                res = user32.VkKeyScanW(key_str)
                if res != -1:
                    vk = res & 0xFF
            except (OSError, ctypes.ArgumentError):
                pass
        if vk is None and key_str.isalnum():
            vk = ord(key_str.upper())

    if vk is not None:
        scan_code = 0
        try:
            scan_code = user32.MapVirtualKeyW(vk, 0)
        except OSError:
            pass
        lparam_down = to_lparam(1 | (scan_code << 16))
        lparam_up = to_lparam(1 | (scan_code << 16) | KEY_RELEASE_LPARAM_MASK)
        with state.currently_held_keys_lock:
            state.currently_held_keys.add(("bg", hwnd, vk))
        try:
            user32.PostMessageW(hwnd, WM_KEYDOWN, vk, lparam_down)
            safe_sleep(0.06)
        finally:
            user32.PostMessageW(hwnd, WM_KEYUP, vk, lparam_up)
            with state.currently_held_keys_lock:
                state.currently_held_keys.discard(("bg", hwnd, vk))

def execute_click(x, y, is_rel, use_bg, off_x, off_y, btn="left", target_hwnd=None):
    """統一派發前台或背景點擊 (保證後台與前台模式均精準套用偏差校正)"""
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
        target_x = int(x) + off_x
        target_y = int(y) + off_y
        if is_rel and IS_WINDOWS and hwnd and user32:
            pt = POINT(target_x, target_y)
            user32.ClientToScreen(hwnd, ctypes.byref(pt))
            pyautogui.click(pt.x, pt.y, button=btn)
            return f"前台追蹤{btn_cn} ({pt.x},{pt.y})"
        pyautogui.click(target_x, target_y, button=btn)
        return f"前台{btn_cn} ({target_x},{target_y})"

def force_bring_window_to_front(hwnd):
    """強制喚醒並將目標視窗置頂最前"""
    if not IS_WINDOWS or not hwnd or not user32:
        return
    try:
        if user32.GetForegroundWindow() == hwnd:
            return  # 目標已在前台，不重複執行置頂與敲擊 Alt 鍵
        user32.ShowWindow(hwnd, SW_RESTORE)
        swp_flags = SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, swp_flags)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, swp_flags)

        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
    except (OSError, AttributeError):
        pass

def is_window_alive(hwnd):
    """檢查指定視窗句柄是否仍然存活且有效 (防禦目標視窗關閉或異常崩潰)"""
    if not IS_WINDOWS or not user32 or not hwnd:
        return True
    try:
        return bool(user32.IsWindow(hwnd))
    except (OSError, AttributeError):
        return True
