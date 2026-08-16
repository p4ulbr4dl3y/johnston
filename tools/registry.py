import inspect
import json
from typing import Any, Dict, Type

from core.domain.defaults.errors import ToolResult
from tools.ask_user import AskUserTool
from tools.base import BaseTool, _resolve_app
from tools.create import CreateTool
from tools.edit import EditTool, MultiEditTool
from tools.invoke_subagent import InvokeSubagentTool
from tools.manage_shell import ManageShellTool
from tools.manage_subagent import ManageSubagentTool
from tools.read import ReadTool
from tools.shell import ShellTool
from tools.update_plan import UpdatePlanTool
from tools.web_fetch import WebFetchTool

TOOL_CLASSES = [
    ReadTool,
    CreateTool,
    EditTool,
    MultiEditTool,
    ShellTool,
    AskUserTool,
    ManageShellTool,
    InvokeSubagentTool,
    ManageSubagentTool,
    UpdatePlanTool,
    WebFetchTool,
]

REGISTRY: Dict[str, Type[BaseTool]] = {cls.name.lower(): cls for cls in TOOL_CLASSES}


def _build_close_match_candidates() -> list[str]:
    """Sorted list of all tool names used for fuzzy-matching unknown tools."""
    return sorted(set(REGISTRY.keys()))


# Precomputed candidate list for fuzzy tool-name suggestions. Rebuilt lazily if the
# registry changes after import (e.g. dynamic tool registration in tests).
_CLOSE_MATCH_CANDIDATES: list[str] = _build_close_match_candidates()


def _close_match_candidates() -> list[str]:
    """Return the cached candidate list, invalidating it if REGISTRY grew."""
    if len(_CLOSE_MATCH_CANDIDATES) == len(REGISTRY):
        return _CLOSE_MATCH_CANDIDATES
    _CLOSE_MATCH_CANDIDATES[:] = _build_close_match_candidates()
    return _CLOSE_MATCH_CANDIDATES


def normalize_tool_name(name: str) -> str:
    """Normalizes a tool name for case/whitespace-insensitive dispatch.

    Strip + lowercase only. No alias resolution.
    """
    if not name:
        return ""
    return name.strip().lower()


def get_default_tools() -> list[Dict[str, Any]]:
    return [cls.schema for cls in TOOL_CLASSES if getattr(cls, "schema", None)]


async def prompt_permission_confirmation(
    app_obj: Any,
    screen_name: str,
    args: Dict[str, Any],
    reason: str,
    perm_name: str | None = None,
) -> bool:
    """Prompts the user for tool permission confirmation (backward-compat wrapper).

    Delegates to the shared tools.base.confirm_permission which resolves a host
    app via ``_resolve_app`` and denies otherwise (headless/CLI mode).
    """
    from tools.base import confirm_permission

    return await confirm_permission(screen_name, args, reason, perm_name, ctx_or_app=app_obj)


async def check_and_confirm_permission(
    target_perm_name: str,
    display_name: str,
    args: Dict[str, Any],
    context_or_app: Any,
    confirm_tool_name: str | None = None,
    *,
    action: str | None = None,
    action_reason: str = "",
) -> ToolResult | None:
    """
    Checks tool permissions via PermissionManager and prompts user if confirmation is required.
    Returns None if allowed, or an error ToolResult if denied/cancelled.

    When `action` is provided (e.g. a caller that already evaluated role
    policy), the PermissionManager check is skipped and the given action is used.
    """
    from core.permission_manager import PermissionManager

    pm = PermissionManager.get_instance()
    app_obj = _resolve_app(context_or_app)
    if action is not None:
        action, reason = action, action_reason
    else:
        action, reason = pm.check_permission(target_perm_name, args)

    if action == "deny":
        return ToolResult.error("denied", name=display_name, detail="by permission policy")
    elif action == "ask":
        if app_obj and hasattr(app_obj, "push_screen_wait"):
            screen_name = confirm_tool_name or target_perm_name
            confirmed = await prompt_permission_confirmation(
                app_obj, screen_name, args, reason, perm_name=target_perm_name
            )
            if not confirmed:
                return ToolResult.error("denied", name=display_name, detail="by user")
        else:
            return ToolResult.error(
                "denied", name=display_name, detail=f"requires user confirmation ({reason})"
            )
    return None


