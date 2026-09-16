import os
import tempfile
import threading
import unittest
from unittest.mock import patch

import config_manager
import engine
import models
import state
from events import EventBus, AppEvents


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

    def test_set_running_clears_testing_mode_and_set_testing_clears_running_mode(self):
        app_state = state.AppState()

        app_state.set_testing(True)
        self.assertTrue(app_state.is_in_testing())

        app_state.set_running(True)
        self.assertTrue(app_state.is_running())
        self.assertFalse(app_state.is_in_testing())

        app_state.set_running(False)
        app_state.set_testing(True)
        self.assertTrue(app_state.is_in_testing())
        self.assertFalse(app_state.is_running())

    def test_runtime_mode_transition_uses_single_state_source_of_truth(self):
        app_state = state.AppState()

        app_state.set_running(True)
        self.assertTrue(app_state.is_running())
        self.assertFalse(app_state.is_in_testing())
        self.assertFalse(app_state.stop_event.is_set())

        app_state.set_testing(True)
        self.assertFalse(app_state.is_running())
        self.assertTrue(app_state.is_in_testing())
        self.assertFalse(app_state.stop_event.is_set())

        app_state.set_running(False)
        app_state.set_testing(False)
        self.assertFalse(app_state.is_running())
        self.assertFalse(app_state.is_in_testing())
        self.assertTrue(app_state.stop_event.is_set())

    def test_start_reload_and_stop_sequence_remains_consistent(self):
        app_state = state.AppState()

        app_state.set_running(True)
        app_state.request_reload()
        self.assertTrue(app_state.is_running())
        self.assertTrue(app_state.reload_requested)

        app_state.reload_requested = False
        self.assertFalse(app_state.reload_requested)

        app_state.set_running(False)
        self.assertFalse(app_state.is_running())
        self.assertTrue(app_state.stop_event.is_set())

        app_state.set_testing(True)
        self.assertTrue(app_state.is_in_testing())
        self.assertFalse(app_state.is_running())

    def test_snapshot_active_does_not_deadlock_when_updating_reload_flag(self):
        app_state = state.AppState()
        done = {}

        def worker():
            try:
                app_state.snapshot_active(reload_requested=True)
                done["ok"] = True
            except Exception as exc:  # pragma: no cover - assertion path for debugging
                done["err"] = exc

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=1)

        self.assertTrue(done.get("ok"), "snapshot_active should not deadlock while updating reload_requested")
        self.assertTrue(app_state.reload_requested)

    def test_stop_macro_run_is_idempotent(self):
        app_state = state.AppState()
        calls = []

        def listener():
            calls.append("stop")

        EventBus.subscribe(AppEvents.MACRO_STOPPED, listener)
        try:
            engine.stop_macro_run(app_state, "manual")
            engine.stop_macro_run(app_state, "manual")
            self.assertEqual(len(calls), 1)
        finally:
            EventBus.unsubscribe(AppEvents.MACRO_STOPPED, listener)

    def test_stop_emits_log_before_macro_stopped_event(self):
        app_state = state.AppState()
        calls = []

        def fake_emit(event_type, *args, **kwargs):
            calls.append((event_type, args, kwargs.get("scope", "default")))

        with patch.object(engine, "emergency_release_all"), patch.object(engine.EventBus, "emit", side_effect=fake_emit):
            engine.stop_macro_run(app_state, "manual")

        self.assertEqual(calls[0][0], AppEvents.LOG_MESSAGE)
        self.assertEqual(calls[1][0], AppEvents.MACRO_STOPPED)

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

    def test_validate_profile_data_normalizes_nested_invalid_data(self):
        invalid = {
            "variables": {"hp": {"type": "wait", "value": "bad"}},
            "combos": [{"name": "combo", "actions": [{"type": "click", "x": "bad", "y": 1, "btn": "left", "rel": True}]}],
            "steps": [{"type": "key", "key": 123}],
            "periodic_tasks": [{"id": "pt1", "name": "heal", "interval": "bad", "action": {"type": "wait", "sec": "not-a-number"}}],
        }

        valid = config_manager.validate_profile_data(invalid)

        self.assertEqual(valid["variables"]["hp"]["type"], "wait")
        self.assertEqual(valid["combos"][0]["name"], "combo")
        self.assertEqual(valid["steps"][0]["type"], "key")
        self.assertEqual(valid["periodic_tasks"][0]["interval"], 1.0)

    def test_event_bus_scopes_subscriptions_per_app(self):
        events = __import__("events")
        calls = []

        def cb_a(*args, **kwargs):
            calls.append(("a", args, kwargs))

        def cb_b(*args, **kwargs):
            calls.append(("b", args, kwargs))

        events.EventBus.subscribe("demo", cb_a, scope="app_a")
        events.EventBus.subscribe("demo", cb_b, scope="app_b")

        events.EventBus.emit("demo", "payload", scope="app_a")

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "a")
        self.assertEqual(calls[0][1], ("payload",))

    def test_hot_reload_flag_only_changes_under_steps_lock(self):
        app_state = _HotReloadState()

        with app_state.steps_lock:
            app_state.reload_requested = True
            self.assertTrue(app_state.reload_requested)

        with app_state.steps_lock:
            app_state.reload_requested = False
            self.assertFalse(app_state.reload_requested)

    def test_reload_requested_guard_handles_custom_lock_without_acquire(self):
        class _NoAcquireLock:
            def __init__(self):
                self.depth = 0

            def __enter__(self):
                self.depth += 1
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                self.depth -= 1
                return False

        app_state = state.AppState()
        app_state.steps_lock = _NoAcquireLock()

        with app_state.steps_lock:
            app_state.reload_requested = True
            self.assertTrue(app_state.reload_requested)

        with app_state.steps_lock:
            app_state.reload_requested = False
            self.assertFalse(app_state.reload_requested)

    def test_validate_profile_data_normalizes_invalid_trigger_mode(self):
        invalid = {
            "periodic_tasks": [{
                "id": "pt1",
                "name": "heal",
                "trigger_mode": "bogus",
                "interval": "bad",
                "action": {"type": "wait", "sec": "1.5"},
            }],
        }

        valid = config_manager.validate_profile_data(invalid)

        self.assertEqual(valid["periodic_tasks"][0]["trigger_mode"], "interval")
        self.assertEqual(valid["periodic_tasks"][0]["interval"], 1.0)

    def test_coordinate_bool_strings_are_normalized_from_profile_input(self):
        coord = models.Variable.from_dict({
            "type": "coord",
            "value": {"x": 10, "y": 20, "btn": "right", "rel": "false"},
        })

        self.assertFalse(coord.value["rel"])
        self.assertEqual(coord.value["btn"], "right")

    def test_frozen_runtime_keeps_safe_int_helper_available(self):
        import importlib
        import sys

        original_frozen = getattr(sys, "frozen", False)
        try:
            sys.frozen = True
            importlib.reload(config_manager)
            self.assertTrue(callable(config_manager._safe_int))
            self.assertEqual(config_manager._safe_int("42", 0), 42)
        finally:
            sys.frozen = original_frozen
            importlib.reload(config_manager)


if __name__ == "__main__":
    unittest.main()
