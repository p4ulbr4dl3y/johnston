import asyncio
import os
import uuid
from typing import Any, Dict

from core.defaults.config import MAX_CONCURRENT_SUBAGENTS
from core.session_manager import SessionStore
from tools.base import BaseTool, format_tool_error

MAX_SUBAGENT_RESULT_CHARS = 15000


def _truncate_subagent_result(text: str, session_id: str = "") -> str:
    """Clip a subagent's final result so a verbose subagent does not flood the
    parent agent's context with a huge <task_result> block. The full session log
    is saved on truncation and the path is returned in the hint."""
    text = (text or "").strip()
    if len(text) <= MAX_SUBAGENT_RESULT_CHARS:
        return text
    import uuid

    from core.config import LOGS_DIR
    log_name = f"{session_id or 'subagent'}-{uuid.uuid4().hex[:4]}.log"
    log_path = os.path.join(LOGS_DIR, log_name)
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        log_path = "log file"
    truncated = text[:MAX_SUBAGENT_RESULT_CHARS]
    shown_lines = truncated.count("\n") + (1 if truncated else 0)
    next_line = shown_lines + 1
    return (
        truncated
        + f"\n... [Subagent result truncated at {MAX_SUBAGENT_RESULT_CHARS} chars (lines 1-{shown_lines} shown). Full log saved to {log_path}. Use `read` tool (path='{log_path}', start_line={next_line}) to inspect remaining output.]"
    )


class InvokeSubagentTool(BaseTool):
    name = "invoke_subagent"
    description = (
        f"Launch an autonomous subagent for a bounded subtask (max {MAX_CONCURRENT_SUBAGENTS} concurrent). "
        "Returns <task_result>. workspace='branch' returns branch name and diff summary."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "invoke_subagent",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Task prompt with relative paths, boundaries, output format"},
                    "description": {"type": "string", "description": "Short summary (3-5 words)"},
                    "type": {"type": "string", "description": "Subagent type: worker or explorer"},
                    "workspace": {"type": "string", "description": "Workspace: inherit or branch"},
                    "task_id": {"type": "string", "description": "Task ID (auto-generated if omitted)"}
                },
                "required": ["prompt", "description"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> str:
        from tools.registry import normalize_tool_args
        args = normalize_tool_args("invoke_subagent", args)
        ctx = self._ensure_context(ctx)
        prompt = args.get("prompt", "").strip()
        description = args.get("description", prompt[:30] or "subagent task").strip()
        subagent_type = args.get("subagent_type", "worker").strip().lower()
        workspace_mode = args.get("workspace", "inherit").strip().lower()

        if not prompt:
            return format_tool_error("params", name="prompt", detail="required")

        session_id = args.get("session_id") or f"subagent-{uuid.uuid4().hex[:6]}"
        args["session_id"] = session_id

        if ctx.app and getattr(ctx.app, "current_tool_widget", None):
            ctx.app.current_tool_widget.args["session_id"] = session_id
            setattr(ctx.app.current_tool_widget, "subagent_session_id", session_id)

        parent_session_id = getattr(ctx.app, "current_session_id", None) if ctx.app else None
        if ctx.app and getattr(ctx.app, "sm", None):
            store = ctx.app.sm
        else:
            store = SessionStore.get_instance()
        store.list(kind="subagent")  # ensure subagent sessions for project are loaded

        active_sessions = store.get_subagents_for_parent(parent_session_id) if parent_session_id else store.list(kind="subagent")
        running_subagents = [s for s in active_sessions if s.status == "running"]
        if len(running_subagents) >= MAX_CONCURRENT_SUBAGENTS:
            return format_tool_error(
                "limit", detail=f"{MAX_CONCURRENT_SUBAGENTS} concurrent max; wait or manage_subagent(action='kill')"
            )

        subagent = ctx.create_agent()
        if not subagent:
            return format_tool_error("context", name="app", detail="unavailable")
        subagent.app = ctx.app
        subagent.is_subagent = True

        wt_path = None
        wt_branch = None
        project_dir = ctx.project_dir

        if workspace_mode in ("branch", "share"):
            from core.subagent_worktree import SubagentWorktreeManager
            wt_path, wt_branch = SubagentWorktreeManager.create_worktree(project_dir, session_id)
            if wt_path:
                subagent.project_dir = wt_path
                subagent.cwd = wt_path

        session = store.create_subagent(
            parent_id=parent_session_id or "",
            subagent_id=session_id,
            role=subagent_type,
            description=description,
            prompt=prompt,
            status="running",
            project_dir=wt_path or "",
            branch_name=wt_branch or "",
        )
        session.agent = subagent
        session.add_event({"type": "user", "text": prompt})

        # Apply role definition: system prompt, model, and tool filtering
        from core.subagent_stream import apply_subagent_role
        apply_subagent_role(subagent, subagent_type, project_dir=project_dir)

        from core.subagent_stream import run_subagent_stream_bg
        from core.subagent_worktree import SubagentWorktreeManager

        def _cleanup_worktree_and_append_diff(acc):
            nonlocal wt_path, wt_branch
            wt_path, wt_branch = SubagentWorktreeManager.append_worktree_diff_to_acc(
                project_dir, wt_path, wt_branch, acc, is_followup=False
            )

        from tools.base import format_background_notification
        notification_hdr = format_background_notification("Background subagent", description, session_id, "{result_text}")
        notification_ftr = f"(Note: If details are missing or follow-up is needed, send a message via `manage_subagent(action='send_message', session_id='{session_id}', message='...')`.)"

        bg_task = asyncio.create_task(
            run_subagent_stream_bg(
                subagent,
                prompt,
                session,
                ctx,
                store,
                cleanup_fn=_cleanup_worktree_and_append_diff,
                error_prefix="Subagent error",
                notification_template=f"{notification_hdr}\n{notification_ftr}",
                session_id=session_id,
                truncate_result=True,
            )
        )
        session.async_task = bg_task
        ctx.refresh_status()

        return f"subagent '{description}' launched ({session_id})"
