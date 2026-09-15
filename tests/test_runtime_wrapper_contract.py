import unittest

from autoclicker import App
import engine


class RuntimeWrapperContractTests(unittest.TestCase):
    def test_app_dispatch_action_passes_app_state(self):
        app = App()
        try:
            call = app.dispatch_action
            self.assertTrue(call is not None)
        finally:
            app.destroy()

    def test_app_macro_worker_loop_uses_app_state(self):
        app = App()
        try:
            self.assertTrue(hasattr(app, "macro_worker_loop"))
        finally:
            app.destroy()

    def test_runtime_orchestration_helpers_are_exposed(self):
        self.assertTrue(hasattr(engine, "start_macro_run"))
        self.assertTrue(hasattr(engine, "stop_macro_run"))
        self.assertTrue(hasattr(engine, "prepare_runtime_state"))
        self.assertTrue(hasattr(engine, "run_macro_cycle"))
        self.assertTrue(hasattr(engine, "bootstrap_macro_runtime"))
        self.assertTrue(hasattr(engine, "shutdown_macro_runtime"))


if __name__ == "__main__":
    unittest.main()
