import unittest
from unittest import mock

import engine
from models import PeriodicTask
import state


class HotReloadPeriodicGuardTests(unittest.TestCase):
    def test_periodic_task_without_action_is_skipped_gracefully(self):
        app_state = state.AppState()
        app_state.set_running(True)
        app_state.stop_event.clear()
        task = PeriodicTask(id="pt_empty", name="empty", interval=0.1, enabled=True, action=None)
        try:
            result = engine.check_and_run_due_periodic_tasks(
                app_state,
                [task],
                current_vars={},
                current_combos=[],
                current_round=1,
                is_round_end=False,
                is_startup=False,
            )
            self.assertTrue(result)
        finally:
            app_state.set_running(False)

    def test_pending_reload_aborts_due_periodic_task_dispatch(self):
        app_state = state.AppState()
        app_state.set_running(True)
        app_state.stop_event.clear()
        app_state.reload_requested = True
        task = PeriodicTask(
            id="pt_reload_guard",
            name="reload_guard",
            interval=0.0,
            enabled=True,
            run_on_start=True,
            action=engine.KeyAction(key="f1"),
        )
        try:
            with mock.patch('engine.dispatch_action', return_value=True):
                result = engine.check_and_run_due_periodic_tasks(
                    app_state,
                    [task],
                    current_vars={},
                    current_combos=[],
                    current_round=1,
                    is_round_end=False,
                    is_startup=False,
                )
            self.assertFalse(result)
        finally:
            app_state.set_running(False)


if __name__ == "__main__":
    unittest.main()
