"""Unit tests for the shared provider models-cache path helper."""
import os

from core.infrastructure.platform import paths


def test_provider_models_cache_path_filename_and_dir():
    for provider_key in ("anthropic", "openai", "ollama", "some-custom.provider"):
        path = paths.provider_models_cache_path(provider_key)
        assert path.name == f"models_{provider_key}.json"
        assert str(path.parent) == paths.CACHE_DIR


def test_provider_models_cache_path_matches_legacy_join():
    provider_key = "gemini"
    assert str(paths.provider_models_cache_path(provider_key)) == os.path.join(
        paths.CACHE_DIR, f"models_{provider_key}.json"
    )
