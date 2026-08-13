import inspect
from typing import Any, Dict, Type

from tools.ask_user import AskUserTool
from tools.base import BaseTool, format_tool_error
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

from tools.aliases import (  # noqa: E402  # re-export for downstream imports
    ALIAS_MAP,
    EDIT_CHUNK_ALIAS_MAP,
    PARAM_ALIAS_MAP,
)


def _build_close_match_candidates() -> list[str]:
    """Sorted list of all tool/alias names used for fuzzy-matching unknown tools."""
    return sorted(set(REGISTRY.keys()) | set(ALIAS_MAP.keys()))


# Precomputed candidate list for fuzzy tool-name suggestions. Rebuilt lazily if the
# registry changes after import (e.g. dynamic tool registration in tests).
_CLOSE_MATCH_CANDIDATES: list[str] = _build_close_match_candidates()


def _close_match_candidates() -> list[str]:
    """Return the cached candidate list, invalidating it if REGISTRY/ALIAS_MAP grew."""
    if len(_CLOSE_MATCH_CANDIDATES) == len(REGISTRY) + len(ALIAS_MAP):
        return _CLOSE_MATCH_CANDIDATES
    _CLOSE_MATCH_CANDIDATES[:] = _build_close_match_candidates()
    return _CLOSE_MATCH_CANDIDATES


def normalize_tool_name(name: str) -> str:
    """Normalizes a tool name or alias to its canonical name using ALIAS_MAP.

    Resolves alias chains recursively (guard against cycles) and maps empty/None
    alias values back to the requested name instead of returning a dead value.
    """
    if not name:
        return ""
    clean = name.strip().lower()
    seen: set[str] = set()
    while clean not in REGISTRY and clean in ALIAS_MAP:
        if clean in seen:
            break
        seen.add(clean)
        target = ALIAS_MAP.get(clean)
        if not isinstance(target, str) or not target.strip():
            break
        clean = target.strip().lower()
    return clean


def normalize_tool_args(tool_name: str, args: dict | None) -> Dict[str, Any]:
    """Normalizes tool argument names to canonical names using PARAM_ALIAS_MAP."""
    if not args or not isinstance(args, dict):
        return {}

    resolved_name = normalize_tool_name(tool_name)
    param_aliases = PARAM_ALIAS_MAP.get(resolved_name, {})

    normalized = dict(args)
    for k, v in list(args.items()):
        canon_key = k
        if k not in param_aliases:
            # Case-insensitive fallback (e.g. PascalCase -> lowercase)
            canon_key = k.lower()
        if canon_key in param_aliases:
            canonical = param_aliases[canon_key]
            if canonical not in normalized or normalized[canonical] is None:
                normalized[canonical] = v

    if resolved_name in ("multi_edit", "edit") and isinstance(normalized.get("edits"), list):
        chunk_aliases = EDIT_CHUNK_ALIAS_MAP
        normalized_edits = []
        for chunk in normalized["edits"]:
            if isinstance(chunk, dict):
                c_norm = dict(chunk)
                for ck, cv in list(chunk.items()):
                    ck_l = ck[0].lower() + ck[1:] if ck else ck
                    if ck in chunk_aliases:
                        canon_c = chunk_aliases[ck]
                    elif ck_l in chunk_aliases:
                        canon_c = chunk_aliases[ck_l]
                    else:
                        continue
                    if canon_c not in c_norm or c_norm[canon_c] is None:
                        c_norm[canon_c] = cv
                normalized_edits.append(c_norm)
            else:
                normalized_edits.append(chunk)
        normalized["edits"] = normalized_edits

    return normalized


def get_default_tools() -> list[Dict[str, Any]]:
    return [cls.schema for cls in TOOL_CLASSES if getattr(cls, "schema", None)]


