"""Edge-case tests for core.prompt_builder.

Goal: find bugs in PromptBuilder / get_git_info / get_project_instructions_snippet /
get_rules_snippet under empty/None/long/unicode/duplicate/unsorted input, plus
consistency and mutation invariants.
"""
from unittest.mock import patch

import pytest

from core.prompt_builder import PromptBuilder, get_git_info, get_git_info_async, get_project_instructions_snippet


@pytest.fixture(autouse=True)
def _no_git_subprocess(monkeypatch):
    # Keep git subprocess deterministic/fast in edge tests.
    monkeypatch.setattr("core.prompt_builder._compute_git_info", lambda cwd=None: "")
    monkeypatch.setattr("core.prompt_builder.run_git", lambda *a, **k: None)


# ---------------------------------------------------------------------------
# __init__ / None inputs
# ---------------------------------------------------------------------------

def test_init_none_base_tools_does_not_crash():
    """base_tools=None should be tolerated (constructor already does `list(None or [])`)."""
    b = PromptBuilder("p", None)
    assert b.base_tools == []


def test_init_none_base_system_prompt():
    """None base_system_prompt must not crash build_system_prompt."""
    b = PromptBuilder(None, [], role="worker")
    # INTENT: docstring says "Builds composite system prompt" — a None text should
    # degrade to something, not crash. If this raises TypeError the implementation
    # does not honor the invariant (tools tolerate None, prompt does not).
    out = b.build_system_prompt()
    assert isinstance(out, str)


def test_init_none_role():
    b = PromptBuilder("p", [], role=None)
    assert b.role is None


def test_init_base_tools_non_list_iterable():
    """tuple/generator inputs should be accepted (list() coercion)."""
    b = PromptBuilder("p", ({"function": {"name": "read"}},))
    assert len(b.base_tools) == 1


# ---------------------------------------------------------------------------
# build_tools edge cases
# ---------------------------------------------------------------------------

def test_build_tools_empty_base():
    b = PromptBuilder("p", [], role="worker")
    tools = b.build_tools()
    assert isinstance(tools, list)


def test_build_tools_none_base():
    b = PromptBuilder("p", None, role="worker")
    tools = b.build_tools()
    assert isinstance(tools, list)


def test_build_tools_duplicate_names_preserved():
    """Duplicate tool names in base_tools should not be silently deduped/mutated."""
    base = [{"function": {"name": "dup"}}, {"function": {"name": "dup"}}]
    b = PromptBuilder("p", base, role="worker", allow_task=False)
    tools = b.build_tools()
    names = [t["function"]["name"] for t in tools]
    assert names.count("dup") == 2


def test_build_tools_no_function_key():
    """Tool dict without a 'function' key must not crash (name = '' => allowed)."""
    base = [{"type": "function"}]
    b = PromptBuilder("p", base, role="worker", allow_task=False)
    tools = b.build_tools()
    assert len(tools) == 1


def test_build_tools_non_dict_item_crash_probe():
    """A non-dict item in base_tools is malformed input.

    INTENT: `_tool_allowed` calls `tool_item.get(...)` so a bare string crashes
    with AttributeError. Documenting actual behavior; not a valid-input bug.
    """
    base = ["not_a_dict", {"function": {"name": "read"}}]
    b = PromptBuilder("p", base, role="worker", allow_task=False)
    with pytest.raises(AttributeError):
        b.build_tools()


def test_build_tools_function_not_dict_crash_probe():
    """function value that is not a dict (list/str) crashes in _tool_allowed.

    INTENT: `tool_item.get("function", {}).get("name", "")` — a list has no .get.
    """
    base = [{"function": []}]
    b = PromptBuilder("p", base, role="worker", allow_task=False)
    with pytest.raises(AttributeError):
        b.build_tools()


def test_build_tools_parameters_not_dict():
    """parameters as a non-dict (list) must not crash _sort_tool_schema."""
    base = [{"function": {"name": "weird", "parameters": ["x"]}}]
    b = PromptBuilder("p", base, role="worker", allow_task=False)
    tools = b.build_tools()
    assert len(tools) == 1


def test_build_tools_properties_not_dict():
    base = [{"function": {"name": "weird", "parameters": {"properties": []}}}]
    b = PromptBuilder("p", base, role="worker", allow_task=False)
    tools = b.build_tools()
    assert len(tools) == 1


