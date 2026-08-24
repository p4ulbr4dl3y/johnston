import os
from unittest.mock import patch

from core.infrastructure.secrets import (
    get_secret,
    interpolate_secrets,
    interpolate_secrets_in_obj,
    load_secrets,
    save_secret,
)


def test_load_and_save_secrets(tmp_path):
    secrets_file = str(tmp_path / "secrets.json")
    with patch("core.infrastructure.secrets.SECRETS_FILE", secrets_file), patch(
        "core.infrastructure.secrets.CONFIG_DIR", str(tmp_path)
    ):
        assert load_secrets() == {}
        save_secret("TEST_KEY", "secret_val_123")
        assert load_secrets() == {"TEST_KEY": "secret_val_123"}
        assert get_secret("TEST_KEY") == "secret_val_123"


def test_get_secret_fallbacks(tmp_path):
    secrets_file = str(tmp_path / "secrets.json")
    with (
        patch("core.infrastructure.secrets.SECRETS_FILE", secrets_file),
        patch("core.infrastructure.secrets.CONFIG_DIR", str(tmp_path)),
        patch.dict(os.environ, {"ENV_ONLY_KEY": "env_val", "MY_PROVIDER_API_KEY": "prov_val"}),
    ):
        save_secret("FILE_KEY", "file_val")
        save_secret("OPENROUTER_API_KEY", "sk-or-test")

        # Direct from env
        assert get_secret("ENV_ONLY_KEY") == "env_val"
        # Direct from file
        assert get_secret("FILE_KEY") == "file_val"
        # Provider key variant from file
        assert get_secret("openrouter") == "sk-or-test"
        # Provider key variant from env
        assert get_secret("my-provider") == "prov_val"
        # Default
        assert get_secret("NONEXISTENT", default="def") == "def"


def test_interpolate_secrets(tmp_path):
    secrets_file = str(tmp_path / "secrets.json")
    with patch("core.infrastructure.secrets.SECRETS_FILE", secrets_file), patch(
        "core.infrastructure.secrets.CONFIG_DIR", str(tmp_path)
    ):
        save_secret("DB_PASS", "pass123")
        save_secret("TOKEN", "tok456")

        raw_str = "postgresql://user:${DB_PASS}@localhost/$TOKEN"
        interpolated = interpolate_secrets(raw_str)
        assert interpolated == "postgresql://user:pass123@localhost/tok456"

        nested = {
            "url": "https://api.example.com?token=${TOKEN}",
            "args": ["--pass", "${DB_PASS}"],
            "num": 42,
        }
        res = interpolate_secrets_in_obj(nested)
        assert res["url"] == "https://api.example.com?token=tok456"
        assert res["args"] == ["--pass", "pass123"]
        assert res["num"] == 42
