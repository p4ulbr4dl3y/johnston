import asyncio
import copy
import uuid
from typing import Any, Dict

from core.domain.defaults.config import MAX_CONCURRENT_SUBAGENTS
from core.domain.defaults.errors import ToolResult, ToolResultStatus
from core.infrastructure.runtime.subagent_worktree import SubagentWorktreeManager
from tools.base import BaseTool


def _record_subagent_session(app: Any, session_id: str) -> None:
    """Associate a spawned subagent's session id with the host's current tool widget.

    The subagent_screen/chat_toolcall widgets (UI zone, outside the tools layer)
    read ``session_id`` from the current tool widget to launch the subagent view on
    click. This helper is the single tools-side touchpoint for that coupling; the
    widget access itself cannot be fully isolated without touching the UI zone.

    Also registers the widget in the host's subagent-tool registry so the
    background completion callback can repaint the card (yellow -> green/red).
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
    reg = getattr(app, "_subagent_tools", None)
    if not isinstance(reg, dict):
        reg = {}
        app._subagent_tools = reg
    reg[session_id] = widget


def _mark_subagent_running(app: Any, session_id: str, text: str = "") -> None:
    """Flip the host's invoke_subagent widget for ``session_id`` back to running (yellow).

    Used when a follow-up (``manage_subagent send_message``) is dispatched: the
    subagent is now working again, so its card should leave the green "done"
    state until the background completion callback repaints it to a final color.
    Safe no-op in headless environments (no app / no widget / widget without a
    ``mark_running`` hook).
    """
    if app is None:
        return
    reg = getattr(app, "_subagent_tools", None)
    if not isinstance(reg, dict):
        return
    widget = reg.get(session_id)
    if widget is None:
        return
    mark = getattr(widget, "mark_running", None)
    if callable(mark):
        try:
            mark(text=text)
        except Exception:
            pass


class InvokeSubagentTool(BaseTool):
    name = "invoke_subagent"
    description = (
        f"Launch an autonomous subagent in the background for a bounded task "
        f"(max {MAX_CONCURRENT_SUBAGENTS} concurrent). "
        "Completion notifies automatically. Manage or follow up via 'manage_subagent'."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "invoke_subagent",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": (
                            "Short task title as a noun phrase (3-5 words, "
                            "e.g. 'Key handling refactor', 'Streaming core audit', not verbs)"
                        ),
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Task instructions with clear boundaries and expected output format",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["worker", "explorer"],
                        "description": "Subagent role name from available roles (default: 'worker')",
                    },
                    "branch": {
                        "type": "string",
                        "description": (
                            "Git branch name for worktree isolation. MUST be used for parallel write/edit tasks "
                            "to avoid file conflicts. Runs in an isolated worktree. On completion, changes stay on "
                            "this branch for you to `git merge <branch>`. "
                            "If omitted or same as current branch, runs directly in main workspace."
                        ),
                    },
                },
                "required": ["title", "prompt"],
            },
        },
    }

    def get_schema(self, is_subagent: bool = False) -> Dict[str, Any]:
        from core.role_registry import RoleRegistry

        schema = copy.deepcopy(self.schema)
        try:
            roles = sorted(RoleRegistry.get_instance().list_subagent_roles().keys())
            if roles and "type" in schema.get("function", {}).get("parameters", {}).get("properties", {}):
                schema["function"]["parameters"]["properties"]["type"]["enum"] = roles
        except Exception:
            pass
        return schema

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        ctx = self._ensure_context(ctx)
        args = args or {}
        prompt = (args.get("prompt") or "").strip()
        title = (args.get("title") or prompt[:30] or "subagent task").strip()
        subagent_type = args.get("type", "worker").strip().lower()
        branch_name = args.get("branch", "").strip()

        if not prompt:
            return ToolResult.error("params", name="prompt", detail="required")

        session_id = f"subagent-{uuid.uuid4().hex[:6]}"
        args = {**args, "session_id": session_id}

        _record_subagent_session(ctx.host, session_id)

        parent_session_id = ctx.session_id
        if not isinstance(parent_session_id, str) or not parent_session_id:
            parent_session_id = getattr(getattr(ctx, "host", None), "current_session_id", None)
        from core.session_manager import get_session_store

        store = get_session_store(ctx.host)
        store.list(kind="subagent")  # ensure subagent sessions for project are loaded

        active_sessions = store.children(parent_session_id) if parent_session_id else store.list(kind="subagent")
        running_subagents = [s for s in active_sessions if s.status == "running"]
        if len(running_subagents) >= MAX_CONCURRENT_SUBAGENTS:
            return ToolResult.error(
                "limit", detail=f"{MAX_CONCURRENT_SUBAGENTS} concurrent max; wait or manage_subagent(action='kill')"
            )

        subagent = ctx.create_agent()
        if not subagent:
            return ToolResult.error("context", name="app", detail="unavailable")

        wt_path = None
        wt_branch = None
        project_dir = ctx.project_dir

        from core.infrastructure.runtime.git_utils import run_git_async

        is_git = SubagentWorktreeManager.is_git_repo(project_dir)
        current_branch = ""
        if is_git:
            res = await run_git_async(["branch", "--show-current"], cwd=project_dir, timeout=5)
            current_branch = res.stdout.strip()

        # Same branch as the main tree or no branch requested -> work directly in it;
        # otherwise isolate in a worktree on the requested branch (created if missing).
        if is_git and branch_name and branch_name != current_branch:
            wt_path, wt_branch = await SubagentWorktreeManager.create_worktree_async(
                project_dir, session_id, branch_name
            )
            if wt_path:
                subagent.project_dir = wt_path
                subagent.cwd = wt_path

        # Apply role definition: system prompt, model, and tool filtering. Do this
        # BEFORE creating the session so session.role captures the canonically
        # applied role (apply_subagent_role falls back to 'worker' for empty,
        # unknown, or main-only roles), not the raw caller-supplied subagent_type.
        from core.application.session.stream import configure_subagent_agent

        applied_role = configure_subagent_agent(
            subagent, subagent_type, app=ctx.host, project_dir=project_dir
        )
        canonical_role = getattr(subagent, "role", None) or getattr(applied_role, "key", None) or "worker"

        session = store.create_subagent(
            parent_id=parent_session_id or "",
            subagent_id=session_id,
            role=canonical_role,
            description=title,
            prompt=prompt,
            status="running",
            project_dir=wt_path or "",
            branch_name=wt_branch or (branch_name if is_git else ""),
        )
        session.agent = subagent
        subagent.session = session
        session.add_event({"type": "user", "text": prompt})

        from core.application.session.stream import run_subagent_stream_bg

        cleanup_fn = SubagentWorktreeManager.make_worktree_cleanup_fn(
            project_dir, wt_path, wt_branch, is_followup=False
        )

        from tools.base import format_background_notification

        notification_hdr = format_background_notification(
            "subagent",
            title,
            session_id,
            "{result_text}",
        )

        bg_task = asyncio.create_task(
            run_subagent_stream_bg(
                subagent,
                prompt,
                session,
                ctx,
                store,
                cleanup_fn=cleanup_fn,
                error_prefix="Subagent error",
                notification_template=notification_hdr,
                session_id=session_id,
                truncate_result=True,
            )
        )
        session.async_task = bg_task
        ctx.refresh_status()

        branch_info = f" | branch: {branch_name}" if branch_name else ""
        content_txt = f"[subagent started | id: {session_id} | role: {canonical_role}{branch_info}]"
        return ToolResult(
            status=ToolResultStatus.RUNNING,
            content=content_txt,
            display="",
        )
