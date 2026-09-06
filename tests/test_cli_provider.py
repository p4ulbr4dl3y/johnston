"""Tests for Johnston CLI provider command."""
from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

from core.infrastructure.platform import paths
from core.interfaces.cli.commands.provider_cmd import (
    add_provider_cmd,
    disable_provider,
    enable_provider,
    list_providers,
    print_models,
    rm_provider_cmd,
    run_provider,
    set_key,
    set_model,
)
from core.interfaces.cli.entrypoint import build_parser, main
from core.provider_manager import ProviderManager


class TestCLIProvider(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.cfg_file = os.path.join(self.tmp_dir.name, "config.json")
        self.prov_file = os.path.join(self.tmp_dir.name, "providers.json")
        self.patch_cfg = patch.object(paths, "CONFIG_FILE", self.cfg_file)
        self.patch_prov = patch.object(paths, "PROVIDERS_JSON_FILE", self.prov_file)
        self.patch_cfg.start()
        self.patch_prov.start()

    def tearDown(self):
        self.patch_prov.stop()
        self.patch_cfg.stop()
        self.tmp_dir.cleanup()

    def test_list_providers_table_output(self):
        f = io.StringIO()
        pm = MagicMock()
        pm.load_providers.return_value = {
            "openai": {"name": "OpenAI", "model": "gpt-4o", "enabled": True},
            "ollama": {"name": "Ollama", "model": "llama3", "enabled": True},
            "custom": {"name": "Custom", "model": "m1", "enabled": False},
        }
        pm.get_active_provider_key.return_value = "openai"
        pm.get_disabled_providers.return_value = ["custom"]
        pm.get_provider_model.side_effect = lambda k: "gpt-4o" if k == "openai" else ("llama3" if k == "ollama" else "m1")
        pm.get_api_key.side_effect = lambda k: "sk-test" if k == "openai" else ""
        pm.load_provider_def.return_value = MagicMock(requires_key=True)

        def mock_needs_key(k, pdef):
            return k != "ollama"

        pm.provider_needs_key.side_effect = mock_needs_key

        with redirect_stdout(f):
            code = list_providers(pm)

        self.assertEqual(code, 0)
        output = f.getvalue()
        self.assertIn("Active", output)
        self.assertIn("Provider", output)
        self.assertIn("Model", output)
        self.assertIn("API Key status", output)
        self.assertIn("State", output)
        # Check active provider row
        self.assertIn("*", output)
        self.assertIn("openai", output)
        self.assertIn("active", output)
        self.assertIn("set", output)
        # Check local/not required provider row
        self.assertIn("ollama", output)
        self.assertIn("not required", output)
        self.assertIn("ready", output)
        # Check disabled provider row
        self.assertIn("custom", output)
        self.assertIn("disabled", output)

    def test_list_providers_default_models_fallback(self):
        f = io.StringIO()
        pm = MagicMock()
        pm.load_providers.return_value = {
            "empty_model": {"name": "Empty", "models": ["fallback-model"], "enabled": True}
        }
        pm.get_active_provider_key.return_value = ""
        pm.get_disabled_providers.return_value = []
        pm.get_provider_model.return_value = ""
        pm.get_api_key.return_value = ""
        pm.load_provider_def.return_value = None

        with redirect_stdout(f):
            code = list_providers(pm)

        self.assertEqual(code, 0)
        output = f.getvalue()
        self.assertIn("fallback-model", output)
        self.assertIn("unset", output)
        self.assertIn("ready", output)

    def test_set_key(self):
        pm = MagicMock()
        f = io.StringIO()
        with redirect_stdout(f):
            code = set_key("openai", "sk-123456", pm)
        self.assertEqual(code, 0)
        pm.set_provider_api_key.assert_called_once_with("openai", "sk-123456")
        self.assertIn("API key for 'openai' saved.", f.getvalue())

    def test_set_key_validation(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = set_key("", "sk-123")
        self.assertEqual(code, 1)
        self.assertIn("Error", err.getvalue())

    def test_set_model(self):
        pm = MagicMock()
        f = io.StringIO()
        with redirect_stdout(f):
            code = set_model("openai", "gpt-4o-mini", pm)
        self.assertEqual(code, 0)
        pm.set_provider_model.assert_called_once_with("openai", "gpt-4o-mini")
        self.assertIn("Model for 'openai' set to 'gpt-4o-mini'.", f.getvalue())

    def test_set_model_validation(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = set_model("openai", "")
        self.assertEqual(code, 1)
        self.assertIn("Error", err.getvalue())

    def test_enable_provider(self):
        pm = MagicMock()
        f = io.StringIO()
        with redirect_stdout(f):
            code = enable_provider("anthropic", pm)
        self.assertEqual(code, 0)
        pm.set_provider_disabled.assert_called_once_with("anthropic", False)
        self.assertIn("Provider 'anthropic' enabled.", f.getvalue())

    def test_enable_provider_validation(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = enable_provider("")
        self.assertEqual(code, 1)

    def test_disable_provider(self):
        pm = MagicMock()
        f = io.StringIO()
        with redirect_stdout(f):
            code = disable_provider("anthropic", pm)
        self.assertEqual(code, 0)
        pm.set_provider_disabled.assert_called_once_with("anthropic", True)
        self.assertIn("Provider 'anthropic' disabled.", f.getvalue())

    def test_disable_provider_validation(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = disable_provider("")
        self.assertEqual(code, 1)

    def test_add_provider_cmd(self):
        pm = MagicMock()
        f = io.StringIO()
        with redirect_stdout(f):
            code = add_provider_cmd(
                "my_llm",
                model="my-model-1",
                api_key="secret-key",
                base_url="https://api.myllm.com",
                pm=pm,
            )
        self.assertEqual(code, 0)
        pm.add_provider.assert_called_once_with(
            "my_llm",
            model="my-model-1",
            api_key="secret-key",
            base_url="https://api.myllm.com",
        )
        self.assertIn("Provider 'my_llm' added.", f.getvalue())

    def test_add_provider_cmd_validation(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = add_provider_cmd("", "model")
        self.assertEqual(code, 1)

    def test_rm_provider_cmd_success(self):
        pm = MagicMock()
        pm.remove_provider.return_value = True
        f = io.StringIO()
        with redirect_stdout(f):
            code = rm_provider_cmd("old_llm", pm)
        self.assertEqual(code, 0)
        pm.remove_provider.assert_called_once_with("old_llm")
        self.assertIn("Provider 'old_llm' removed.", f.getvalue())

    def test_rm_provider_cmd_not_found(self):
        pm = MagicMock()
        pm.remove_provider.return_value = False
        err = io.StringIO()
        with redirect_stderr(err):
            code = rm_provider_cmd("nonexistent", pm)
        self.assertEqual(code, 1)
        self.assertIn("Provider 'nonexistent' not found.", err.getvalue())

    def test_rm_provider_cmd_validation(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = rm_provider_cmd("")
        self.assertEqual(code, 1)

    def test_run_provider_routing(self):
        pm = MagicMock()
        parser = build_parser()

        # default list
        args = parser.parse_args(["provider"])
        code = run_provider(args, pm)
        self.assertEqual(code, 0)

        # explicit list
        args = parser.parse_args(["provider", "list"])
        code = run_provider(args, pm)
        self.assertEqual(code, 0)

        # set-key
        args = parser.parse_args(["provider", "set-key", "p1", "k1"])
        code = run_provider(args, pm)
        self.assertEqual(code, 0)
        pm.set_provider_api_key.assert_called_with("p1", "k1")

        # set-model
        args = parser.parse_args(["provider", "set-model", "p1", "m1"])
        code = run_provider(args, pm)
        self.assertEqual(code, 0)
        pm.set_provider_model.assert_called_with("p1", "m1")

        # enable
        args = parser.parse_args(["provider", "enable", "p1"])
        code = run_provider(args, pm)
        self.assertEqual(code, 0)
        pm.set_provider_disabled.assert_called_with("p1", False)

        # disable
        args = parser.parse_args(["provider", "disable", "p1"])
        code = run_provider(args, pm)
        self.assertEqual(code, 0)
        pm.set_provider_disabled.assert_called_with("p1", True)

        # add
        args = parser.parse_args(["provider", "add", "p2", "--model", "m2", "--api-key", "k2", "--base-url", "u2"])
        code = run_provider(args, pm)
        self.assertEqual(code, 0)
        pm.add_provider.assert_called_with("p2", model="m2", api_key="k2", base_url="u2")

        # rm
        pm.remove_provider.return_value = True
        args = parser.parse_args(["provider", "rm", "p2"])
        code = run_provider(args, pm)
        self.assertEqual(code, 0)
        pm.remove_provider.assert_called_with("p2")

    def test_run_provider_unknown_action(self):
        args = MagicMock()
        args.provider_action = "unknown_action"
        err = io.StringIO()
        with redirect_stderr(err):
            code = run_provider(args)
        self.assertEqual(code, 1)

    def test_main_subcommand_provider(self):
        with patch("core.interfaces.cli.commands.provider_cmd.run_provider", return_value=0) as mock_run:
            with self.assertRaises(SystemExit) as cm:
                main(["provider", "list"])
            self.assertEqual(cm.exception.code, 0)
            mock_run.assert_called_once()

    def test_provider_manager_add_and_remove_integration(self):
        pm = ProviderManager()
        pm.add_provider("test_prov", model="test-model", api_key="sk-test", base_url="http://localhost:8000")
        providers = pm.load_providers()
        self.assertIn("test_prov", providers)
        self.assertEqual(providers["test_prov"]["model"], "test-model")

        # Now remove it
        removed = pm.remove_provider("test_prov")
        self.assertTrue(removed)
        providers_after = pm.load_providers()
        self.assertNotIn("test_prov", providers_after)

    def test_print_models_legacy(self):
        f = io.StringIO()
        with redirect_stdout(f):
            print_models()
        self.assertIn("Available Johnston Providers & Models:", f.getvalue())


if __name__ == "__main__":
    unittest.main()
