import os
import tempfile
import unittest

import config_manager
import state


class _TrackingLock:
    def __init__(self):
        self.depth = 0

    def __enter__(self):
        self.depth += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self.depth -= 1
        return False


class _HotReloadState(state.AppState):
    def __init__(self):
        super().__init__()
        self._reload_requested = False
        self.steps_lock = _TrackingLock()

    @property
    def reload_requested(self):
        return self._reload_requested

    @reload_requested.setter
    def reload_requested(self, value):
        if self.steps_lock.depth == 0:
            raise RuntimeError("reload_requested must only be mutated while holding steps_lock")
        self._reload_requested = bool(value)


class StateAndConfigRegressionTests(unittest.TestCase):
    def test_set_running_clears_stop_event_when_starting(self):
        app_state = state.AppState()
        app_state.stop_event.set()

        app_state.set_running(True)

        self.assertTrue(app_state.is_running())
        self.assertFalse(app_state.stop_event.is_set())

        app_state.set_running(False)
        self.assertFalse(app_state.is_running())
        self.assertTrue(app_state.stop_event.is_set())

    def test_load_profile_file_handles_invalid_periodic_tasks(self):
        app_state = state.AppState()
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, f"profile{config_manager.CONFIG_EXT}")
            with open(file_path, "w", encoding="utf-8") as fh:
                fh.write(
                    '{"variables": {"hp": {"type": "wait", "value": 1.0}}, '
                    '"combos": [], "steps": [], "periodic_tasks": [null, {"name": "heal"}]}'
                )

            loaded = config_manager.load_profile_file("profile", app_state, dir_path=tmpdir)

            self.assertIn("periodic_tasks", loaded)
            self.assertEqual(len(app_state.periodic_tasks), 1)
            self.assertEqual(app_state.periodic_tasks[0].name, "heal")
            self.assertTrue(app_state.periodic_tasks[0].id)

    def test_hot_reload_flag_only_changes_under_steps_lock(self):
        app_state = _HotReloadState()

        with app_state.steps_lock:
            app_state.reload_requested = True
            self.assertTrue(app_state.reload_requested)

        with app_state.steps_lock:
            app_state.reload_requested = False
            self.assertFalse(app_state.reload_requested)


if __name__ == "__main__":
    unittest.main()
