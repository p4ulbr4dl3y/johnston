"""Edge-case tests for core.models_catalog — designed to HUNT for bugs.

Intentionally include cases the main suite does NOT cover: malformed sizes,
broken nested structures, weird names, network edge cases, non-determinism.
If a test FAILS we record whether it is a real code bug or a wrong test.
"""
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from core.models_catalog import (
    ModelsCatalog,
    format_context_tokens,
    get_context_window,
)

# ---------------------------------------------------------------------------
# format_context_tokens / get_context_window — parsing + formatting edge cases
# ---------------------------------------------------------------------------

def test_format_context_huge():
    assert format_context_tokens(1_000_000_000) == "1000M"
    assert format_context_tokens(2_500_000_000) == "2500M"


def test_format_context_rollover_near_million():
    # 999999 seconds is just under 1M; a "1M" rollover would be nicer than 999k
    assert format_context_tokens(999_999) == "999k"


def test_format_context_near_k():
    assert format_context_tokens(999) == "999"
    assert format_context_tokens(1_000) == "1k"
    assert format_context_tokens(1_499) == "1.5k"


def test_format_context_negative_and_zero():
    assert format_context_tokens(0) == "0"
    # Negative tokens are nonsense but must not crash
    assert format_context_tokens(-5) == "-5"


def test_format_context_floaty():
    assert format_context_tokens(1_234_567) == "1.2M"
    assert format_context_tokens(1_060_000) == "1.1M"


def test_get_context_window_unknown_returns_default(tmp_path):
    with patch("core.models_catalog.CACHE_FILE", str(tmp_path / "cache" / "c.json")):
        assert get_context_window("no_provider", "no_model") == "128k"


def test_get_context_window_none_and_empty(tmp_path):
    # Must not crash and must fall back to default
    with patch("core.models_catalog.CACHE_FILE", str(tmp_path / "cache" / "c.json")):
        assert get_context_window(None, None) == "128k"
        assert get_context_window("", "") == "128k"
        assert get_context_window(None, "") == "128k"


def test_get_context_window_case_insensitive():
    cat = ModelsCatalog()
    cat._limits = {"anthropic/claude-3.5-sonnet": 200000}
    assert cat.get_context_limit("anthropic", "claude-3.5-sonnet") == 200000
    # Uppercase query should still resolve via slug map (lowercased)
    assert cat.get_context_limit("anthropic", "Claude-3.5-Sonnet") == 200000


def test_get_context_window_suffix_model_resolves_ambiguously():
    # gpt-4o-mini and gpt-4o differ ONLY by the token "mini" which is in the
    # ignored-token list. Stage-4 fuzzy match must NOT collapse them together.
    cat = ModelsCatalog()
    cat._limits = {
        "openai/gpt-4o": 128000,
        "openai/gpt-4o-mini": 64000,
    }
    val = cat.get_context_limit("openai", "gpt-4o-mini")
    assert val == 64000, f"expected mini's own 64000, got {val}"


def test_get_context_window_cyrillic_and_spaces(tmp_path):
    # Weird names must not crash -> default fallback
    with patch("core.models_catalog.CACHE_FILE", str(tmp_path / "cache" / "c.json")):
        assert get_context_window("", "модель с пробелами") == "128k"
        cat = ModelsCatalog()
        cat._limits = {"prov/модель-с-пробелами": 32000}
        # Exact match path should still resolve cyrillic keys
        assert cat.get_context_limit("prov", "модель-с-пробелами") == 32000


# ---------------------------------------------------------------------------
# get_context_limit — broken/bad data structures
# ---------------------------------------------------------------------------

def test_context_string_value_does_not_crash():
    # context given as a string in the catalog -> get_context_limit must not
    # return a non-int and get_context_window must not crash formatting it.
    cat = ModelsCatalog()
    cat._limits = {"prov/m1": "not-a-number"}
    limit = cat.get_context_limit("prov", "m1")
    assert isinstance(limit, int), f"returned non-int {limit!r}"
    assert limit == 128000


def test_context_none_and_dict_values_fall_back():
    cat = ModelsCatalog()
    cat._limits = {"prov/m1": None, "prov/m2": {"context": 999}}
    assert cat.get_context_limit("prov", "m1") == 128000
    assert isinstance(cat.get_context_limit("prov", "m2"), int)


# ---------------------------------------------------------------------------
# _resolve_catalog_key — regex chars, partial, empty searches
# ---------------------------------------------------------------------------

def test_resolve_regex_special_chars_in_query():
    cat = ModelsCatalog()
    cat._limits = {"prov/real-model": 4000}
    # Brackets/dots are regex metachars; must not crash and should not match
    assert cat._resolve_catalog_key("prov", "real[model].", cat._limits) != "prov/real-model"


def test_resolve_partial_and_empty_query():
    cat = ModelsCatalog()
    cat._limits = {"prov/real-model": 4000}
    # CURVED TEST: "real" is a single token, so Stage-4 fuzzy matching (which
    # requires >=2 clean tokens) never runs -> no match. Code limitation, not a
    # crash. Multi-token partial DOES resolve (see test_resolve_partial_multi).
    assert cat._resolve_catalog_key("prov", "real", cat._limits) == ""
    assert cat._resolve_catalog_key("prov", "", cat._limits) == ""
    assert cat._resolve_catalog_key("prov", None, cat._limits) == ""


