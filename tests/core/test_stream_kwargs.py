"""Unit tests for the shared ``build_stream_kwargs`` helper.

This helper centralizes construction of the ``adapter.stream_chat(**kwargs)``
dict that was previously duplicated across the agent loop, compaction and
auto-titling.
"""

from types import SimpleNamespace

from core.infrastructure.adapters.base import build_stream_kwargs


def _agent(**overrides):
    attrs = {
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-test",
        "model": "gpt-4o",
        "api_type": "openai",
        "headers": {"X-Custom": "1"},
        "extra_body": {"temperature": 0.7},
        "_client": None,
        "thinking_effort": None,
        "chunk_timeout": 30.0,
        "provider_key": "openai",
        "max_tokens": 8192,
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


def test_builds_base_keys():
    messages = [{"role": "user", "content": "hi"}]
    kwargs = build_stream_kwargs(_agent(), messages=messages, max_tokens=256)
    assert kwargs["base_url"] == "https://api.example.com/v1"
    assert kwargs["api_key"] == "sk-test"
    assert kwargs["model"] == "gpt-4o"
    assert kwargs["messages"] is messages
    assert kwargs["max_tokens"] == 256
    assert kwargs["headers"] == {"X-Custom": "1"}
    assert kwargs["extra_body"] == {"temperature": 0.7}
    # openai agent has no client set -> not forwarded
    assert "client" not in kwargs


def test_client_forwarded_for_openai_with_client():
    client = object()
    kwargs = build_stream_kwargs(_agent(_client=client), messages=[], max_tokens=1)
    assert kwargs["client"] is client


def test_client_not_forwarded_for_non_openai_by_default():
    kwargs = build_stream_kwargs(_agent(api_type="anthropic", _client=object()), messages=[], max_tokens=1)
    assert "client" not in kwargs


def test_openai_client_disabled_forwards_any_client():
    client = object()
    kwargs = build_stream_kwargs(
        _agent(api_type="anthropic", _client=client), messages=[], max_tokens=1, openai_client=False
    )
    assert kwargs["client"] is client


def test_tools_and_overrides_are_merged():
    tools = [{"type": "function", "function": {"name": "f"}}]
    kwargs = build_stream_kwargs(
        _agent(),
        messages=[],
        max_tokens=1,
        tools=tools,
        thinking_effort="high",
        chunk_timeout=15.0,
        provider_key="custom",
    )
    assert kwargs["tools"] is tools
    assert kwargs["thinking_effort"] == "high"
    assert kwargs["chunk_timeout"] == 15.0
    assert kwargs["provider_key"] == "custom"


def test_model_override_wins():
    kwargs = build_stream_kwargs(_agent(), messages=[], max_tokens=1, model="claude-3-5-haiku")
    assert kwargs["model"] == "claude-3-5-haiku"


def test_tools_none_and_empty_headers_are_omitted():
    kwargs = build_stream_kwargs(_agent(headers={}, extra_body={}), messages=[], max_tokens=1)
    assert "tools" not in kwargs
    assert "headers" not in kwargs
    assert "extra_body" not in kwargs
