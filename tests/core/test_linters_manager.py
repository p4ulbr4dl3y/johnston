import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core.linters_manager import PRESET_LINTERS, LintersManager, get_linters_manager


class TestLintersManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        import shutil

        shutil.rmtree(self.test_dir)

    def _mgr(self, **kw):
        config = os.path.join(self.test_dir, "linters.json")
        m = LintersManager(config_file=config, **kw)
        # Re-point config to a temp path so tests never touch the user's
        # ~/.johnston/linters.json.
        m.config_file = config
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

    def test_custom_config_entries_loaded(self):
        m = self._mgr()
        with open(m.config_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "linters": {
                        "python": {"enabled": False},
                        "mycustom": {"cmd": ["my-tool", "{file}"], "extensions": [".mc"]},
                    }
                },
                f,
            )

        linters = m.load_linters()
        py = next(it for it in linters if it["name"] == "python")
        self.assertFalse(py["enabled"])
        self.assertEqual(py["scope"], "preset")

        c = next(it for it in linters if it["name"] == "mycustom")
        self.assertEqual(c["cmd"][0], "my-tool")
        self.assertTrue(c["custom"])

    def test_toggle_enabled_persists(self):
        m = self._mgr()
        with open(m.config_file, "w", encoding="utf-8") as f:
            json.dump({"linters": {"php": {"enabled": True}}}, f)

        ok = m.set_enabled("php", False)
        self.assertTrue(ok)
        self.assertFalse(m.set_enabled("nope", True))

        m2 = LintersManager(config_file=m.config_file)
        php = next(it for it in m2.load_linters() if it["name"] == "php")
        self.assertFalse(php["enabled"])

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
            self.assertNotIn("php", [it["name"] for it in m.get_for_extension(".php")])

    def test_render_cmd_expands_placeholders(self):
        m = self._mgr()
        lint = PRESET_LINTERS["rust"]
        cmd = m.render_cmd(lint, "/tmp/x.rs")
        self.assertIn("/tmp/x.rs", cmd)
        self.assertTrue(any(c.startswith("/") for c in cmd))
        self.assertTrue(any(c.endswith(".rmeta") for c in cmd))

    def test_scan_available_system_tools(self):
        m = self._mgr()
        av = m.scan_available()
        # python/rust resolve via which(); others may be absent on some CI.
        self.assertIn("python", av)
        self.assertIn("rust", av)

    def test_linters_command_registered(self):
        from widgets.commands import COMMAND_REGISTRY

        self.assertIn("/linters", COMMAND_REGISTRY)
        self.assertIn("/lint", COMMAND_REGISTRY)

    def test_get_linters_manager_singleton(self):
        inst1 = get_linters_manager()
        inst2 = get_linters_manager()
        self.assertIs(inst1, inst2)


if __name__ == "__main__":
    unittest.main()