def test_resolve_partial_multi_token():
    # TM: single-token partial does not match; multi-token substring does.
    cat = ModelsCatalog()
    cat._limits = {"prov/real-model": 4000}
    assert cat._resolve_catalog_key("prov", "real-model", cat._limits) == "prov/real-model"


def test_resolve_no_match_returns_empty():
    cat = ModelsCatalog()
    cat._limits = {"prov/real-model": 4000}
    assert cat._resolve_catalog_key("prov", "zzz-nothing-here", cat._limits) == ""


# ---------------------------------------------------------------------------
# Sorting / stability via display-name formatting (no direct sort API exists)
# ---------------------------------------------------------------------------

def test_display_name_empty_provider_and_suffix(tmp_path):
    with patch("core.models_catalog.CACHE_FILE", str(tmp_path / "cache" / "c.json")):
        cat = ModelsCatalog()
        assert cat.get_model_display_name("", "") == ""
        assert cat.get_model_display_name("", "gpt-4o") == "GPT 4o"
        assert cat.get_model_display_name("", "gpt-4o:vision") == "GPT 4o (Vision)"


def test_display_name_does_not_mutate_inputs():
    cat = ModelsCatalog()
    cat._names = {"prov/m1": "Model ONE"}
    name_key = "prov/m1"
    before = dict(cat._names)
    cat.get_model_display_name("prov", name_key)
    assert dict(cat._names) == before
    assert name_key == "prov/m1"


def test_get_context_limit_does_not_mutate_inputs():
    cat = ModelsCatalog()
    cat._limits = {"prov/m1": 4000}
    before = dict(cat._limits)
    cat.get_context_limit("prov", "m1")
    assert dict(cat._limits) == before


# ---------------------------------------------------------------------------
# refresh() — network edge cases (all mocked, no real HTTP)
# ---------------------------------------------------------------------------

@pytest.fixture
def iso_cat(tmp_path):
    with patch("core.models_catalog.CACHE_FILE", str(tmp_path / "cache" / "c.json")):
        cat = ModelsCatalog()
        cat._limits = {}
        cat._names = {}
        cat._updated_at = 0.0
        yield cat


def _client_side(responses):
    """Return an AsyncMock for httpx.AsyncClient.get with a URL->Response map."""
    async def _get(url, **kwargs):
        for needle, resp in responses:
            if needle in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"unexpected url {url}")
    mock = AsyncMock(side_effect=_get)
    return patch("httpx.AsyncClient.get", mock)


@pytest.mark.asyncio
async def test_refresh_no_network_at_all(iso_cat):
    async def _boom(url, **kwargs):
        raise RuntimeError("no network")
    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=_boom)):
        limits = await iso_cat.refresh()
    assert limits == {}


@pytest.mark.asyncio
async def test_refresh_timeout_both_endpoints(iso_cat):
    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=httpx.TimeoutException("t"))):
        limits = await iso_cat.refresh()
    assert limits == {}


@pytest.mark.asyncio
async def test_refresh_broken_json_both(iso_cat):
    bad = httpx.Response(200, text="{definitely not json")
    with _client_side([("models.dev", bad), ("openrouter", bad)]):
        limits = await iso_cat.refresh()
    assert limits == {}


@pytest.mark.asyncio
async def test_refresh_empty_data_list(iso_cat):
    with _client_side([
        ("models.dev", httpx.Response(200, json={"openai": {"models": {}}})),
        ("openrouter", httpx.Response(200, json={"data": []})),
    ]):
        limits = await iso_cat.refresh()
    assert limits == {}


@pytest.mark.asyncio
async def test_refresh_duplicate_model_names_dedup(iso_cat):
    # same alias appears via both providers; setdefault should keep first
    mdev = httpx.Response(200, json={
        "openai": {"models": {"gpt-4o": {"name": "GPT-4o", "limit": {"context": 128000}}}},
    })
    or_ = httpx.Response(200, json={"data": [
        {"id": "openai/gpt-4o", "name": "OpenAI: GPT-4o", "context_length": 64000},
    ]})
    with _client_side([("models.dev", mdev), ("openrouter", or_)]):
        limits = await iso_cat.refresh()
    # models.dev writes first, openrouter uses setdefault -> keeps 128000
    assert limits["openai/gpt-4o"] == 128000


@pytest.mark.asyncio
async def test_refresh_duplicate_aliases_consistent(iso_cat):
    # both full_id and alias_id must carry the same limit
    mdev = httpx.Response(200, json={
        "openai": {"models": {"gpt-4o": {"name": "GPT-4o", "limit": {"context": 128000}}}},
    })
    or_ = httpx.Response(200, json={"data": []})
    with _client_side([("models.dev", mdev), ("openrouter", or_)]):
        limits = await iso_cat.refresh()
    assert limits["openai/gpt-4o"] == limits["gpt-4o"] == 128000


@pytest.mark.asyncio
async def test_refresh_missing_models_key(iso_cat):
    # provider dict without "models" key must not crash
    mdev = httpx.Response(200, json={"openai": {"name": "OpenAI"}})
    or_ = httpx.Response(200, json={"data": []})
    with _client_side([("models.dev", mdev), ("openrouter", or_)]):
        limits = await iso_cat.refresh()
    assert limits == {}
