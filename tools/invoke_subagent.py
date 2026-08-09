import asyncio
import os
import uuid
from typing import Any, Dict

from core.background_task import BackgroundSubagent
from core.defaults.config import MAX_CONCURRENT_SUBAGENTS
from core.session_manager import SessionStore
from tools.base import BaseTool

MAX_SUBAGENT_RESULT_CHARS = 15000


def _truncate_subagent_result(text: str, task_id: str = "") -> str:
    """Clip a subagent's final result so a verbose subagent does not flood the
    parent agent's context with a huge <task_result> block. The full session log
    is saved on truncation and the path is returned in the hint."""
    text = (text or "").strip()
    if len(text) <= MAX_SUBAGENT_RESULT_CHARS:
        return text
    import uuid

    from core.config import LOGS_DIR
    log_name = f"{task_id or 'subagent'}-{uuid.uuid4().hex[:4]}.log"
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
        f"Launch an autonomous subagent for a bounded, non-blocking subtask (max {MAX_CONCURRENT_SUBAGENTS} concurrent). "
        "Returns <task_result> on completion. When workspace='branch', returns created git branch name and diff summary to merge."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "invoke_subagent",
            "description": (
                f"Launch an autonomous subagent for a bounded, non-blocking subtask (max {MAX_CONCURRENT_SUBAGENTS} concurrent). "
                "Returns <task_result> on completion. When workspace='branch', returns created git branch name and diff summary to merge."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Detailed task prompt with relative file paths from project root, clear boundaries, and expected output format"},
                    "description": {"type": "string", "description": "Short summary (3-5 words)"},
                    "subagent_type": {"type": "string", "description": "Subagent type: 'worker' (task execution) or 'explorer' (read-only analysis)"},
                    "workspace": {"type": "string", "description": "Workspace: 'inherit' (current directory) or 'branch' (isolated git worktree; returns branch name and diff summary on completion to merge via `git merge`)"},
                    "task_id": {"type": "string", "description": "Optional task ID"}
                },
                "required": ["prompt", "description"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        ctx = self._ensure_context(app)
        prompt = args.get("prompt", "").strip()
        description = args.get("description", prompt[:30] or "subagent task").strip()
        subagent_type = args.get("subagent_type", "worker").strip().lower()
        workspace_mode = args.get("workspace", "inherit").strip().lower()

        if not prompt:
            return "ERR: 'prompt' required"

        task_id = args.get("task_id") or f"subagent-{uuid.uuid4().hex[:6]}"
        args["task_id"] = task_id

        if ctx.app and getattr(ctx.app, "current_tool_widget", None):
            ctx.app.current_tool_widget.args["task_id"] = task_id
            setattr(ctx.app.current_tool_widget, "subagent_task_id", task_id)

        session_id = getattr(ctx.app, "current_session_id", None) if ctx.app else None
        if ctx.app and getattr(ctx.app, "sm", None):
            store = ctx.app.sm
        else:
            store = SessionStore.get_instance()
        store.list(kind="subagent")  # ensure subagent sessions for project are loaded

        active_sessions = store.get_subagents_for_parent(session_id) if session_id else store.list(kind="subagent")
        running_subagents = [s for s in active_sessions if s.status == "running"]
        if len(running_subagents) >= MAX_CONCURRENT_SUBAGENTS:
            return (
                f"ERR: maximum concurrent subagents limit ({MAX_CONCURRENT_SUBAGENTS}) reached. "
                "Wait for running subagents to finish or terminate them using `manage_subagent` action='kill'."
            )

        subagent = ctx.create_agent()
        if not subagent:
            return "ERR: no app context"
        subagent.app = ctx.app
        subagent.is_subagent = True

        wt_path = None
        wt_branch = None
        project_dir = ctx.project_dir

        if workspace_mode in ("branch", "share"):
            from core.subagent_worktree import SubagentWorktreeManager
            wt_path, wt_branch = SubagentWorktreeManager.create_worktree(project_dir, task_id)
            if wt_path:
                subagent.project_dir = wt_path
                subagent.cwd = wt_path

        session = store.create_subagent(
            parent_id=session_id or "",
            subagent_id=task_id,
            role=subagent_type,
            description=description,
            prompt=prompt,
            status="running",
            project_dir=wt_path or "",
            branch_name=wt_branch or "",
        )
        session.agent = subagent
        session.add_event({"type": "user", "text": prompt})

        # Disable nested subagent spawning, background task management, and UI questions for subagents
        subagent.allow_task = False
        original_tools = getattr(subagent, "tools", []) or []
        excluded_tools = {"invoke_subagent", "manage_subagent", "manage_task", "ask_user"}
        subagent.tools = [
            t for t in original_tools
            if t.get("function", {}).get("name", "").lower() not in excluded_tools
        ]

        from core.prompt_builder import SUBAGENT_DEFAULT_SYSTEM_PROMPT
        from core.role_registry import RoleRegistry
        registry = RoleRegistry.get_instance()
        registry.load_roles(project_dir=project_dir)
        definition = registry.get_role(subagent_type)

        subagent.mode = definition.key
        subagent.system_prompt = f"{SUBAGENT_DEFAULT_SYSTEM_PROMPT}\n\n{definition.system_prompt}"
        if definition.model:
            subagent.model = definition.model

        if definition.read_only or definition.disallowed_tools or definition.allowed_tools:
            subagent.tools = [
                t for t in subagent.tools
                if definition.is_tool_allowed(t.get("function", {}).get("name", "")) is None
            ]

        import copy
        subagent_tools_custom = []
        for t in subagent.tools:
            if isinstance(t, dict) and t.get("function", {}).get("name") == "shell":
                t_copy = copy.deepcopy(t)
                t_copy["function"]["description"] = (
                    "Run a synchronous terminal command with a configurable timeout (default 60s, max 300s). "
                    "Processes terminate on timeout. Always use non-interactive flags (e.g. -y, --non-interactive) to prevent hanging."
                )
                subagent_tools_custom.append(t_copy)
            else:
                subagent_tools_custom.append(t)
        subagent.tools = subagent_tools_custom

        from core.subagent_tracker import run_subagent_stream_bg
        from core.subagent_worktree import SubagentWorktreeManager

        def _cleanup_worktree_and_append_diff(acc):
            nonlocal wt_path, wt_branch
            wt_path, wt_branch = SubagentWorktreeManager.append_worktree_diff_to_acc(
                project_dir, wt_path, wt_branch, acc, is_followup=False
            )

        notification_hdr = f"[System Notification] Background subagent '{description}' (ID: {task_id}) completed."
        notification_ftr = f"(Note: If details are missing or follow-up is needed, send a message via `manage_subagent(action='send_message', task_id='{task_id}', message='...')`.)"

        bg_task = asyncio.create_task(
            run_subagent_stream_bg(
                subagent,
                prompt,
                session,
                ctx,
                store,
                cleanup_fn=_cleanup_worktree_and_append_diff,
                error_prefix="Subagent error",
                notification_template=f"{notification_hdr}\n<task_result>\n{{result_text}}\n</task_result>\n{notification_ftr}",
                task_id=task_id,
                truncate_result=True,
            )
        )
        session.async_task = bg_task
        curr_sid = getattr(ctx.app, "current_session_id", None) if ctx.app else None
        bg_sub = BackgroundSubagent(task_id, description, bg_task, session_id=curr_sid)
        ctx.add_background_task(bg_sub)

        return f"OK: subagent '{description}' launched ({task_id})"
