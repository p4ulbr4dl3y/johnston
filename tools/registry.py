import inspect
from typing import Any, Dict, Type

from tools.ask_user import AskUserTool
from tools.base import BaseTool
from tools.call_mcp import CallMCPTool
from tools.create import CreateTool
from tools.edit import EditTool, MultiEditTool
from tools.invoke_subagent import InvokeSubagentTool
from tools.manage_subagent import ManageSubagentTool
from tools.manage_task import ManageTaskTool
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
    ManageTaskTool,
    InvokeSubagentTool,
    ManageSubagentTool,
    UpdatePlanTool,
    WebFetchTool,
]

REGISTRY: Dict[str, Type[BaseTool]] = {cls.name.lower(): cls for cls in TOOL_CLASSES}

ALIAS_MAP: Dict[str, str] = {
    "write": "create",
    "write_file": "create",
    "create_file": "create",
    "save_file": "create",
    "write_to_file": "create",
    "touch": "create",
    "read_file": "read",
    "view_file": "read",
    "cat": "read",
    "read_file_content": "read",
    "edit_file": "edit",
    "replace_file_content": "edit",
    "multi_replace_file_content": "edit",
    "multi_edit": "edit",
    "subagent": "invoke_subagent",
    "spawn_subagent": "invoke_subagent",
    "run_subagent": "invoke_subagent",
    "call_mcp_tool": "call_mcp",
    "mcp": "call_mcp",
    "execute_mcp": "call_mcp",
    "update_file": "edit",
    "modify_file": "edit",
    "str_replace_editor": "edit",
    "replace": "edit",
    "multi_replace": "edit",
    "terminal": "shell",
    "exec": "shell",
    "run_command": "shell",
    "bash": "shell",
    "cmd": "shell",
    "run": "shell",
    "ask": "ask_user",
    "ask_question": "ask_user",
    "plan": "update_plan",
    "set_plan": "update_plan",
    "fetch": "web_fetch",
    "fetch_url": "web_fetch",
    "browse": "web_fetch",
    "task": "manage_task",
    "tasks": "manage_task",
    "kill_task": "manage_task",
    "subagents": "manage_subagent",
    "kill_subagent": "manage_subagent",
}


PARAM_ALIAS_MAP: Dict[str, Dict[str, str]] = {
    "shell": {
        "cmd": "command",
        "script": "command",
        "command_line": "command",
        "exec": "command",
        "time_limit": "timeout",
        "max_seconds": "timeout",
        "background": "run_in_background",
        "async": "run_in_background",
        "is_async": "run_in_background",
    },
    "read": {
        "file_path": "path",
        "filepath": "path",
        "file": "path",
        "filename": "path",
        "target_file": "path",
        "uri": "path",
        "url": "path",
        "start": "start_line",
        "startLine": "start_line",
        "from_line": "start_line",
        "line_start": "start_line",
        "end": "end_line",
        "endLine": "end_line",
        "to_line": "end_line",
        "line_end": "end_line",
        "offset": "content_offset",
        "contentOffset": "content_offset",
    },
    "create": {
        "path": "target_file",
        "file_path": "target_file",
        "filepath": "target_file",
        "file": "target_file",
        "filename": "target_file",
        "destination": "target_file",
        "content": "code",
        "text": "code",
        "contents": "code",
        "file_content": "code",
        "body": "code",
        "summary": "description",
        "desc": "description",
        "reason": "description",
    },
    "edit": {
        "path": "target_file",
        "file_path": "target_file",
        "filepath": "target_file",
        "file": "target_file",
        "filename": "target_file",
        "target_content": "old_str",
        "old_content": "old_str",
        "search": "old_str",
        "oldStr": "old_str",
        "old": "old_str",
        "replacement_content": "new_str",
        "new_content": "new_str",
        "replace": "new_str",
        "newStr": "new_str",
        "new": "new_str",
        "desc": "description",
        "prompt": "instruction",
        "replacement_chunks": "edits",
        "chunks": "edits",
        "changes": "edits",
    },
    "multi_edit": {
        "path": "target_file",
        "file_path": "target_file",
        "filepath": "target_file",
        "file": "target_file",
        "replacement_chunks": "edits",
        "chunks": "edits",
        "changes": "edits",
    },
    "web_fetch": {
        "uri": "url",
        "link": "url",
        "path": "url",
        "address": "url",
    },
    "ask_user": {
        "question": "prompt",
        "message": "prompt",
        "text": "prompt",
        "choices": "options",
        "answers": "options",
    },
    "update_plan": {
        "steps": "plan",
        "tasks": "plan",
        "items": "plan",
        "todo": "plan",
    },
    "invoke_subagent": {
        "type": "subagent_type",
        "subagent": "subagent_type",
        "name": "subagent_type",
        "agent_type": "subagent_type",
        "agent": "subagent_type",
        "instructions": "prompt",
        "task": "prompt",
        "goal": "prompt",
        "message": "prompt",
        "mode": "workspace",
    },
    "manage_subagent": {
        "cmd": "action",
        "command": "action",
        "ids": "conversation_ids",
        "subagent_ids": "conversation_ids",
        "id": "conversation_ids",
    },
    "manage_task": {
        "cmd": "action",
        "command": "action",
        "id": "task_id",
        "taskId": "task_id",
        "text": "input",
        "stdin": "input",
        "data": "input",
    },
    "call_mcp": {
        "server": "server_name",
        "mcp_server": "server_name",
        "tool": "tool_name",
        "mcp_tool": "tool_name",
        "args": "arguments",
        "params": "arguments",
        "parameters": "arguments",
        "input": "arguments",
    },
}