def test_build_tools_required_not_list():
    base = [{"function": {"name": "weird", "parameters": {"required": "a"}}}]
    b = PromptBuilder("p", base, role="worker", allow_task=False)
    tools = b.build_tools()
    assert len(tools) == 1


def test_build_tools_required_sorts_strings_and_numbers():
    """required list mixing str/int must sort without crashing (py3 no mixed cmp)."""
    base = [{"function": {"name": "mix", "parameters": {"required": ["b", 2, "a", 1]}}}]
    b = PromptBuilder("p", base, role="worker", allow_task=False)
    tools = b.build_tools()
    assert len(tools) == 1


def test_build_tools_sorts_unicode_names():
    """Unicode/emoji tool names must sort and survive."""
    base = [
        {"function": {"name": "😀"}},
        {"function": {"name": "z_tool"}},
        {"function": {"name": "Абрикос"}},
    ]
    b = PromptBuilder("p", base, role="worker", allow_task=False)
    tools = b.build_tools()
    names = [t["function"]["name"] for t in tools]
    assert names == sorted(names)


def test_build_tools_does_not_mutate_base_tools():
    """build_tools must not mutate the caller's base_tools (deepcopy in sort)."""
    base = [
        {
            "function": {
                "name": "t",
                "parameters": {
                    "properties": {"z": {}, "a": {}},
                    "required": ["z", "a"],
                },
            }
        }
    ]
    b = PromptBuilder("p", base, role="worker", allow_task=False)
    b.build_tools()
    props = list(base[0]["function"]["parameters"]["properties"].keys())
    req = base[0]["function"]["parameters"]["required"]
    assert props == ["z", "a"]
    assert req == ["z", "a"]


def test_build_tools_deterministic_same_input():
    base = [
        {"function": {"name": "b", "parameters": {"properties": {"z": {}, "a": {}}}}},
        {"function": {"name": "a", "parameters": {"properties": {"y": {}, "m": {}}}}},
    ]
    b1 = PromptBuilder("p", list(base), role="worker", allow_task=False)
    b2 = PromptBuilder("p", list(base), role="worker", allow_task=False)
    assert b1.build_tools() == b2.build_tools()


def test_build_tools_subagent_excluded_tools():
    """Subagent must drop SUBAGENT_EXCLUDED_TOOLS (invoke_subagent etc)."""
    base = [
        {"function": {"name": "invoke_subagent"}},
        {"function": {"name": "ask_user"}},
        {"function": {"name": "read"}},
    ]
    b = PromptBuilder("p", base, role="worker", allow_task=False, is_subagent=True)
    names = [t["function"]["name"] for t in b.build_tools()]
    assert "invoke_subagent" not in names
    assert "ask_user" not in names
    assert "read" in names


_SUBAGENT_SCHEMA = {"type": "function", "function": {"name": "invoke_subagent"}}


def test_build_tools_no_duplicate_invoke_subagent_when_present():
    """If invoke_subagent already present, allow_task must not append a second."""
    base = [{"function": {"name": "invoke_subagent"}}]
    b = PromptBuilder("p", base, role="worker", allow_task=True)
    names = [t["function"]["name"] for t in b.build_tools()]
    assert names.count("invoke_subagent") == 1


def test_build_tools_float_allow_task_truthy():
    b = PromptBuilder("p", [], role="worker", allow_task=1.5, subagent_schema=_SUBAGENT_SCHEMA)
    names = [t["function"]["name"] for t in b.build_tools()]
    assert "invoke_subagent" in names


def test_build_tools_allow_task_zero_falsy():
    b = PromptBuilder("p", [], role="worker", allow_task=0)
    names = [t["function"]["name"] for t in b.build_tools()]
    assert "invoke_subagent" not in names


# ---------------------------------------------------------------------------
# build_system_prompt edge cases
# ---------------------------------------------------------------------------

def test_build_system_prompt_empty_string_base():
    b = PromptBuilder("", [], role="worker")
    out = b.build_system_prompt()
    assert isinstance(out, str)
    assert "## Environment Metadata" in out


