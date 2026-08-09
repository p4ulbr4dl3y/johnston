import inspect
from typing import Any, Dict, Type

from tools.ask_user import AskUserTool
from tools.base import BaseTool, format_tool_error
from tools.call_mcp import CallMCPTool
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
    CallMCPTool,
    ManageShellTool,
    InvokeSubagentTool,
    ManageSubagentTool,
    UpdatePlanTool,
    WebFetchTool,
]

REGISTRY: Dict[str, Type[BaseTool]] = {cls.name.lower(): cls for cls in TOOL_CLASSES}

from tools.aliases import ALIAS_MAP, PARAM_ALIAS_MAP  # noqa: E402  (re-export for downstream imports)


def normalize_tool_name(name: str) -> str:
    """Normalizes a tool name or alias to its canonical name using ALIAS_MAP."""
    if not name:
        return ""
    clean = name.strip().lower()
    if clean in REGISTRY:
        return clean
    return ALIAS_MAP.get(clean, clean)


def normalize_tool_args(tool_name: str, args: dict | None) -> Dict[str, Any]:
    """Normalizes tool argument names to canonical names using PARAM_ALIAS_MAP."""
    if not args or not isinstance(args, dict):
        return {}

    clean_name = (tool_name or "").strip().lower()
    resolved_name = clean_name if clean_name in REGISTRY else ALIAS_MAP.get(clean_name, clean_name)
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
        chunk_aliases = {
            "target_content": "old_str",
            "TargetContent": "old_str",
            "old_content": "old_str",
            "search": "old_str",
            "oldStr": "old_str",
            "old": "old_str",
            "replacement_content": "new_str",
            "ReplacementContent": "new_str",
            "new_content": "new_str",
            "replace": "new_str",
            "newStr": "new_str",
            "new": "new_str",
            "start_line": "start_line",
            "StartLine": "start_line",
            "start": "start_line",
            "end_line": "end_line",
            "EndLine": "end_line",
            "end": "end_line",
            "allow_multiple": "allow_multiple",
            "multiple": "allow_multiple",
        }
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
    """Shows the PermissionConfirmScreen and applies session overrides for confirmed tools.

    Returns True if the user granted access ('allow' or 'always_allow'), False otherwise.
    Handles the 'always_allow' result by setting the corresponding session override(s).
    Supports both `push_screen_wait` (async) and `push_screen` + callback (sync-style) hosts.
    """
    from core.permission_manager import PermissionManager
    from widgets.screens.permission_confirm import PermissionConfirmScreen
    pm = PermissionManager.get_instance()
    screen = PermissionConfirmScreen(tool_name=screen_name, args=args, reason=reason)

    result = None
    if hasattr(app_obj, "push_screen_wait"):
        try:
            result = await app_obj.push_screen_wait(screen)
        except TypeError:
            # Host only exposes push_screen (e.g. MagicMock in tests)
            result = None

    if result is None:
        import asyncio
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def on_dismiss(r: Any) -> None:
            if not future.done():
                future.set_result(r)

        app_obj.push_screen(screen, callback=on_dismiss)
        result = await future

    if result == "always_allow":
        if perm_name:
            pm.set_session_override(perm_name, "allow")
        if perm_name == "shell":
            pm.set_session_override("shell_guard", "allow")
    return result in ("allow", "always_allow")


async def check_and_confirm_permission(
    target_perm_name: str,
    display_name: str,
    args: Dict[str, Any],
    context_or_app: Any,
    confirm_tool_name: str | None = None,
) -> str | None:
    """
    Checks tool permissions via PermissionManager and prompts user if confirmation is required.
    Returns None if allowed, or error message string if denied/cancelled.
    """
    from core.permission_manager import PermissionManager
    pm = PermissionManager.get_instance()
    if hasattr(context_or_app, "push_screen_wait"):
        app_obj = context_or_app
    else:
        app_obj = getattr(context_or_app, "app", context_or_app)
    project_dir = (
        getattr(context_or_app, "cwd", None)
        or getattr(context_or_app, "project_dir", None)
        or getattr(app_obj, "project_dir", None)
    )
    action, reason = pm.check_permission(target_perm_name, args, project_dir=project_dir)

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
    resolved_name = clean_name if clean_name in REGISTRY else ALIAS_MAP.get(clean_name, clean_name)
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
        res_or_coro = mcp_mgr.get_active_tools_async(mode=None)
        active_mcp_tools = await res_or_coro if inspect.isawaitable(res_or_coro) else res_or_coro
    else:
        active_mcp_tools = mcp_mgr.get_active_tools(mode=None) or []
    is_mcp = any(t.get("function", {}).get("name") == name for t in active_mcp_tools) or bool(mcp_mgr.get_capabilities_for_exposed_tool(name))

    if not is_mcp:
        import difflib
        all_candidates = set(REGISTRY.keys()) | set(ALIAS_MAP.keys())
        matches = difflib.get_close_matches(clean_name, sorted(all_candidates), n=2, cutoff=0.4)
        hint = ""
        if matches:
            resolved_target = ALIAS_MAP.get(matches[0], matches[0])
            desc_str = f" (target: {resolved_target})" if resolved_target != matches[0] else ""
            hint = f" [Hint: Did you mean '{matches[0]}'{desc_str}?]"
        return format_tool_error("unknown", detail=hint.strip(), name=name)

    from core.role_registry import RoleRegistry, role_tool_error

    ctx_or_app = context or app
    app_obj = getattr(ctx_or_app, "app", ctx_or_app)
    mode = getattr(app_obj, "mode", "act") if app_obj is not None else "act"
    role_def = RoleRegistry.get_instance().get_role(str(mode).lower())
    policy_err = role_tool_error(role_def, clean_name) or role_tool_error(role_def, resolved_name)
    if policy_err:
        return policy_err

    err = await check_and_confirm_permission("call_mcp", name, args, ctx_or_app, confirm_tool_name=f"mcp:{name}")
    if err:
        return err

    try:

        if not type(mcp_mgr).__name__.endswith("Mock") and hasattr(mcp_mgr, "call_tool_async"):
            res_or_coro = mcp_mgr.call_tool_async(name, args)
        else:
            res_or_coro = mcp_mgr.call_tool(name, args)
        mcp_res = await res_or_coro if inspect.isawaitable(res_or_coro) else res_or_coro
        if mcp_res is not None:
            return mcp_res
    except Exception as e:
        return format_tool_error("mcp", detail=str(e), name=name)

    return format_tool_error("unknown", name=name)
