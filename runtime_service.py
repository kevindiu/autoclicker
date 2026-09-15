import threading
import time

import engine
from events import EventBus, AppEvents


class RuntimeService:
    """將 App 的 runtime lifecycle 從 UI 類別中抽離，讓 App 只保留 UI 與事件協調責任。"""

    def __init__(self, app):
        self.app = app

    def _stop_macro_run_ui(self, was_test=False):
        app_state = self.app.app_state
        app_state.stop_event.set()
        try:
            engine.stop_macro_run(app_state, reason="手動停止")
        except Exception as e:
            self.app.append_log("系統", f"釋放按鍵例外: {e}")
        self.app.set_running_ui(False)
        msg = "試跑已手動中止！" if was_test else "已手動停止"
        self.app.set_status(msg)
        self.app.append_log("系統", f"⏹ 巨集{msg}")

    def _start_macro_run_ui(self):
        app_state = self.app.app_state
        has_enabled_periodic = any(getattr(pt, "enabled", True) for pt in app_state.periodic_tasks)
        if not app_state.steps and not has_enabled_periodic:
            return self.app.set_status("掛機流程清單與定時任務均為空，請先加入步驟或定時任務！")

        app_state.snapshot_active(reload_requested=False)
        engine.start_macro_run(app_state)
        self.app.set_running_ui(True)
        self.app.set_status("循環運作中...")
        win_title = self.app.var_window.get() if hasattr(self.app, "var_window") else ""
        mode_str = "後台模式" if app_state.use_bg else "前台模式"
        self.app.append_log("系統", f"▶ 巨集啟動 ({mode_str} | 目標: {win_title})")
        threading.Thread(target=self.app.macro_worker_loop, daemon=True).start()

    def toggle_run(self):
        app = self.app
        now = time.time()
        if hasattr(app, "_last_toggle_time") and now - app._last_toggle_time < 0.5:
            return
        app._last_toggle_time = now

        with app.app_state.running_lock:
            is_active = app.app_state.is_running() or app.app_state.is_testing
            was_test = app.app_state.is_testing
            if is_active:
                app.app_state.set_running(False)
                app.app_state.is_testing = False

        if is_active:
            self._stop_macro_run_ui(was_test)
        else:
            self._start_macro_run_ui()

    def macro_worker_loop(self):
        engine.macro_worker_loop(self.app.app_state)
