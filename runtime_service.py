import threading
import time

import engine
import state
from events import EventBus, AppEvents
from win32_api import emergency_release_all


class MacroRuntimeCoordinator:
    """集中處理巨集 runtime 生命周期，讓 UI 層只負責事件通知與狀態展示。"""

    def __init__(self, app):
        self.app = app

    def stop_run(self, was_test=False):
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

    def run_in_test_thread(self, task_name, task_fn):
        """啟動受保護的試跑執行緒，集中管理試跑快照與清理。"""
        app_state = self.app.app_state
        ok, reason = app_state.try_start_testing()
        if not ok:
            if reason == "running":
                return self.app.set_status("巨集正在循環執行中，請先停止再試跑！")
            return self.app.set_status("已有試跑任務正在執行中，請稍候！")

        app_state.stop_event.clear()
        self.app.set_running_ui(True, is_test=True)
        app_state.test_steps = state.fast_deepcopy(app_state.steps)
        app_state.test_combos = state.fast_deepcopy(app_state.combos)
        app_state.test_variables = state.fast_deepcopy(app_state.variables)

        def _worker():
            try:
                self.app.append_log("試跑", f"▶ 正在試跑: {task_name}")
                task_fn()
                if app_state.stop_event.is_set():
                    self.app.append_log("試跑", f"⏹ {task_name} 試跑已手動中止！")
                else:
                    self.app.append_log("試跑", f"✓ {task_name} 試跑完成！")
            except Exception as e:
                self.app.append_log("警示", f"✕ {task_name} 試跑異常: {e}")
            finally:
                app_state.test_steps.clear()
                app_state.test_combos.clear()
                app_state.test_variables.clear()
                app_state.is_testing = False
                emergency_release_all(app_state)
                self.app.set_running_ui(False)

        threading.Thread(target=_worker, daemon=True).start()

    def start_run(self):
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
            self.stop_run(was_test)
        else:
            self.start_run()

    def macro_worker_loop(self):
        engine.macro_worker_loop(self.app.app_state)


class RuntimeService:
    """保留兼容 API，將實際 lifecycle 邏輯交由 MacroRuntimeCoordinator 執行。"""

    def __init__(self, app):
        self.app = app
        self.coordinator = MacroRuntimeCoordinator(app)

    def _stop_macro_run_ui(self, was_test=False):
        return self.coordinator.stop_run(was_test)

    def _start_macro_run_ui(self):
        return self.coordinator.start_run()

    def toggle_run(self):
        return self.coordinator.toggle_run()

    def run_in_test_thread(self, task_name, task_fn):
        return self.coordinator.run_in_test_thread(task_name, task_fn)

    def macro_worker_loop(self):
        return self.coordinator.macro_worker_loop()
