"""Unit tests for the shared ``update_json_config`` helper in platform_utils."""

import json

from core.infrastructure.platform.platform_utils import (
    cached_json_read,
    update_json_config,
)


def test_creates_file_when_missing(tmp_path):
    path = str(tmp_path / "nested" / "config.json")

    result = update_json_config(path, lambda cfg: cfg.__setitem__("key", "value"))

    assert result == {"key": "value"}
    assert json.loads((tmp_path / "nested" / "config.json").read_text()) == {"key": "value"}


def test_updates_key(tmp_path):
    path = str(tmp_path / "config.json")
    path_obj = tmp_path / "config.json"
    path_obj.write_text(json.dumps({"a": 1, "b": 2}))

    result = update_json_config(path, lambda cfg: cfg.__setitem__("a", 99))

    assert result == {"a": 99, "b": 2}
    assert json.loads(path_obj.read_text()) == {"a": 99, "b": 2}


def test_preserves_other_keys(tmp_path):
    path = str(tmp_path / "config.json")
    path_obj = tmp_path / "config.json"
    path_obj.write_text(json.dumps({"keep": "me", "drop": "this"}))

    def _mutate(cfg):
        cfg["added"] = True
        cfg.pop("drop", None)

    update_json_config(path, _mutate)

    assert json.loads(path_obj.read_text()) == {"keep": "me", "added": True}


def test_non_dict_content_is_overwritten(tmp_path):
    path = str(tmp_path / "config.json")
    path_obj = tmp_path / "config.json"
    path_obj.write_text("[1, 2, 3]")

    result = update_json_config(path, lambda cfg: cfg.__setitem__("key", "val"))

    assert result == {"key": "val"}
    assert json.loads(path_obj.read_text()) == {"key": "val"}


def test_invalidates_read_cache(tmp_path):
    path = str(tmp_path / "config.json")
    path_obj = tmp_path / "config.json"
    path_obj.write_text(json.dumps({"v": 1}))

    # Populate the shared cache.
    assert cached_json_read(path, {}) == {"v": 1}
    # Make sure a write happens even though mtime may be unchanged.
    update_json_config(path, lambda cfg: cfg.__setitem__("v", 2))

    # The helper invalidates the cache, so a fresh read sees the new value.
    assert cached_json_read(path, {}) == {"v": 2}


def test_returns_updated_dict(tmp_path):
    path = str(tmp_path / "config.json")

    result = update_json_config(path, lambda cfg: cfg.__setitem__("x", 10), indent=4)

    assert result == {"x": 10}
    content = (tmp_path / "config.json").read_text()
    assert '    "x": 10' in content  # indent=4 honored
