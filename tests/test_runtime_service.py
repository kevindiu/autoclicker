import unittest
from types import SimpleNamespace
from unittest.mock import patch

import state
from models import Combo, Variable, WaitAction
from runtime_service import MacroRuntimeCoordinator, RuntimeService


class _ImmediateThread:
    created = []

    def __init__(self, target, daemon=False):
        self.target = target
        self.daemon = daemon
        self.created.append(self)

    def start(self):
        self.target()


class RuntimeServiceTests(unittest.TestCase):
    def setUp(self):
        _ImmediateThread.created = []
        self.app_state = state.AppState()
        self.app_state.steps = [WaitAction(sec=0.25)]
        self.app_state.combos = [Combo(name="heal", actions=[])]
        self.app_state.variables = {"delay": Variable(type="wait", value=0.5)}
        self.logs = []
        self.ui_states = []
        self.statuses = []
        self.app = SimpleNamespace(
            app_state=self.app_state,
            append_log=lambda *args: self.logs.append(args),
            set_running_ui=lambda *args, **kwargs: self.ui_states.append((args, kwargs)),
            set_status=lambda message: self.statuses.append(message),
        )

    def test_test_run_copies_snapshots_and_cleans_up_after_success(self):
        task_observations = []
        coordinator = MacroRuntimeCoordinator(self.app)

        def task():
            task_observations.append((
                self.app_state.test_steps[0].sec,
                self.app_state.test_combos[0].name,
                self.app_state.test_variables["delay"].value,
            ))
            self.app_state.test_steps[0].sec = 9.0

        with patch("runtime_service.threading.Thread", _ImmediateThread), patch(
            "runtime_service.emergency_release_all"
        ) as release:
            coordinator.run_in_test_thread("延遲測試", task)

        self.assertEqual(task_observations, [(0.25, "heal", 0.5)])
        self.assertEqual(self.app_state.test_steps, [])
        self.assertEqual(self.app_state.test_combos, [])
        self.assertEqual(self.app_state.test_variables, {})
        self.assertFalse(self.app_state.is_in_testing())
        self.assertEqual(self.ui_states, [((True,), {"is_test": True}), ((False,), {})])
        release.assert_called_once_with(self.app_state)
        self.assertIn(("試跑", "✓ 延遲測試 試跑完成！"), self.logs)

    def test_test_run_cleans_up_and_logs_when_task_fails(self):
        coordinator = MacroRuntimeCoordinator(self.app)

        def task():
            raise ValueError("bad task")

        with patch("runtime_service.threading.Thread", _ImmediateThread), patch(
            "runtime_service.emergency_release_all"
        ) as release:
            coordinator.run_in_test_thread("失敗測試", task)

        self.assertFalse(self.app_state.is_in_testing())
        self.assertEqual(self.app_state.test_steps, [])
        self.assertEqual(self.app_state.test_combos, [])
        self.assertEqual(self.app_state.test_variables, {})
        release.assert_called_once_with(self.app_state)
        self.assertIn(("警示", "✕ 失敗測試 試跑異常: bad task"), self.logs)
        self.assertEqual(self.ui_states[-1], ((False,), {}))

    def test_test_run_rejects_running_or_existing_test(self):
        coordinator = MacroRuntimeCoordinator(self.app)
        task = lambda: self.fail("rejected task must not run")

        self.app_state.set_running(True)
        with patch("runtime_service.threading.Thread", _ImmediateThread):
            coordinator.run_in_test_thread("運行中", task)
        self.assertEqual(self.statuses, ["巨集正在循環執行中，請先停止再試跑！"])
        self.assertEqual(_ImmediateThread.created, [])

        self.app_state.set_running(False)
        self.app_state.is_testing = True
        with patch("runtime_service.threading.Thread", _ImmediateThread):
            coordinator.run_in_test_thread("試跑中", task)
        self.assertEqual(self.statuses[-1], "已有試跑任務正在執行中，請稍候！")
        self.assertEqual(_ImmediateThread.created, [])

    def test_runtime_service_keeps_test_run_compatibility_wrapper(self):
        service = RuntimeService(self.app)
        service.coordinator = SimpleNamespace(run_in_test_thread=lambda name, task: (name, task))
        marker = object()

        self.assertEqual(service.run_in_test_thread("task", marker), ("task", marker))


if __name__ == "__main__":
    unittest.main()
