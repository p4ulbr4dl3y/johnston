import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from core.domain.policies.permission_policy import ExecutionMode
from core.permission_manager import PermissionManager
from widgets.app.app import JohnstonApp
from widgets.mixins.actions import ActionsMixin


class DummyActionApp(ActionsMixin):
    def __init__(self):
        self.refreshed = False
        self.notifications = []

    def refresh_status_footer(self):
        self.refreshed = True

    def notify(self, message, timeout=2):
        self.notifications.append((message, timeout))


class TestExecutionModeUI(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        self.config_patcher = patch("core.permission_manager.CONFIG_FILE", os.path.join(self.test_dir, "config.json"))
        self.config_patcher.start()
        PermissionManager._instance = None
        self.pm = PermissionManager.get_instance()

    def tearDown(self):
        self.config_patcher.stop()
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)
        PermissionManager._instance = None

    def test_toggle_mode_cycle(self):
        app = DummyActionApp()
        self.assertEqual(self.pm.execution_mode, ExecutionMode.REVIEW)

        # 1. review -> edits
        app.action_toggle_mode()
        self.assertEqual(self.pm.execution_mode, ExecutionMode.EDITS)
        self.assertTrue(app.refreshed)

        # 2. edits -> yolo
        app.action_toggle_mode()
        self.assertEqual(self.pm.execution_mode, ExecutionMode.YOLO)

        # 3. yolo -> review
        app.action_toggle_mode()
        self.assertEqual(self.pm.execution_mode, ExecutionMode.REVIEW)

    def test_tab_and_shift_tab_bindings(self):
        binding_dict = {b[0]: b[1] for b in JohnstonApp.BINDINGS}
        self.assertEqual(binding_dict.get("tab"), "toggle_role")
        self.assertEqual(binding_dict.get("shift+tab"), "toggle_mode")



if __name__ == "__main__":
    unittest.main()
