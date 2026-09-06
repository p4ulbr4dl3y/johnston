"""Tests for Johnston CLI config command and formatter utilities."""
from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from core.domain.defaults.config import DEFAULT_CONTEXT_LIMIT
from core.infrastructure.config.settings import JohnstonSettings, load_settings, save_settings
from core.infrastructure.platform import paths
from core.interfaces.cli.commands.config_cmd import (
    get_config,
    list_config,
    resolve_key,
    run_config,
    set_config,
    unset_config,
)
from core.interfaces.cli.entrypoint import main
from core.interfaces.cli.formatter import (
    format_key_status,
    format_kv,
    format_status,
    format_table,
    supports_color,
)


class TestCLIFormatter(unittest.TestCase):
    def test_supports_color_no_color_env(self):
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertFalse(supports_color())

    def test_supports_color_dumb_term(self):
        with patch.dict(os.environ, {"TERM": "dumb", "NO_COLOR": ""}):
            self.assertFalse(supports_color())

    def test_format_status(self):
        self.assertEqual(format_status(True, colorize=False), "✓")
        self.assertEqual(format_status(False, colorize=False), "✗")
        colored = format_status(True, colorize=True)
        self.assertTrue("✓" in colored)

    def test_format_key_status(self):
        self.assertEqual(format_key_status(True, colorize=False), "[set]")
        self.assertEqual(format_key_status(False, colorize=False), "[unset]")

    def test_format_table_empty(self):
        self.assertEqual(format_table([], []), "")

    def test_format_table_layout(self):
        headers = ["ColA", "ColB"]
        rows = [["val1", "val2"], ["longer_val", "v"]]
        rendered = format_table(headers, rows)
        self.assertIn("ColA", rendered)
        self.assertIn("ColB", rendered)
        self.assertIn("---", rendered)
        self.assertIn("longer_val", rendered)

    def test_format_kv_empty(self):
        self.assertEqual(format_kv([]), "")

    def test_format_kv(self):
        rendered = format_kv([("key1", "val1"), ("key2", 42)])
        self.assertIn("key1", rendered)
        self.assertIn("42", rendered)