async def prompt_permission_confirmation(
    app_obj: Any,
    screen_name: str,
    args: Dict[str, Any],
    reason: str,
    perm_name: str | None = None,
) -> bool:
    """Prompts the user for tool permission confirmation.

    Returns True if the user granted access ('allow' or 'always_allow'), False otherwise.
    Delegates to the host app's `confirm_permission` when available (UI hosts), and
    denies otherwise (headless/CLI mode) so the tools layer stays UI-independent.
    """
    confirm = getattr(app_obj, "confirm_permission", None)
    if callable(confirm):
        return await confirm(screen_name, args, reason, perm_name)

    return False


async def check_and_confirm_permission(
    target_perm_name: str,
    display_name: str,
    args: Dict[str, Any],
    context_or_app: Any,
    confirm_tool_name: str | None = None,
    *,
    action: str | None = None,
    action_reason: str = "",
) -> str | None:
    """
    Checks tool permissions via PermissionManager and prompts user if confirmation is required.
    Returns None if allowed, or error message string if denied/cancelled.

    When `action` is provided (e.g. a caller that already evaluated role
    policy), the PermissionManager check is skipped and the given action is used.
    """
    from core.permission_manager import PermissionManager

    pm = PermissionManager.get_instance()
    if hasattr(context_or_app, "push_screen_wait"):
        app_obj = context_or_app
    else:
        app_obj = getattr(context_or_app, "app", context_or_app)
    if action is not None:
        action, reason = action, action_reason
    else:
        action, reason = pm.check_permission(target_perm_name, args)

    if action == "deny":
        return format_tool_error("denied", name=display_name, detail="by permission policy")
    elif action == "ask":
        if app_obj and hasattr(app_obj, "push_screen_wait"):
            screen_name = confirm_tool_name or target_perm_name
            confirmed = await prompt_permission_confirmation(
                app_obj, screen_name, args, reason, perm_name=target_perm_name
            )
            if not confirmed:
                return format_tool_error("denied", name=display_name, detail="by user")
        else:
            return format_tool_error("denied", name=display_name, detail=f"requires user confirmation ({reason})")
    return None


async def execute_tool(name: str, args: dict | None, app: Any = None, context: Any = None) -> str:
    raw_name = (name or "").strip()
    clean_name = raw_name.lower()
    resolved_name = normalize_tool_name(raw_name)
    args = normalize_tool_args(resolved_name, args)

    tool_cls = REGISTRY.get(resolved_name)
    if tool_cls:
        try:
            tool_inst = tool_cls()
            ctx = tool_inst._ensure_context(context or app)

            err = await check_and_confirm_permission(resolved_name, name, args, context or app)
            if err:
                return err

            return await tool_inst.execute(args, ctx)
        except Exception as e:
            return format_tool_error("execute", detail=str(e), name=name)

    from core.mcp_manager import get_mcp_manager

    mcp_mgr = get_mcp_manager()

    # Check if the tool is an active MCP tool
    if hasattr(mcp_mgr, "get_active_tools_async") and not type(mcp_mgr).__name__.endswith("Mock"):
        res_or_coro = mcp_mgr.get_active_tools_async()
        active_mcp_tools = await res_or_coro if inspect.isawaitable(res_or_coro) else res_or_coro
    else:
        active_mcp_tools = mcp_mgr.get_active_tools() or []
    is_mcp = any(t.get("function", {}).get("name") == name for t in active_mcp_tools) or bool(
        mcp_mgr.get_capabilities_for_exposed_tool(name)
    )

    if not is_mcp:
        import difflib

        matches = difflib.get_close_matches(clean_name, _close_match_candidates(), n=2, cutoff=0.4)
        hint = ""
        if matches:
            resolved_target = ALIAS_MAP.get(matches[0], matches[0])
            desc_str = f" (target: {resolved_target})" if resolved_target != matches[0] else ""
            hint = f" [Hint: Did you mean '{matches[0]}'{desc_str}?]"
        return format_tool_error("unknown", detail=hint.strip(), name=name)

    from tools.base import check_mcp_role_policy

    ctx_or_app = context or app
    policy_err = check_mcp_role_policy(ctx_or_app, clean_name, [clean_name, resolved_name])
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
            return mcp_res
    except Exception as e:
        return format_tool_error("mcp", detail=str(e), name=name)

    return format_tool_error("unknown", name=name)
