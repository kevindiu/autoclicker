import os
import tempfile
import threading
import unittest
import time
from types import SimpleNamespace
from unittest.mock import patch

import config_manager
import engine
import win32_api
from controllers import PeriodicTaskController, VarController
from models import CallComboAction, Combo, PeriodicTask, Variable, WaitAction
import state


class FunctionalityRegressionTests(unittest.TestCase):
    def test_hot_reload_completes_without_lock_deadlock(self):
        app_state = state.AppState()
        app_state.steps = []
        app_state.combos = []
        app_state.variables = {}
        app_state.periodic_tasks = []
        app_state.snapshot_active(reload_requested=True)
        app_state.set_running(True)
        runtime = engine.RuntimeManager(app_state)
        worker = threading.Thread(target=runtime.reload_if_needed, daemon=True)

        worker.start()
        worker.join(timeout=0.5)

        self.assertFalse(worker.is_alive())
        self.assertTrue(runtime.reload_if_needed() is False)

    def test_coordinate_variable_builds_click_action(self):
        app = SimpleNamespace(
            app_state=SimpleNamespace(
                variables={
                    "target": Variable(
                        type="coord",
                        value={"x": 10, "y": 20, "btn": "right", "rel": True},
                    )
                }
            ),
            var_use_rel=SimpleNamespace(get=lambda: True),
        )

        action, description = VarController(app)._build_variable_action("target")

        self.assertEqual(action["type"], "click")
        self.assertEqual(action["x"], 10)
        self.assertEqual(action["y"], 20)
        self.assertEqual(action["btn"], "right")
        self.assertIn("target", description)

    def test_malformed_coordinate_profile_is_normalized(self):
        app_state = state.AppState()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, f"broken{config_manager.CONFIG_EXT}")
            with open(path, "w", encoding="utf-8") as profile:
                profile.write(
                    '{"variables": {"target": {"type": "coord", "value": {"x": "bad", "y": null}}}, '
                    '"steps": [{"type": "click", "x": "bad", "y": null}], '
                    '"combos": [], "periodic_tasks": []}'
                )

            config_manager.load_profile_file("broken", app_state, dir_path=tmpdir)

        self.assertEqual(app_state.variables["target"].value["x"], 0)
        self.assertEqual(app_state.variables["target"].value["y"], 0)
        self.assertEqual(app_state.steps[0].x, 0)
        self.assertEqual(app_state.steps[0].y, 0)

    def test_periodic_task_without_action_is_not_started_for_test(self):
        calls = []
        statuses = []
        app_state = state.AppState()
        app_state.periodic_tasks = [PeriodicTask(id="empty", name="Empty", action=None)]
        app = SimpleNamespace(
            app_state=app_state,
            periodic_listbox=SimpleNamespace(curselection=lambda: (0,)),
            set_status=statuses.append,
            run_in_test_thread=lambda *args: calls.append(args),
        )

        PeriodicTaskController(app).test_run_selected_periodic_task()

        self.assertEqual(calls, [])

    def test_unsupported_background_key_is_rejected(self):
        app_state = state.AppState()
        fake_user32 = SimpleNamespace()

        with patch.object(win32_api, "user32", fake_user32), patch.object(
            win32_api, "is_windows_supported", return_value=True
        ):
            with self.assertRaises(ValueError):
                win32_api.post_bg_key(app_state, 123, "not-a-key")

    def test_profile_round_trip_preserves_nested_data(self):
        source = state.AppState()
        source.variables["delay"] = Variable(type="wait", value=0.25)
        source.combos.append(Combo(name="heal", actions=[WaitAction(sec=0.1)]))
        source.steps.append(WaitAction(sec=0.5, var_name="delay"))
        source.periodic_tasks.append(
            PeriodicTask(id="pt1", name="tick", interval=2.0, action=WaitAction(sec=0.1))
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config_manager.save_profile_file("roundtrip", source, dir_path=tmpdir)
            loaded = state.AppState()
            config_manager.load_profile_file("roundtrip", loaded, dir_path=tmpdir)

        self.assertEqual(loaded.variables["delay"].value, 0.25)
        self.assertEqual(loaded.combos[0].actions[0].sec, 0.1)
        self.assertEqual(loaded.steps[0].var_name, "delay")
        self.assertEqual(loaded.periodic_tasks[0].action.type, "wait")

    def test_due_periodic_wait_task_updates_runtime_timestamp(self):
        app_state = state.AppState()
        app_state.set_running(True)
        task = PeriodicTask(id="pt1", name="tick", interval=1.0, action=WaitAction(sec=0.0))
        task.last_run = time.time() - 2.0

        try:
            result = engine.check_and_run_due_periodic_tasks(
                app_state,
                [task],
                current_vars={},
                current_combos=[],
            )
        finally:
            app_state.set_running(False)

        self.assertTrue(result)
        self.assertGreater(task.last_run, time.time() - 1.0)

    def test_recursive_combo_call_is_guarded(self):
        app_state = state.AppState()
        app_state.set_testing(True)
        app_state.test_combos = [Combo(name="loop", actions=[CallComboAction(target_name="loop")])]

        try:
            result = engine.dispatch_action(
                app_state,
                CallComboAction(target_name="loop"),
                "test",
                current_vars={},
                current_combos=app_state.test_combos,
                is_test=True,
            )
        finally:
            app_state.set_testing(False)

        self.assertTrue(result)

    def test_safe_sleep_honors_stop_event(self):
        app_state = state.AppState()
        app_state.stop_event.set()

        self.assertFalse(win32_api.safe_sleep(app_state, 0.01))

    def test_profile_service_uses_config_directory_for_existing_profile(self):
        import profile_service

        app = SimpleNamespace(
            app_state=state.AppState(),
            var_profile_name=SimpleNamespace(get=lambda: "default"),
            set_status=lambda message: None,
            append_log=lambda *args: None,
            refresh_profiles=lambda **kwargs: None,
        )
        service = profile_service.ProfileService(app)

        with patch.object(profile_service.config_manager, "_DEFAULT_DIR", "/profiles"), patch(
            "profile_service.os.path.exists", side_effect=lambda path: path == "/profiles/default.shm"
        ), patch.object(profile_service.messagebox, "askyesno", return_value=False), patch.object(
            profile_service.config_manager, "save_profile_file"
        ) as save:
            service.save_config()

        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
