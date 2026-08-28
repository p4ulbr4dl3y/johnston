import json
import os
import tempfile

import pytest

from core.domain.defaults.config import MAX_CONCURRENT_SUBAGENTS
from core.infrastructure.config.config_helpers import (
    ensure_json_config,
    load_max_concurrent_subagents,
    load_sandbox_config,
    load_theme_config,
    save_max_concurrent_subagents,
    save_sandbox_config,
    save_theme_config,
)


def test_ensure_json_config_creates_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "subdir", "config.json")
        ensure_json_config(path, {"default_key": "val"})
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data == {"default_key": "val"}


def test_sandbox_config_load_and_save():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        assert load_sandbox_config(path) is False
        save_sandbox_config(True, path)
        assert load_sandbox_config(path) is True
        save_sandbox_config(False, path)
        assert load_sandbox_config(path) is False


def test_theme_config_load_and_save():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        assert load_theme_config(path) is None
        save_theme_config("dracula", path)
        assert load_theme_config(path) == "dracula"


def test_max_concurrent_subagents_defaults():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        assert load_max_concurrent_subagents(path) == MAX_CONCURRENT_SUBAGENTS


def test_max_concurrent_subagents_config_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        save_max_concurrent_subagents(12, path)
        assert load_max_concurrent_subagents(path) == 12


def test_max_concurrent_subagents_env_override(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        save_max_concurrent_subagents(10, path)

        monkeypatch.setenv("JOHNSTON_MAX_CONCURRENT_SUBAGENTS", "20")
        assert load_max_concurrent_subagents(path) == 20

        monkeypatch.setenv("JOHNSTON_MAX_CONCURRENT_SUBAGENTS", "invalid")
        assert load_max_concurrent_subagents(path) == 10


def test_save_max_concurrent_subagents_invalid_value():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        with pytest.raises(ValueError):
            save_max_concurrent_subagents(0, path)
        with pytest.raises(ValueError):
            save_max_concurrent_subagents(-5, path)
