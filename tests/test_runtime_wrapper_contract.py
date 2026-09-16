import threading
import time
import unittest
import sys
from types import SimpleNamespace

from autoclicker import App
import engine
from models import PeriodicTask, WaitAction
import state


class RuntimeWrapperContractTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "GUI runtime contract requires Windows")
    def test_app_dispatch_action_passes_app_state(self):
        app = App()
        try:
            call = app.dispatch_action
            self.assertTrue(call is not None)
        finally:
            app.destroy()

    @unittest.skipUnless(sys.platform == "win32", "GUI runtime contract requires Windows")
    def test_app_macro_worker_loop_uses_app_state(self):
        app = App()
        try:
            self.assertTrue(hasattr(app, "macro_worker_loop"))
        finally:
            app.destroy()

    def test_runtime_orchestration_helpers_are_exposed(self):
        self.assertTrue(hasattr(engine, "RuntimeManager"))
        self.assertTrue(hasattr(engine, "start_macro_run"))
        self.assertTrue(hasattr(engine, "stop_macro_run"))
        self.assertTrue(hasattr(engine, "prepare_runtime_state"))
        self.assertTrue(hasattr(engine, "run_macro_cycle"))
        self.assertTrue(hasattr(engine, "bootstrap_macro_runtime"))
        self.assertTrue(hasattr(engine, "shutdown_macro_runtime"))

    def test_app_hot_reload_delegates_to_service(self):
        app = object.__new__(App)
        calls = []
        app.hot_reload_service = SimpleNamespace(trigger_hot_reload=lambda: calls.append("hot_reload_service"))
        app.step_ctrl = SimpleNamespace(trigger_hot_reload=lambda: calls.append("step_ctrl"))

        app.trigger_hot_reload()

        self.assertEqual(calls, ["hot_reload_service"])

    def test_app_ui_feedback_delegates_to_service(self):
        app = object.__new__(App)
        calls = []
        app.ui_feedback_service = SimpleNamespace(
            clear_active_step_highlight=lambda: calls.append("clear_step"),
            highlight_active_step=lambda idx, sub_idx=None: calls.append(("active_step", idx, sub_idx)),
            highlight_pending_step=lambda idx: calls.append(("pending_step", idx)),
            highlight_active_periodic_task=lambda idx: calls.append(("active_periodic", idx)),
            clear_active_periodic_task_highlight=lambda: calls.append("clear_periodic"),
        )

        app.clear_active_step_highlight()
        app.highlight_active_step(2, sub_idx=1)
        app.highlight_pending_step(3)
        app.highlight_active_periodic_task(4)
        app.clear_active_periodic_task_highlight()

        self.assertEqual(
            calls,
            ["clear_step", ("active_step", 2, 1), ("pending_step", 3), ("active_periodic", 4), "clear_periodic"],
        )

    def test_runtime_manager_handles_periodic_task_objects(self):
        app_state = state.AppState()
        app_state.active_periodic_tasks = [
            PeriodicTask(id="pt1", name="tick", interval=0.01, enabled=True, action=WaitAction(sec=0.0), run_on_start=True)
        ]
        runtime = engine.RuntimeManager(app_state)

        boot = runtime.bootstrap()

        self.assertIsInstance(boot["periodic_tasks_runtime"], list)
        self.assertEqual(len(boot["periodic_tasks_runtime"]), 1)
        self.assertEqual(boot["periodic_tasks_runtime"][0].name, "tick")


if __name__ == "__main__":
    unittest.main()
