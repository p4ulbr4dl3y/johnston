import difflib
import inspect
import logging
import time
from typing import Any, Dict, Type

from core.domain.defaults.errors import ToolResult, normalize_tool_result
from core.infrastructure.runtime.tool_name import normalize_tool_name
from tools.ask_user import AskUserTool
from tools.base import BaseTool, _resolve_app
from tools.create import CreateTool
from tools.edit import EditTool
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
    ShellTool,
    AskUserTool,
    ManageShellTool,
    InvokeSubagentTool,
    ManageSubagentTool,
    UpdatePlanTool,
    WebFetchTool,
]

REGISTRY: Dict[str, Type[BaseTool]] = {cls.name.lower(): cls for cls in TOOL_CLASSES}

logger = logging.getLogger(__name__)


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


# Negative-lookup cache: a full MCP listing that already failed to find a tool
# name is remembered briefly so a hallucinated name (LLM-invented) can't spawn
# every MCP server on every agent turn. Bounded and TTL-expiring.
_MCP_MISS_TTL = 30.0
_MCP_MISS_MAX = 512
_mcp_name_misses: Dict[str, float] = {}


def _mcp_name_recently_missed(name: str) -> bool:
    """True if a full MCP listing recently failed to find ``name``."""
    ts = _mcp_name_misses.get(name)
    if ts is None:
        return False
    if time.time() - ts > _MCP_MISS_TTL:
        _mcp_name_misses.pop(name, None)
        return False
    return True


def _remember_mcp_miss(name: str) -> None:
    if len(_mcp_name_misses) >= _MCP_MISS_MAX:
        _mcp_name_misses.clear()
    _mcp_name_misses[name] = time.time()


def _forget_mcp_miss(name: str) -> None:
    _mcp_name_misses.pop(name, None)


def _unknown_tool_result(name: str, clean_name: str) -> ToolResult:
    """Build the 'unknown tool' error, with a close-match suggestion when available."""
    matches = difflib.get_close_matches(clean_name, _close_match_candidates(), n=2, cutoff=0.4)
    hint = ""
    if matches:
        hint = f" Did you mean '{matches[0]}'?"
    return ToolResult.error("unknown", detail=hint.strip(), name=name)


def get_default_tools() -> list[Dict[str, Any]]:
    tools = []
    for cls in TOOL_CLASSES:
        if getattr(cls, "schema", None):
            try:
                inst = _get_tool_instance(cls)
                tools.append(inst.get_schema())
            except Exception:
                tools.append(cls.schema)
    return tools


async def check_and_confirm_permission(
    target_perm_name: str,
    display_name: str,
    args: Dict[str, Any],
    context_or_app: Any,
    confirm_tool_name: str | None = None,
) -> ToolResult | None:
    """
    Checks tool permissions via PermissionManager and prompts user if confirmation is required.
    Returns None if allowed, or an error ToolResult if denied/cancelled.
    """
    from core.domain.policies.permission_policy import PermissionAction
    from core.permission_manager import PermissionManager
    from tools.base import confirm_permission, resolve_subagent_identity

    pm = PermissionManager.get_instance()
    app_obj = _resolve_app(context_or_app)
    decision = pm.check_permission(target_perm_name, args)

    if decision.action == PermissionAction.DENY:
        return ToolResult.error("denied", name=display_name, detail="by permission policy")
    elif decision.action == PermissionAction.ASK:
        is_sub, sub_role = resolve_subagent_identity(context_or_app, app_obj)
        if app_obj and (hasattr(app_obj, "push_screen_wait") or callable(getattr(app_obj, "confirm_permission", None))):
            screen_name = confirm_tool_name or target_perm_name
            confirmed = await confirm_permission(
                screen_name,
                args,
                decision.reason,
                target_perm_name,
                ctx_or_app=context_or_app or app_obj,
                is_subagent=is_sub,
                subagent_role=sub_role,
            )
            if isinstance(confirmed, str) and confirmed.startswith("deny:"):
                user_reason = confirmed.split(":", 1)[1].strip()
                return ToolResult.error("denied", name=display_name, detail=f"by user ({user_reason})")
            elif not confirmed:
                return ToolResult.error("denied", name=display_name, detail="by user")
        else:
            return ToolResult.error(
                "denied", name=display_name, detail=f"requires user confirmation ({decision.reason})"
            )
    return None


_TOOL_INSTANCES: Dict[Type[BaseTool], BaseTool] = {}


def _get_tool_instance(tool_cls: Type[BaseTool]) -> BaseTool:
    """Get or create singleton tool instance."""
    inst = _TOOL_INSTANCES.get(tool_cls)
    if inst is None:
        inst = tool_cls()
        _TOOL_INSTANCES[tool_cls] = inst
    return inst


async def aclose_tools() -> None:
    """Clean up and close persistent resources held by cached tool instances."""
    for inst in list(_TOOL_INSTANCES.values()):
        if hasattr(inst, "aclose"):
            try:
                res = inst.aclose()
                if inspect.isawaitable(res):
                    await res
            except Exception:
                pass
    _TOOL_INSTANCES.clear()


