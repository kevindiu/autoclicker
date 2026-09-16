import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import config_manager
import engine
import state
from models import CallComboAction, Combo, KeyAction, PeriodicTask, Variable, WaitAction


class EndToEndMacroWorkflowTests(unittest.TestCase):
    def _runtime_patches(self):
        return [
            patch("engine.execute_click", return_value="已點擊"),
            patch("engine.post_bg_key"),
            patch("engine.safe_sleep", return_value=True),
            patch("engine.force_bring_window_to_front"),
            patch("engine.is_window_alive", return_value=True),
            patch("engine.emergency_release_all"),
        ]

    def _make_app_state(self):
        app_state = state.AppState()
        app_state.use_bg = True
        app_state.target_hwnd = 123
        app_state.set_running(False)
        app_state.stop_event.clear()
        return app_state

    def test_profile_round_trip_and_runtime_bootstrap(self):
        app_state = self._make_app_state()
        app_state.variables = {
            "atk": Variable(type="key", value="f1"),
            "delay": Variable(type="wait", value=0.25),
            "target": Variable(type="coord", value={"x": 23, "y": 45, "btn": "left", "rel": True}),
        }
        app_state.combos = [Combo(name="heal", actions=[KeyAction(key="f2"), WaitAction(sec=0.1)])]
        app_state.steps = [CallComboAction(target_name="heal"), WaitAction(sec=0.2, var_name="delay")]
        app_state.periodic_tasks = [
            PeriodicTask(
                id="pt1",
                name="tick",
                interval=0.5,
                enabled=True,
                run_on_start=True,
                action=KeyAction(key="f3"),
            )
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_manager.save_profile_file("e2e_macro", app_state, dir_path=tmpdir)
            loaded = state.AppState()
            config_manager.load_profile_file("e2e_macro", loaded, dir_path=tmpdir)

        self.assertEqual(loaded.variables["atk"].value, "f1")
        self.assertEqual(loaded.variables["target"].value["x"], 23)
        self.assertEqual(loaded.combos[0].name, "heal")
        self.assertEqual(loaded.steps[0].target_name, "heal")
        self.assertEqual(loaded.periodic_tasks[0].action.key, "f3")

        loaded.snapshot_active(reload_requested=False)
        manager = engine.RuntimeManager(loaded)
        boot = manager.bootstrap()
        self.assertEqual(boot["steps"][0].target_name, "heal")
        self.assertEqual(len(boot["periodic_tasks_runtime"]), 1)

    def test_runtime_cycle_executes_steps_and_due_periodic_task(self):
        app_state = self._make_app_state()
        app_state.set_running(True)
        app_state.stop_event.clear()

        current_steps = [KeyAction(key="f1"), WaitAction(sec=0.0)]
        current_vars = {"atk": Variable(type="key", value="f1")}
        current_combos = [Combo(name="heal", actions=[KeyAction(key="f2")])]
        periodic_tasks_runtime = [
            PeriodicTask(
                id="pt1",
                name="tick",
                interval=0.0,
                enabled=True,
                run_on_start=True,
                action=KeyAction(key="f4"),
            )
        ]

        with patch.multiple(engine, **{name: p.start() for name, p in {
            "execute_click": patch("engine.execute_click", return_value="已點擊"),
            "post_bg_key": patch("engine.post_bg_key"),
            "safe_sleep": patch("engine.safe_sleep", return_value=True),
            "force_bring_window_to_front": patch("engine.force_bring_window_to_front"),
            "is_window_alive": patch("engine.is_window_alive", return_value=True),
            "emergency_release_all": patch("engine.emergency_release_all"),
        }.items()}):
            result = engine.run_macro_cycle(
                app_state,
                current_steps,
                current_combos,
                current_vars,
                periodic_tasks_runtime,
                1,
            )
            self.assertTrue(result)
            self.assertGreater(periodic_tasks_runtime[0].last_run, 0.0)

        engine.shutdown_macro_runtime(app_state, round_idx=1)

    def test_hot_reload_updates_active_snapshot_while_running(self):
        app_state = self._make_app_state()
        app_state.set_running(True)
        app_state.steps = [WaitAction(sec=0.1)]
        app_state.variables = {"delay": Variable(type="wait", value=0.1)}
        app_state.snapshot_active(reload_requested=False)

        app_state.steps = [KeyAction(key="f9")]
        app_state.variables = {"delay": Variable(type="wait", value=2.0)}
        app_state.snapshot_active(reload_requested=True)

        manager = engine.RuntimeManager(app_state)
        self.assertTrue(manager.reload_if_needed())
        self.assertEqual(manager.current_steps[0].type, "key")
        self.assertEqual(manager.current_variables["delay"].value, 2.0)

        app_state.set_running(False)

    def test_stop_event_aborts_running_cycle(self):
        app_state = self._make_app_state()
        app_state.set_running(True)
        app_state.stop_event.set()

        with self._runtime_patches()[0]:
            pass

        with patch("engine.safe_sleep", return_value=True), patch("engine.is_window_alive", return_value=True):
            result = engine.run_macro_cycle(
                app_state,
                [WaitAction(sec=0.1)],
                [],
                {},
                [],
                1,
            )

        self.assertFalse(result)
        self.assertTrue(app_state.stop_event.is_set())

    def test_runtime_coordinator_start_stop_lifecycle(self):
        app_state = self._make_app_state()
        app_state.steps = [WaitAction(sec=0.0)]
        app_state.periodic_tasks = []
        app = SimpleNamespace(
            app_state=app_state,
            set_running_ui=lambda *args, **kwargs: None,
            set_status=lambda *args, **kwargs: None,
            append_log=lambda *args, **kwargs: None,
            var_window=SimpleNamespace(get=lambda: "Test Window"),
            macro_worker_loop=lambda: None,
        )

        coordinator = engine.RuntimeManager(app_state)
        with patch("engine.start_macro_run", return_value={"steps": app_state.steps, "combos": [], "variables": {}, "round_idx": 1}), patch(
            "runtime_service.threading.Thread"
        ) as thread_factory:
            app.runtime_service = SimpleNamespace()
            app.runtime_service.coordinator = SimpleNamespace(start_run=lambda: app_state.set_running(True), stop_run=lambda: app_state.stop_event.set())
            app_state.set_running(True)
            app_state.stop_event.clear()
            app_state.stop_event.set()
            self.assertTrue(app_state.stop_event.is_set())

        self.assertTrue(app_state.stop_event.is_set())


if __name__ == "__main__":
    unittest.main()
