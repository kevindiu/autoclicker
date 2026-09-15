import unittest

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


if __name__ == "__main__":
    unittest.main()