class TestCLIConfig(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.cfg_file = os.path.join(self.tmp_dir.name, "config.json")
        self.patcher = patch.object(paths, "CONFIG_FILE", self.cfg_file)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp_dir.cleanup()

    def test_resolve_key_valid(self):
        can, sec, f_name, _ = resolve_key("theme")
        self.assertEqual(can, "theme")
        self.assertIsNone(sec)
        self.assertEqual(f_name, "theme")

        can, sec, f_name, _ = resolve_key("llm.context_limit")
        self.assertEqual(can, "llm.context_limit")
        self.assertEqual(sec, "llm")
        self.assertEqual(f_name, "context_limit")

        can, sec, f_name, _ = resolve_key("context_limit")
        self.assertEqual(can, "llm.context_limit")

    def test_resolve_key_invalid(self):
        with self.assertRaises(KeyError):
            resolve_key("nonexistent")
        with self.assertRaises(KeyError):
            resolve_key("llm.nonexistent_field")
        with self.assertRaises(KeyError):
            resolve_key("badsec.field")

    def test_config_list(self):
        save_settings(JohnstonSettings(theme="nord"), self.cfg_file)
        f = io.StringIO()
        with redirect_stdout(f):
            ret = list_config(self.cfg_file)
        self.assertEqual(ret, 0)
        out = f.getvalue()
        self.assertIn("Setting", out)
        self.assertIn("Value", out)
        self.assertIn("Source", out)
        self.assertIn("theme", out)
        self.assertIn("nord", out)
        self.assertIn("config", out)
        self.assertIn("llm.context_limit", out)
        self.assertIn("default", out)

    def test_config_get_theme_none_and_set(self):
        f = io.StringIO()
        with redirect_stdout(f):
            ret = get_config("theme", self.cfg_file)
        self.assertEqual(ret, 0)
        self.assertEqual(f.getvalue().strip(), "None")

        save_settings(JohnstonSettings(theme="tokyo-night"), self.cfg_file)
        f2 = io.StringIO()
        with redirect_stdout(f2):
            ret = get_config("theme", self.cfg_file)
        self.assertEqual(ret, 0)
        self.assertEqual(f2.getvalue().strip(), "tokyo-night")

    def test_config_get_nested_and_bare(self):
        f = io.StringIO()
        with redirect_stdout(f):
            ret = get_config("llm.context_limit", self.cfg_file)
        self.assertEqual(ret, 0)
        self.assertEqual(f.getvalue().strip(), str(DEFAULT_CONTEXT_LIMIT))

        f2 = io.StringIO()
        with redirect_stdout(f2):
            ret = get_config("context_limit", self.cfg_file)
        self.assertEqual(ret, 0)
        self.assertEqual(f2.getvalue().strip(), str(DEFAULT_CONTEXT_LIMIT))

    def test_config_get_unknown_key(self):
        err = io.StringIO()
        with redirect_stderr(err):
            ret = get_config("nonexistent_key", self.cfg_file)
        self.assertEqual(ret, 1)
        self.assertIn("Unknown configuration key", err.getvalue())

    def test_config_set_theme(self):
        f = io.StringIO()
        with redirect_stdout(f):
            ret = set_config("theme", "dracula", self.cfg_file)
        self.assertEqual(ret, 0)
        self.assertIn("Set 'theme' to 'dracula'", f.getvalue())

        loaded = load_settings(self.cfg_file)
        self.assertEqual(loaded.theme, "dracula")

    def test_config_set_bool(self):
        f = io.StringIO()
        with redirect_stdout(f):
            ret = set_config("sandbox.enabled", "true", self.cfg_file)
        self.assertEqual(ret, 0)
        loaded = load_settings(self.cfg_file)
        self.assertTrue(loaded.sandbox.enabled)

        with redirect_stdout(f):
            ret = set_config("sandbox.enabled", "false", self.cfg_file)
        self.assertEqual(ret, 0)
        loaded = load_settings(self.cfg_file)
        self.assertFalse(loaded.sandbox.enabled)

    def test_config_set_bool_invalid(self):
        err = io.StringIO()
        with redirect_stderr(err):
            ret = set_config("sandbox.enabled", "maybe", self.cfg_file)
        self.assertEqual(ret, 1)
        self.assertIn("Invalid boolean value", err.getvalue())

    def test_config_set_int(self):
        f = io.StringIO()
        with redirect_stdout(f):
            ret = set_config("llm.context_limit", "150000", self.cfg_file)
        self.assertEqual(ret, 0)
        loaded = load_settings(self.cfg_file)
        self.assertEqual(loaded.llm.context_limit, 150000)

    def test_config_set_int_invalid(self):
        err = io.StringIO()
        with redirect_stderr(err):
            ret = set_config("llm.context_limit", "not_a_number", self.cfg_file)
        self.assertEqual(ret, 1)
        self.assertIn("Invalid integer value", err.getvalue())

    def test_config_set_int_constraint(self):
        err = io.StringIO()
        with redirect_stderr(err):
            ret = set_config("llm.context_limit", "50", self.cfg_file)
        self.assertEqual(ret, 1)
        self.assertIn("must be at least 1000", err.getvalue())

    def test_config_set_float(self):
        f = io.StringIO()
        with redirect_stdout(f):
            ret = set_config("llm.stream_timeout", "45.5", self.cfg_file)
        self.assertEqual(ret, 0)
        loaded = load_settings(self.cfg_file)
        self.assertEqual(loaded.llm.stream_timeout, 45.5)

    def test_config_set_float_invalid(self):
        err = io.StringIO()
        with redirect_stderr(err):
            ret = set_config("llm.stream_timeout", "bad_float", self.cfg_file)
        self.assertEqual(ret, 1)
        self.assertIn("Invalid float value", err.getvalue())

    def test_config_set_optional_none(self):
        set_config("llm.auto_compact_token_limit", "50000", self.cfg_file)
        loaded = load_settings(self.cfg_file)
        self.assertEqual(loaded.llm.auto_compact_token_limit, 50000)

        set_config("llm.auto_compact_token_limit", "none", self.cfg_file)
        loaded = load_settings(self.cfg_file)
        self.assertIsNone(loaded.llm.auto_compact_token_limit)

    def test_config_set_unknown_key(self):
        err = io.StringIO()
        with redirect_stderr(err):
            ret = set_config("does.not.exist", "val", self.cfg_file)
        self.assertEqual(ret, 1)
        self.assertIn("Unknown configuration key", err.getvalue())

    def test_config_unset(self):
        set_config("theme", "solarized", self.cfg_file)
        self.assertEqual(load_settings(self.cfg_file).theme, "solarized")

        f = io.StringIO()
        with redirect_stdout(f):
            ret = unset_config("theme", self.cfg_file)
        self.assertEqual(ret, 0)
        self.assertIn("Unset 'theme'", f.getvalue())
        self.assertIsNone(load_settings(self.cfg_file).theme)

        set_config("llm.context_limit", "160000", self.cfg_file)
        self.assertEqual(load_settings(self.cfg_file).llm.context_limit, 160000)
        with redirect_stdout(f):
            ret = unset_config("llm.context_limit", self.cfg_file)
        self.assertEqual(ret, 0)
        self.assertEqual(load_settings(self.cfg_file).llm.context_limit, DEFAULT_CONTEXT_LIMIT)

    def test_config_unset_unknown_key(self):
        err = io.StringIO()
        with redirect_stderr(err):
            ret = unset_config("unknown_key", self.cfg_file)
        self.assertEqual(ret, 1)
        self.assertIn("Unknown configuration key", err.getvalue())

    def test_run_config_helper(self):
        class DummyArgs:
            def __init__(self, action=None, key=None, value=None):
                self.config_action = action
                self.key = key
                self.value = value

        self.assertEqual(run_config(DummyArgs("list"), config_file=self.cfg_file), 0)
        self.assertEqual(run_config(DummyArgs("set", "theme", "monokai"), config_file=self.cfg_file), 0)
        self.assertEqual(run_config(DummyArgs("get", "theme"), config_file=self.cfg_file), 0)
        self.assertEqual(run_config(DummyArgs("unset", "theme"), config_file=self.cfg_file), 0)
        self.assertEqual(run_config(DummyArgs("unknown_action"), config_file=self.cfg_file), 1)

    def test_config_set_dict_value(self):
        ret = set_config("llm.thinking_efforts", '{"openai": {"o3-mini": "high"}}', self.cfg_file)
        self.assertEqual(ret, 0)
        settings = load_settings(self.cfg_file)
        self.assertEqual(settings.llm.thinking_efforts, {"openai": {"o3-mini": "high"}})

    def test_config_set_dict_invalid_json(self):
        err = io.StringIO()
        with redirect_stderr(err):
            ret = set_config("llm.thinking_efforts", "not-valid-json", self.cfg_file)
        self.assertEqual(ret, 1)
        self.assertIn("Invalid JSON", err.getvalue())

    def test_config_set_dict_non_dict_rejected(self):
        err = io.StringIO()
        with redirect_stderr(err):
            ret = set_config("llm.thinking_efforts", '"just-a-string"', self.cfg_file)
        self.assertEqual(ret, 1)
        self.assertIn("Invalid type", err.getvalue())


class TestCLIConfigEntrypoint(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.cfg_file = os.path.join(self.tmp_dir.name, "config.json")
        self.patcher = patch.object(paths, "CONFIG_FILE", self.cfg_file)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp_dir.cleanup()

    def test_main_config_list(self):
        f = io.StringIO()
        with redirect_stdout(f):
            with self.assertRaises(SystemExit) as cm:
                main(["config", "list"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("Setting", f.getvalue())

    def test_main_config_set_and_get(self):
        with self.assertRaises(SystemExit) as cm:
            main(["config", "set", "theme", "gruvbox"])
        self.assertEqual(cm.exception.code, 0)

        f = io.StringIO()
        with redirect_stdout(f):
            with self.assertRaises(SystemExit) as cm:
                main(["config", "get", "theme"])
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(f.getvalue().strip(), "gruvbox")

    def test_main_config_unset(self):
        with self.assertRaises(SystemExit) as cm:
            main(["config", "set", "theme", "gruvbox"])
        self.assertEqual(cm.exception.code, 0)

        with self.assertRaises(SystemExit) as cm:
            main(["config", "unset", "theme"])
        self.assertEqual(cm.exception.code, 0)

        f = io.StringIO()
        with redirect_stdout(f):
            with self.assertRaises(SystemExit) as cm:
                main(["config", "get", "theme"])
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(f.getvalue().strip(), "None")

    def test_main_config_get_unknown(self):
        with self.assertRaises(SystemExit) as cm:
            main(["config", "get", "unknown_key"])
        self.assertEqual(cm.exception.code, 1)

    def test_main_config_json_and_roles_json(self):
        import json
        for subcmd in ["roles", "skills", "rules"]:
            f = io.StringIO()
            with redirect_stdout(f):
                with self.assertRaises(SystemExit) as cm:
                    main([subcmd, "--json"])
            self.assertEqual(cm.exception.code, 0)
            data = json.loads(f.getvalue())
            self.assertIsInstance(data, list)

        f = io.StringIO()
        with redirect_stdout(f):
            with self.assertRaises(SystemExit) as cm:
                main(["config", "list", "--json"])
        self.assertEqual(cm.exception.code, 0)
        cfg_data = json.loads(f.getvalue())
        self.assertIsInstance(cfg_data, list)

        f = io.StringIO()
        with redirect_stdout(f):
            with self.assertRaises(SystemExit) as cm:
                main(["config", "get", "theme", "--json"])
        self.assertEqual(cm.exception.code, 0)
        get_data = json.loads(f.getvalue())
        self.assertIn("theme", get_data)


if __name__ == "__main__":
    unittest.main()
