import asyncio
import uuid
from typing import Any, Dict

from core.defaults.config import MAX_CONCURRENT_SUBAGENTS
from core.subagent_worktree import SubagentWorktreeManager
from tools.base import BaseTool, format_tool_error

MAX_SUBAGENT_RESULT_CHARS = 15000


def _truncate_subagent_result(text: str, session_id: str = "") -> str:
    """Clip a subagent's final result so a verbose subagent does not flood the
    parent agent's context with a huge <task_result> block. The full session log
    is saved on truncation and the path is returned in the hint."""
    from tools.base import _write_output_log
    from tools.utils import truncate_leading

    text = (text or "").strip()
    if len(text) <= MAX_SUBAGENT_RESULT_CHARS:
        return text

    log_path = _write_output_log(text, session_id=session_id or "subagent") or "log file"
    truncated, shown_lines = truncate_leading(text, MAX_SUBAGENT_RESULT_CHARS)
    next_line = shown_lines + 1
    return (
        truncated
        + f"\n... [Subagent result truncated at {MAX_SUBAGENT_RESULT_CHARS} chars (lines 1-{shown_lines} shown). Full log saved to {log_path}. Use `read` tool (path='{log_path}', start_line={next_line}) to inspect remaining output.]"
    )


def _record_subagent_session(app: Any, session_id: str) -> None:
    """Associate a spawned subagent's session id with the host's current tool widget.

    The subagent_screen/chat_toolcall widgets (UI zone, outside the tools layer)
    read ``session_id`` from the current tool widget to launch the subagent view on
    click. This helper is the single tools-side touchpoint for that coupling; the
    widget access itself cannot be fully isolated without touching the UI zone.
    """
    if app is None:
        return
    widget = getattr(app, "current_tool_widget", None)
    if widget is None:
        return
    if isinstance(getattr(widget, "args", None), dict):
        widget.args["session_id"] = session_id
    try:
        setattr(widget, "subagent_session_id", session_id)
    except Exception:
        pass


class InvokeSubagentTool(BaseTool):
    name = "invoke_subagent"
    description = (
        f"Launch an autonomous subagent for a bounded subtask (max {MAX_CONCURRENT_SUBAGENTS} concurrent). "
        "Returns <task_result>. branch='<name>' runs the subagent on that git branch: if it matches "
        "the current branch it works in the main tree, otherwise in an isolated worktree."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "invoke_subagent",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Task prompt with relative paths, boundaries, output format",
                    },
                    "description": {"type": "string", "description": "Short summary (3-5 words)"},
                    "type": {"type": "string", "description": "Subagent type"},
                    "branch": {
                        "type": "string",
                        "description": "Git branch to work on. If it matches the current branch, the subagent works in the main tree; otherwise it runs in an isolated worktree on that branch (created if missing).",
                    },
                },
                "required": ["prompt", "description", "branch"],
            },
        },
    }

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> str:
        from tools.registry import normalize_tool_args

        args = normalize_tool_args("invoke_subagent", args)
        ctx = self._ensure_context(ctx)
        prompt = args.get("prompt", "").strip()
        description = args.get("description", prompt[:30] or "subagent task").strip()
        subagent_type = args.get("subagent_type", "worker").strip().lower()
        branch_name = args.get("branch", "").strip()

        if not prompt:
            return format_tool_error("params", name="prompt", detail="required")

        if not branch_name:
            return format_tool_error("params", name="branch", detail="required")

        session_id = args.get("session_id") or f"subagent-{uuid.uuid4().hex[:6]}"
        args = {**args, "session_id": session_id}

        _record_subagent_session(ctx.app, session_id)

        parent_session_id = ctx.session_id
        if not isinstance(parent_session_id, str) or not parent_session_id:
            parent_session_id = getattr(getattr(ctx, "app", None), "current_session_id", None)
        from tools.utils import get_session_store

        store = get_session_store(ctx.app)
        store.list(kind="subagent")  # ensure subagent sessions for project are loaded

        active_sessions = (
            store.get_subagents_for_parent(parent_session_id) if parent_session_id else store.list(kind="subagent")
        )
        running_subagents = [s for s in active_sessions if s.status == "running"]
        if len(running_subagents) >= MAX_CONCURRENT_SUBAGENTS:
            return format_tool_error(
                "limit", detail=f"{MAX_CONCURRENT_SUBAGENTS} concurrent max; wait or manage_subagent(action='kill')"
            )

        subagent = ctx.create_agent()
        if not subagent:
            return format_tool_error("context", name="app", detail="unavailable")

        wt_path = None
        wt_branch = None
        project_dir = ctx.project_dir

        from core.infrastructure.runtime.git_utils import run_git

        current_branch = ""
        if SubagentWorktreeManager.is_git_repo(project_dir):
            res = run_git(["branch", "--show-current"], cwd=project_dir, timeout=5)
            current_branch = res.stdout.strip()

        # Same branch as the main tree -> work directly in it; otherwise isolate
        # in a worktree on the requested branch (created if missing).
        if branch_name != current_branch:
            wt_path, wt_branch = SubagentWorktreeManager.create_worktree(project_dir, session_id, branch_name)
            if wt_path:
                subagent.project_dir = wt_path
                subagent.cwd = wt_path

        # Apply role definition: system prompt, model, and tool filtering. Do this
        # BEFORE creating the session so session.role captures the canonically
        # applied role (apply_subagent_role falls back to 'worker' for empty,
        # unknown, or main-only roles), not the raw caller-supplied subagent_type.
        from core.subagent_stream import configure_subagent_agent

        applied_role = configure_subagent_agent(
            subagent, subagent_type, app=ctx.app, project_dir=project_dir
        )
        canonical_role = getattr(subagent, "role", None) or getattr(applied_role, "key", None) or "worker"

        session = store.create_subagent(
            parent_id=parent_session_id or "",
            subagent_id=session_id,
            role=canonical_role,
            description=description,
            prompt=prompt,
            status="running",
            project_dir=wt_path or "",
            branch_name=wt_branch or branch_name,
        )
        session.agent = subagent
        session.add_event({"type": "user", "text": prompt})

        from core.subagent_stream import run_subagent_stream_bg

        cleanup_fn = SubagentWorktreeManager.make_worktree_cleanup_fn(
            project_dir, wt_path, wt_branch, is_followup=False
        )

        from tools.base import format_background_notification

        notification_hdr = format_background_notification(
            "Background subagent", description, session_id, "{result_text}"
        )
        notification_ftr = f"(Note: If details are missing or follow-up is needed, send a message via `manage_subagent(action='send_message', session_id='{session_id}', message='...')`.)"

        bg_task = asyncio.create_task(
            run_subagent_stream_bg(
                subagent,
                prompt,
                session,
                ctx,
                store,
                cleanup_fn=cleanup_fn,
                error_prefix="Subagent error",
                notification_template=f"{notification_hdr}\n{notification_ftr}",
                session_id=session_id,
                truncate_result=True,
            )
        )
        session.async_task = bg_task
        ctx.refresh_status()

        return f"subagent '{description}' launched (session_id: {session_id})"
