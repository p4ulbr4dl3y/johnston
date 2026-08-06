import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from core.commands import COMMAND_REGISTRY
from core.linters_manager import PRESET_LINTERS, LintersManager


class TestLintersManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def _mgr(self, **kw):
        m = LintersManager(project_dir=self.test_dir, **kw)
        return m

    def test_presets_loaded_with_defaults(self):
        m = self._mgr()
        linters = m.load_linters()
        names = [it["name"] for it in linters]
        for preset in PRESET_LINTERS:
            self.assertIn(preset, names)
        p = next(it for it in linters if it["name"] == "python")
        self.assertTrue(p["enabled"])
        self.assertEqual(p["scope"], "preset")
        self.assertIn(".py", p["extensions"])

    def test_global_and_project_merge(self):
        m = self._mgr()
        m.global_file = os.path.join(self.test_dir, "global_linters.json")
        with open(m.global_file, "w", encoding="utf-8") as f:
            json.dump({
                "linters": {
                    "python": {"enabled": False},
                    "myglobal": {"cmd": ["g1", "{file}"], "extensions": [".g1"]},
                }
            }, f)

        os.makedirs(os.path.dirname(m.project_file), exist_ok=True)
        with open(m.project_file, "w", encoding="utf-8") as f:
            json.dump({
                "linters": {
                    "python": {"enabled": True, "cmd": ["proj-uff"]},
                    "myproj": {"cmd": ["p1", "{file}"], "extensions": [".p1"]},
                }
            }, f)

        linters = m.load_linters()
        py = next(it for it in linters if it["name"] == "python")
        self.assertTrue(py["enabled"])
        self.assertEqual(py["cmd"][0], "proj-uff")
        self.assertEqual(py["scope"], "project")

        g = next(it for it in linters if it["name"] == "myglobal")
        self.assertEqual(g["scope"], "global")
        p = next(it for it in linters if it["name"] == "myproj")
        self.assertEqual(p["scope"], "project")
        self.assertTrue(p["custom"])

    def test_toggle_enabled_persists(self):
        m = self._mgr()
        m.global_file = os.path.join(self.test_dir, "g.json")
        # custom entry to prove persistence
        os.makedirs(os.path.dirname(m.project_file), exist_ok=True)
        with open(m.project_file, "w", encoding="utf-8") as f:
            json.dump({"linters": {"php": {"enabled": True}}}, f)

        ok = m.set_enabled("php", False)
        self.assertTrue(ok)
        m2 = LintersManager(project_dir=self.test_dir)
        m2.global_file = m.global_file
        php = next(it for it in m2.load_linters() if it["name"] == "php")
        self.assertFalse(php["enabled"])
        self.assertEqual(php["scope"], "project")

    def test_set_enabled_unknown_returns_false(self):
        m = self._mgr()
        self.assertFalse(m.set_enabled("nope", True))

    def test_get_for_extension_filters_enabled_available(self):
        m = self._mgr()
        with patch.object(m, "is_available", side_effect=lambda n: n in ("python", "rust")):
            py = m.get_for_extension(".py")
            self.assertEqual([it["name"] for it in py], ["python"])
            rs = m.get_for_extension(".rs")
            self.assertEqual([it["name"] for it in rs], ["rust"])
            # php disabled? no - it's enabled by default, but is_available False
            self.assertNotIn("php", [it["name"] for it in m.get_for_extension(".php")])

    def test_render_cmd_expands_placeholders(self):
        m = self._mgr()
        lint = PRESET_LINTERS["rust"]
        cmd = m.render_cmd(lint, "/tmp/x.rs")
        self.assertIn("/tmp/x.rs", cmd)
        self.assertTrue(any(c.startswith("/") for c in cmd))
        # {tmp} expanded
        self.assertTrue(any(c.endswith(".rmeta") for c in cmd))

    def test_scan_available_system_tools(self):
        m = self._mgr()
        av = m.scan_available()
        # bash should be present everywhere; jq/php may be absent on some CI
        self.assertTrue(av["bash"])
        self.assertIn("python", av)

    def test_linters_command_registered(self):
        self.assertIn("/linters", COMMAND_REGISTRY)
        self.assertIn("/lint", COMMAND_REGISTRY)

    def test_get_linters_manager_singleton(self):
        from core.linters_manager import get_linters_manager
        inst1 = get_linters_manager(self.test_dir)
        self.assertEqual(inst1.project_dir, os.path.realpath(self.test_dir))
        dir2 = tempfile.mkdtemp()
        try:
            inst2 = get_linters_manager(dir2)
            self.assertEqual(inst2.project_dir, os.path.realpath(dir2))
            self.assertIs(inst1, inst2)
        finally:
            shutil.rmtree(dir2)


if __name__ == "__main__":
    unittest.main()
