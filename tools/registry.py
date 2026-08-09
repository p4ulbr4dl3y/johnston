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
    "update_file": "edit",
    "modify_file": "edit",
    "str_replace_editor": "edit",
    "replace": "edit",
    "multi_replace": "edit",
    "patch": "edit",
    "apply_patch": "edit",
    "subagent": "invoke_subagent",
    "spawn_subagent": "invoke_subagent",
    "run_subagent": "invoke_subagent",
    "delegate": "invoke_subagent",
    "spawn": "invoke_subagent",
    "run_agent": "invoke_subagent",
    "call_mcp_tool": "call_mcp",
    "mcp": "call_mcp",
    "execute_mcp": "call_mcp",
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
    "get": "web_fetch",
    "curl": "web_fetch",
    "subagents": "manage_subagent",
    "kill_subagent": "manage_subagent",
    "shells": "manage_shell",
    "processes": "manage_shell",
    "manage_processes": "manage_shell",
    "bg_processes": "manage_shell",
}


PARAM_ALIAS_MAP: Dict[str, Dict[str, str]] = {
    "shell": {
        "cmd": "command",
        "script": "command",
        "command_line": "command",
        "exec": "command",
        "time_limit": "timeout",
        "max_seconds": "timeout",
        "timeout_seconds": "timeout",
        "background": "run_in_background",
        "async": "run_in_background",
        "is_async": "run_in_background",
        "bg": "run_in_background",
        "skip_confirmation": "skip_confirm",
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
        "last_line": "end_line",
        "offset": "content_offset",
        "contentOffset": "content_offset",
        "detail_level": "detail",
        "image_detail": "detail",
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
        "file_contents": "code",
        "body": "code",
        "data": "code",
        "summary": "description",
        "desc": "description",
        "reason": "description",
    },
    "edit": {
        "path": "target_file",
        "target_file": "target_file",
        "TargetFile": "target_file",
        "file_path": "target_file",
        "filepath": "target_file",
        "file": "target_file",
        "filename": "target_file",
        "target_content": "old_str",
        "TargetContent": "old_str",
        "old_str": "old_str",
        "old_content": "old_str",
        "old_string": "old_str",
        "search": "old_str",
        "oldStr": "old_str",
        "old": "old_str",
        "replacement_content": "new_str",
        "ReplacementContent": "new_str",
        "new_str": "new_str",
        "new_content": "new_str",
        "new_string": "new_str",
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
        "desc": "description",
        "prompt": "instruction",
        "replacement_chunks": "edits",
        "ReplacementChunks": "edits",
        "chunks": "edits",
        "changes": "edits",
        "replacements": "edits",
    },
    "multi_edit": {
        "path": "target_file",
        "target_file": "target_file",
        "TargetFile": "target_file",
        "file_path": "target_file",
        "filepath": "target_file",
        "file": "target_file",
        "replacement_chunks": "edits",
        "ReplacementChunks": "edits",
        "chunks": "edits",
        "changes": "edits",
        "replacements": "edits",
        "start_line": "start_line",
        "end_line": "end_line",
        "allow_multiple": "allow_multiple",
    },
    "web_fetch": {
        "uri": "url",
        "link": "url",
        "path": "url",
        "address": "url",
        "page_url": "url",
        "as_raw": "raw",
    },
    "ask_user": {
        "question_list": "questions",
        "all_questions": "questions",
        "qs": "questions",
    },
    "update_plan": {
        "steps": "plan",
        "tasks": "plan",
        "items": "plan",
        "todo": "plan",
        "note": "explanation",
    },
    "invoke_subagent": {
        "type": "subagent_type",
        "subagent": "subagent_type",
        "name": "subagent_type",
        "agent_type": "subagent_type",
        "agent": "subagent_type",
        "role": "subagent_type",
        "instructions": "prompt",
        "task": "prompt",
        "goal": "prompt",
        "message": "prompt",
        "mode": "workspace",
        "task_id": "session_id",
        "taskId": "session_id",
        "subagent_id": "session_id",
        "id": "session_id",
    },
    "manage_subagent": {
        "cmd": "action",
        "command": "action",
        "task_id": "session_id",
        "taskId": "session_id",
        "subagent_id": "session_id",
        "id": "session_id",
        "ids": "session_id",
        "subagent_ids": "session_id",
        "msg": "message",
        "async": "background",
        "run_async": "background",
        "show_all": "all",
    },
    "manage_shell": {
        "cmd": "action",
        "command": "action",
        "id": "task_id",
        "taskId": "task_id",
        "text": "input",
        "stdin": "input",
        "data": "input",
        "message": "input",
    },
    "call_mcp": {
        "server_name": "server",
        "mcp_server": "server",
        "tool_name": "tool",
        "mcp_tool": "tool",
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
            from widgets.screens.permission_confirm import PermissionConfirmScreen
            screen_name = confirm_tool_name or target_perm_name
            screen = PermissionConfirmScreen(tool_name=screen_name, args=args, reason=reason)
            res = await app_obj.push_screen_wait(screen)
            if res == "always_allow":
                pm.set_session_override(target_perm_name, "allow")
                if target_perm_name == "shell":
                    pm.set_session_override("shell_guard", "allow")
            elif res != "allow":
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
