import unittest

from models import ClickAction, Variable, WaitAction
from state import format_action_summary


class FormatActionSummaryRegressionTests(unittest.TestCase):
    def test_accepts_action_without_app_state(self):
        act = ClickAction(var_name="boss", x=10, y=20, btn="left", rel=True)
        summary = format_action_summary(act, current_variables={})
        self.assertIn("點擊", summary)
        self.assertIn("boss", summary)

    def test_accepts_legacy_app_state_signature(self):
        class DummyAppState:
            variables = {
                "heal": Variable(type="wait", value=1.5),
            }

        act = WaitAction(var_name="heal", sec=2.0)
        summary = format_action_summary(DummyAppState(), act)
        self.assertIn("heal", summary)
        self.assertIn("停頓", summary)


if __name__ == "__main__":
    unittest.main()