async def execute_tool(name: str, args: dict | None, app: Any = None, context: Any = None) -> ToolResult:
    raw_name = (name or "").strip()
    clean_name = raw_name.lower()
    resolved_name = normalize_tool_name(raw_name)

    tool_cls = REGISTRY.get(resolved_name)
    if tool_cls:
        try:
            tool_inst = _get_tool_instance(tool_cls)
            ctx = tool_inst._ensure_context(context or app)

            err = await check_and_confirm_permission(resolved_name, name, args, context or app)
            if err:
                return err

            return await normalize_tool_result(tool_inst.execute(args, ctx))
        except Exception as e:
            logger.warning("Tool '%s' execution failed: %s", name, e, exc_info=True)
            return ToolResult.error("execute", detail=str(e), name=name)

    from core.infrastructure.mcp import get_mcp_manager

    mcp_mgr = get_mcp_manager()

    # Fast path: a known MCP tool must not re-warm every server (spawning npx)
    # just to confirm the name. Check the already-discovered cached tools first;
    # only fall back to a full active listing when the name isn't cached (cold
    # server not yet warmed up).
    active_mcp_tools: list = []
    try:
        cached_tools = mcp_mgr.get_cached_tools() if hasattr(mcp_mgr, "get_cached_tools") else []
        if isinstance(cached_tools, list):
            active_mcp_tools = cached_tools
    except Exception as e:
        logger.warning("MCP cached tools read failed: %s", e, exc_info=True)
        return ToolResult.error("mcp", detail=f"failed to read cached tools: {e}", name=name)
    # Case-insensitive match on the canonical (stripped+lowercased) name so the
    # MCP lookup follows the same normalization rules as builtin dispatch.
    is_mcp = any((t.get("function", {}).get("name") or "").lower() == clean_name for t in active_mcp_tools)

    if not is_mcp:
        # Short-circuit: only check the capability lookup when the name wasn't
        # found among cached tools. Kept outside the listing try so its failure
        # is reported distinctly and not confused with transport listing errors.
        try:
            if hasattr(mcp_mgr, "get_capabilities_for_exposed_tool") and mcp_mgr.get_capabilities_for_exposed_tool(name):
                is_mcp = True
        except Exception as e:
            logger.warning("MCP capability resolution failed for '%s': %s", name, e, exc_info=True)
            return ToolResult.error("mcp", detail=f"failed to resolve capabilities: {e}", name=name)

    if not is_mcp:
        # Full listing fallback: starts/refreshes servers that cache misses
        # could not cover (e.g. very first call before any warmup ran). A name
        # that already failed a full listing very recently is skipped: re-listing
        # would spawn every server just to confirm a hallucinated tool name.
        if _mcp_name_recently_missed(name):
            return _unknown_tool_result(name, clean_name)
        try:
            if hasattr(mcp_mgr, "get_active_tools_async"):
                res_or_coro = mcp_mgr.get_active_tools_async()
                listed_tools = await res_or_coro if inspect.isawaitable(res_or_coro) else res_or_coro
            elif hasattr(mcp_mgr, "get_active_tools"):
                listed_tools = mcp_mgr.get_active_tools() or []
            else:
                listed_tools = []
            if listed_tools:
                active_mcp_tools = list(listed_tools)
            is_mcp = any((t.get("function", {}).get("name") or "").lower() == clean_name for t in active_mcp_tools)
            if is_mcp:
                _forget_mcp_miss(name)
            else:
                _remember_mcp_miss(name)
        except Exception as e:
            logger.warning("MCP active tools listing failed: %s", e, exc_info=True)
            return ToolResult.error("mcp", detail=f"failed to list active tools: {e}", name=name)

    if not is_mcp:
        return _unknown_tool_result(name, clean_name)

    from tools.base import check_mcp_role_policy

    ctx_or_app = context or app
    policy_err = check_mcp_role_policy(ctx_or_app, resolved_name)
    if policy_err:
        return policy_err

    # Determine the exposed MCP tool name (namespaced as "server__tool" on name
    # collisions) so permissions are stored and checked under that name. The
    # comparison is case-insensitive, matching the lookup rules above.
    exposed_name = clean_name
    target_entry = None
    for t in active_mcp_tools:
        fn_name = t.get("function", {}).get("name")
        if fn_name is not None and fn_name.lower() == clean_name:
            exposed_name = fn_name
            target_entry = t
            break

    perm_err = await check_and_confirm_permission(exposed_name, name, args, ctx_or_app)
    if perm_err:
        return perm_err

    try:
        from tools.base import MAX_TOOL_OUTPUT_CHARS, execute_mcp_tool, truncate_output

        # Execute against the exact server that owns the permission-checked
        # exposed name, so the permission decision and the executed tool can
        # never diverge on a name collision.
        target_server = target_entry.get("_mcp_server") if isinstance(target_entry, dict) else None
        mcp_res = await execute_mcp_tool(mcp_mgr, name, args, target_server=target_server)
        if mcp_res is not None:
            tool_res = await normalize_tool_result(mcp_res)
            if not tool_res.is_error and tool_res.content and len(tool_res.content) > MAX_TOOL_OUTPUT_CHARS:
                tool_res.content = truncate_output(
                    tool_res.content,
                    max_chars=MAX_TOOL_OUTPUT_CHARS,
                    tool_name=name,
                )
            return tool_res
    except Exception as e:
        logger.warning("MCP tool '%s' execution failed: %s", name, e, exc_info=True)
        return ToolResult.error("mcp", detail=str(e), name=name)

    return ToolResult.error("unknown", name=name)
