import sys
import unittest

import config_manager
import win32_api


class WindowsGuardAndProfileValidationTests(unittest.TestCase):
    def test_windows_guard_reports_supported_platform(self):
        self.assertIsInstance(win32_api.is_windows_supported(), bool)

    def test_require_windows_runtime_raises_on_non_windows(self):
        if sys.platform != "win32":
            with self.assertRaises(RuntimeError):
                win32_api.require_windows_runtime()

    def test_background_input_does_not_fallback_to_foreground(self):
        if sys.platform != "win32":
            with self.assertRaises(RuntimeError):
                win32_api.post_bg_click(None, 123, 10, 20)
            with self.assertRaises(RuntimeError):
                win32_api.post_bg_key(None, 123, "a")

    def test_validate_profile_data_rejects_invalid_payloads(self):
        invalid = {"variables": "bad", "combos": "bad", "steps": "bad", "periodic_tasks": "bad"}
        valid = config_manager.validate_profile_data(invalid)
        self.assertIsInstance(valid["variables"], dict)
        self.assertIsInstance(valid["combos"], list)
        self.assertIsInstance(valid["steps"], list)
        self.assertIsInstance(valid["periodic_tasks"], list)


if __name__ == "__main__":
    unittest.main()
