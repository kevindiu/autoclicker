import unittest
from unittest.mock import patch

import events
from autoclicker import App
from controllers import StepController
from models import KeyAction


class StepControllerRuntimeTests(unittest.TestCase):
    def test_test_run_execution_flow_passes_app_state(self):
        app = App()
        try:
            app.app_state.steps = [KeyAction(key="a")]
            app.run_in_test_thread = lambda name, task: task()
            step_ctrl = StepController(app)

            with patch("engine.test_run_execution_flow_worker") as mock_run:
                step_ctrl.test_run_execution_flow()
                mock_run.assert_called_once_with(app.app_state)
        finally:
            app.destroy()

    def test_app_closes_and_unsubscribes_events(self):
        app = App()
        app.on_close()
        self.assertNotIn(app._on_vars_changed, events.EventBus._subscribers.get("VARS_CHANGED", []))


if __name__ == "__main__":
    unittest.main()
