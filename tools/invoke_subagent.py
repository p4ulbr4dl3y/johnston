import asyncio
import os
import uuid
from typing import Any, Dict

from core.background_task import BackgroundSubagent
from core.config import MAX_CONCURRENT_SUBAGENTS
from core.subagent_tracker import SubagentTracker
from tools.base import BaseTool

MAX_SUBAGENT_RESULT_CHARS = 15000


def _truncate_subagent_result(text: str) -> str:
    """Clip a subagent's final result so a verbose subagent does not flood the
    parent agent's context with a huge <task_result> block. The full session log
    remains available via manage_subagent(action='status')."""
    text = (text or "").strip()
    if len(text) <= MAX_SUBAGENT_RESULT_CHARS:
        return text
    return (
        text[:MAX_SUBAGENT_RESULT_CHARS]
        + "\n... [subagent result truncated to keep parent context lean; "
        "inspect the full session via manage_subagent(action='status')]"
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
                    "prompt": {"type": "string", "description": "Detailed task prompt with clear boundaries and expected output format"},
                    "description": {"type": "string", "description": "Short summary (3-5 words)"},
                    "subagent_type": {"type": "string", "description": "Subagent type: 'general' (task execution) or 'explore' (read-only analysis)"},
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
        subagent_type = args.get("subagent_type", "general").strip().lower()
        workspace_mode = args.get("workspace", "inherit").strip().lower()

        if not prompt:
            return "ERR: 'prompt' required"

        task_id = args.get("task_id") or f"subagent-{uuid.uuid4().hex[:6]}"
        args["task_id"] = task_id

        if ctx.app and getattr(ctx.app, "current_tool_widget", None):
            ctx.app.current_tool_widget.args["task_id"] = task_id
            setattr(ctx.app.current_tool_widget, "subagent_task_id", task_id)

        session_id = getattr(ctx.app, "current_session_id", None) if ctx.app else None
        tracker = SubagentTracker.get_instance()

        active_sessions = tracker.get_sessions_for_session(session_id)
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
        project_dir = getattr(ctx.app, "project_dir", None) or os.getcwd()

        if workspace_mode in ("branch", "share"):
            from core.subagent_worktree import SubagentWorktreeManager
            wt_path, wt_branch = SubagentWorktreeManager.create_worktree(project_dir, task_id)
            if wt_path:
                subagent.project_dir = wt_path
                subagent.cwd = wt_path

        session = tracker.create_session(
            task_id, description, prompt, subagent_type, background=True, session_id=session_id
        )
        session.agent = subagent
        session.project_dir = wt_path or ""
        session.branch_name = wt_branch or ""
        session.add_event({"type": "user", "text": prompt})

        # Disable nested Task tool calls (recursion guard) and background task management
        subagent.allow_task = False
        original_tools = getattr(subagent, "tools", []) or []
        excluded_tools = {"subagent", "Subagent", "invoke_subagent", "InvokeSubagent", "Task", "task", "manage_task", "ManageTask"}
        subagent.tools = [
            t for t in original_tools
            if t.get("function", {}).get("name") not in excluded_tools
        ]

        from core.subagent_registry import SubagentRegistry
        registry = SubagentRegistry.get_instance()
        registry.reload(project_dir=getattr(ctx.app, "project_dir", None))
        definition = registry.get_definition(subagent_type)

        subagent.system_prompt += f"\n\n{definition.system_prompt}"
        if definition.model:
            subagent.model = definition.model

        if subagent_type == "explore":
            edit_tool_names = {
                "create", "edit", "replace_file_content", "multi_replace_file_content",
                "Create", "Edit", "Replace_File_Content", "Multi_Replace_File_Content"
            }
            subagent.tools = [
                t for t in subagent.tools
                if t.get("function", {}).get("name") not in edit_tool_names
            ]

        if definition.tools:
            subagent.tools = [
                t for t in subagent.tools
                if t.get("function", {}).get("name") in definition.tools
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

        from core.subagent_tracker import merge_subagent_metrics, record_subagent_step

        def _record_step(step, acc):
            record_subagent_step(step, session, acc)

        def _merge_metrics():
            merge_subagent_metrics(subagent, ctx)
            ctx.refresh_status()

        def _cleanup_worktree_and_append_diff(acc):
            nonlocal wt_path, wt_branch
            if wt_path and wt_branch:
                from core.subagent_worktree import SubagentWorktreeManager
                diff_text, has_changes = SubagentWorktreeManager.get_worktree_diff_summary(project_dir, wt_path, wt_branch)
                if has_changes and diff_text:
                    acc[0] += (
                        f"\n\n[Worktree Branch '{wt_branch}']\n"
                        f"Changes saved to git branch '{wt_branch}'. Run `git merge {wt_branch}` to apply, or `git diff {wt_branch}` for full diff.\n"
                        f"After merging, clean up the branch with `git branch -d {wt_branch}`.\n\n"
                        f"{diff_text}"
                    )
                SubagentWorktreeManager.cleanup_worktree(project_dir, wt_path, wt_branch, keep_branch=has_changes)
                wt_path = None
                wt_branch = None

        async def _run_bg():
            acc = [""]
            try:
                async for step in subagent.stream_steps(prompt):
                    _record_step(step, acc)
                session.finish("completed")
            except asyncio.CancelledError:
                acc[0] = "[Subagent cancelled]"
                session.finish("cancelled", "Cancelled by user")
            except Exception as err:
                acc[0] = f"[Subagent error: {err}]"
                session.finish("error", str(err))
            finally:
                _cleanup_worktree_and_append_diff(acc)
                _merge_metrics()
                for t in ctx.background_tasks:
                    if getattr(t, "task_id", "") == task_id:
                        t.is_running = False

                ctx.refresh_status()

                result_text = _truncate_subagent_result(acc[0]) or "Completed with no text output."
                msg = (
                    f"[System Notification] Background subagent '{description}' (ID: {task_id}) completed.\n"
                    f"<task_result>\n{result_text}\n</task_result>\n"
                    f"(Note: If details are missing or follow-up is needed, send a message via `manage_subagent(action='send_message', task_id='{task_id}', message='...')`.)"
                )
                ctx.trigger_ai_response(msg)

        bg_task = asyncio.create_task(_run_bg())
        session.async_task = bg_task
        curr_sid = getattr(ctx.app, "current_session_id", None) if ctx.app else None
        bg_sub = BackgroundSubagent(task_id, description, bg_task, session_id=curr_sid)
        ctx.add_background_task(bg_sub)

        return f"OK: subagent '{description}' launched ({task_id})"