def normalize_tool_name(name: str) -> str:
    """Normalizes a tool name or alias to its canonical name using ALIAS_MAP."""
    if not name:
        return ""
    clean = name.strip().lower()
    return ALIAS_MAP.get(clean, clean)


def normalize_tool_args(tool_name: str, args: dict | None) -> Dict[str, Any]:
    """Normalizes tool argument names to canonical names using PARAM_ALIAS_MAP."""
    if not args or not isinstance(args, dict):
        return {}

    clean_name = (tool_name or "").strip().lower()
    resolved_name = ALIAS_MAP.get(clean_name, clean_name)
    param_aliases = PARAM_ALIAS_MAP.get(resolved_name, {})

    normalized = dict(args)
    for k, v in list(args.items()):
        if k in param_aliases:
            canonical = param_aliases[k]
            if canonical not in normalized or normalized[canonical] is None:
                normalized[canonical] = v

    if resolved_name in ("multi_edit", "edit") and isinstance(normalized.get("edits"), list):
        chunk_aliases = {
            "target_content": "old_str",
            "old_content": "old_str",
            "search": "old_str",
            "oldStr": "old_str",
            "old": "old_str",
            "replacement_content": "new_str",
            "new_content": "new_str",
            "replace": "new_str",
            "newStr": "new_str",
            "new": "new_str",
        }
        normalized_edits = []
        for chunk in normalized["edits"]:
            if isinstance(chunk, dict):
                c_norm = dict(chunk)
                for ck, cv in list(chunk.items()):
                    if ck in chunk_aliases:
                        canon_c = chunk_aliases[ck]
                        if canon_c not in c_norm or c_norm[canon_c] is None:
                            c_norm[canon_c] = cv
                normalized_edits.append(c_norm)
            else:
                normalized_edits.append(chunk)
        normalized["edits"] = normalized_edits

    return normalized


def get_default_tools() -> list[Dict[str, Any]]:
    return [cls.schema for cls in TOOL_CLASSES if getattr(cls, "schema", None)]

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
    app_obj = getattr(context_or_app, "app", context_or_app)
    project_dir = (
        getattr(context_or_app, "cwd", None)
        or getattr(context_or_app, "project_dir", None)
        or getattr(app_obj, "project_dir", None)
    )
    action, reason = pm.check_permission(target_perm_name, args, project_dir=project_dir)

    if action == "deny":
        return f"ERR: tool '{display_name}' denied by permission policy"
    elif action == "ask":
        if app_obj and hasattr(app_obj, "push_screen_wait"):
            from widgets.screens.permission_confirm import PermissionConfirmScreen
            screen_name = confirm_tool_name or target_perm_name
            screen = PermissionConfirmScreen(tool_name=screen_name, args=args, reason=reason)
            res = await app_obj.push_screen_wait(screen)
            if res == "always_allow":
                pm.set_session_override(target_perm_name, "allow")
                if target_perm_name == "shell":
                    pm.set_session_override("shell_guard", "allow")
            elif res != "allow":
                return f"ERR: tool '{display_name}' execution denied by user"
        else:
            return f"ERR: tool '{display_name}' requires user confirmation ({reason})"
    return None


async def execute_tool(name: str, args: dict | None, app: Any = None, context: Any = None) -> str:
    raw_name = (name or "").strip()
    clean_name = raw_name.lower()
    resolved_name = ALIAS_MAP.get(clean_name, clean_name)
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
            return f"ERR: execute '{name}': {e}"

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
        return f"ERR: unknown tool '{name}'{hint}"

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
        return f"ERR: mcp '{name}': {e}"

    return f"ERR: unknown tool '{name}'"