async def execute_tool(name: str, args: dict | None, app: Any = None, context: Any = None) -> ToolResult:
    raw_name = (name or "").strip()
    clean_name = raw_name.lower()
    resolved_name = normalize_tool_name(raw_name)

    tool_cls = REGISTRY.get(resolved_name)
    if tool_cls:
        try:
            tool_inst = tool_cls()
            ctx = tool_inst._ensure_context(context or app)

            err = await check_and_confirm_permission(resolved_name, name, args, context or app)
            if err:
                return err

            return await _wrap_execute(tool_inst.execute(args, ctx))
        except Exception as e:
            return ToolResult.error("execute", detail=str(e), name=name)

    from core.infrastructure.mcp import get_mcp_manager

    mcp_mgr = get_mcp_manager()

    from tools.base import is_mock_manager

    # Check if the tool is an active MCP tool
    try:
        if hasattr(mcp_mgr, "get_active_tools_async") and not is_mock_manager(mcp_mgr):
            res_or_coro = mcp_mgr.get_active_tools_async()
            active_mcp_tools = await res_or_coro if inspect.isawaitable(res_or_coro) else res_or_coro
        else:
            active_mcp_tools = mcp_mgr.get_active_tools() or []
        is_mcp = any(t.get("function", {}).get("name") == name for t in active_mcp_tools)
    except Exception as e:
        return ToolResult.error("mcp", detail=f"failed to list active tools: {e}", name=name)

    if not is_mcp:
        # Short-circuit: only check the capability lookup when the name wasn't
        # found among active tools. Kept outside the listing try so its failure
        # is reported distinctly and not confused with transport listing errors.
        try:
            if mcp_mgr.get_capabilities_for_exposed_tool(name):
                is_mcp = True
        except Exception as e:
            return ToolResult.error("mcp", detail=f"failed to resolve capabilities: {e}", name=name)

    if not is_mcp:
        import difflib

        matches = difflib.get_close_matches(clean_name, _close_match_candidates(), n=2, cutoff=0.4)
        hint = ""
        if matches:
            hint = f" [Hint: Did you mean '{matches[0]}'?]"
        return ToolResult.error("unknown", detail=hint.strip(), name=name)

    from tools.base import check_mcp_role_policy

    ctx_or_app = context or app
    policy_err = check_mcp_role_policy(ctx_or_app, resolved_name)
    if policy_err:
        return policy_err

    # Determine the exposed MCP tool name (namespaced as "server__tool" on name
    # collisions) so permissions are stored and checked under that name.
    exposed_name = clean_name
    for t in active_mcp_tools:
        fn_name = t.get("function", {}).get("name")
        if fn_name in (name, clean_name, resolved_name):
            exposed_name = fn_name
            break

    perm_err = await check_and_confirm_permission(exposed_name, name, args, ctx_or_app)
    if perm_err:
        return perm_err

    try:
        from tools.base import execute_mcp_tool

        mcp_res = await execute_mcp_tool(mcp_mgr, name, args)
        if mcp_res is not None:
            return await _wrap_execute(mcp_res)
    except Exception as e:
        return ToolResult.error("mcp", detail=str(e), name=name)

    return ToolResult.error("unknown", name=name)


async def _wrap_execute(result: Any) -> ToolResult:
    """Wrap a raw tool ``execute()`` result into a :class:`ToolResult`.

    Accepts one result value (already awaited) or an awaitable. Tools still
    return ``str``/``None``/dict etc.; any value already carrying the ``ERR:``
    convention is treated as an explicit error.
    """
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, ToolResult):
        return result
    if result is None:
        return ToolResult.done("")
    if isinstance(result, Exception):
        return ToolResult.error("execute", detail=str(result))
    if isinstance(result, (dict, list)):
        return ToolResult.done(json.dumps(result, ensure_ascii=False))
    text = str(result)
    if text.lstrip().lower().startswith("err:"):
        # Already carries the canonical ``ERR:`` convention - keep verbatim,
        # just mark it as an explicit error.
        return ToolResult(content=text, is_error=True, status="error")
    return ToolResult.done(text)