def test_build_system_prompt_unicode_emoji_allowed():
    base = "Привет 😀 {model_name} {unknown_key} %s"
    b = PromptBuilder(base, [], role="worker", model_name="模型")
    out = b.build_system_prompt()
    assert "Привет 😀" in out
    assert "模型" in out
    # Unknown placeholders left as-is, no KeyError.
    assert "{unknown_key}" in out


def test_build_system_prompt_model_name_with_braces():
    """model_name containing braces must not break .replace()."""
    b = PromptBuilder("You are {model_name}", [], role="worker", model_name="{x}")
    out = b.build_system_prompt()
    assert "You are {x}" in out


def test_build_system_prompt_no_placeholder_untouched():
    b = PromptBuilder("no placeholder here", [], role="worker", model_name="whatever")
    out = b.build_system_prompt()
    assert out.startswith("no placeholder here")


def test_build_system_prompt_whitespace_model_name_falls_back():
    b = PromptBuilder("You are {model_name}", [], role="worker", model_name="   ")
    out = b.build_system_prompt()
    assert "an expert AI software engineer" in out


def test_build_system_prompt_environment_metadata_last():
    b = PromptBuilder("STABLE_PREFIX", [], role="worker")
    out = b.build_system_prompt()
    assert out.rindex("STABLE_PREFIX") < out.index("## Environment Metadata")


def test_build_system_prompt_deterministic_same_run():
    b1 = PromptBuilder("Base", [], role="worker")
    b2 = PromptBuilder("Base", [], role="worker")
    assert b1.build_system_prompt() == b2.build_system_prompt()


def test_build_system_prompt_subagent_no_role_prompt_injected():
    b = PromptBuilder("Base", [], role="orchestrator", is_subagent=True)
    out = b.build_system_prompt()
    assert "## Execution Mode: ORCHESTRATOR" not in out


# ---------------------------------------------------------------------------
# get_project_instructions_snippet edge cases
# ---------------------------------------------------------------------------

def test_project_snippet_none_cwd(tmp_path):
    with patch("os.getcwd", return_value=str(tmp_path)):
        out = get_project_instructions_snippet(None)
        assert isinstance(out, str)


def test_project_snippet_path_with_spaces_and_unicode(tmp_path):
    weird = tmp_path / "пап ка с пробелом 😀"
    weird.mkdir()
    (weird / "AGENTS.md").write_text("ВНИМАНИЕ: спец символы { %s }", encoding="utf-8")
    out = get_project_instructions_snippet(str(weird))
    assert "ВНИМАНИЕ" in out


def test_project_snippet_truncates_long(tmp_path):
    (tmp_path / "AGENTS.md").write_text("x" * 25000)
    out = get_project_instructions_snippet(str(tmp_path))
    assert "truncated at 20000" in out


def test_project_snippet_no_side_effect_on_cwd(tmp_path):
    (tmp_path / "AGENTS.md").write_text("hi")
    get_project_instructions_snippet(str(tmp_path))
    assert (tmp_path / "AGENTS.md").read_text() == "hi"


# ---------------------------------------------------------------------------
# get_git_info caching / branch formatting
# ---------------------------------------------------------------------------

def test_git_info_cached_short_circuits(monkeypatch):
    calls = []

    def fake_compute(cwd=None):
        calls.append(cwd)
        return "branch 'main'"

    monkeypatch.setattr("core.prompt_builder._compute_git_info", fake_compute)
    monkeypatch.setattr("core.prompt_builder._GIT_INFO_CACHE", {})
    a = get_git_info()
    b = get_git_info()
    assert a == b == "branch 'main'"
    assert len(calls) == 1  # cached, not recomputed twice


@pytest.mark.asyncio
async def test_git_info_async_cached(monkeypatch):
    calls = []

    def fake_compute(cwd=None):
        calls.append(cwd)
        return "branch 'dev'"

    # Patch the sync compute fn used inside get_git_info_async via to_thread;
    # count calls to prove the cache short-circuits the second call.
    monkeypatch.setattr("core.prompt_builder._compute_git_info", fake_compute)
    monkeypatch.setattr("core.prompt_builder._GIT_INFO_CACHE", {})
    a = await get_git_info_async()
    b = await get_git_info_async()
    assert a == b == "branch 'dev'"
    assert len(calls) == 1
