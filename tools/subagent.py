import asyncio
import uuid
from typing import Any, Dict

from core.background_task import BackgroundSubagent
from core.config import MAX_CONCURRENT_SUBAGENTS
from core.subagent_tracker import SubagentTracker
from tools.base import BaseTool


class SubagentTool(BaseTool):
    name = "subagent"
    description = (
        "Launch a subagent to perform a task. "
        "Use subagent_type='explore' for quick codebase searches, or 'general' for multi-step tasks. "
        "Set background=true to run asynchronously without waiting."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "subagent",
            "description": "Launch a subagent to perform a task. Use subagent_type='explore' for fast codebase search, or 'general' for multi-step tasks. Set background=true to run asynchronously.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Task prompt for the subagent"},
                    "description": {"type": "string", "description": "Short (3-5 words) description"},
                    "subagent_type": {"type": "string", "description": "Type of subagent ('general' or 'explore')"},
                    "background": {"type": "boolean", "description": "Run asynchronously in background"}
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
        run_in_background = bool(args.get("background", False))

        if not prompt:
            return "Error: 'prompt' argument is required for subagent tool."

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
                f"Error: Maximum concurrent subagents limit ({MAX_CONCURRENT_SUBAGENTS}) reached. "
                "Wait for running subagents to finish or terminate them using `manage_subagent` action='kill'."
            )

        subagent = ctx.create_agent()
        if not subagent:
            return "Error: No application context available to spawn subagent."
        subagent.app = ctx.app

        session = tracker.create_session(
            task_id, description, prompt, subagent_type, run_in_background, session_id=session_id
        )
        session.agent = subagent
        session.add_event({"type": "user", "text": prompt})

        # Disable nested Task tool calls (recursion guard)
        subagent.allow_task = False
        original_tools = getattr(subagent, "tools", []) or []
        subagent.tools = [
            t for t in original_tools
            if t.get("function", {}).get("name") not in ("subagent", "Subagent", "Task", "task")
        ]

        from core.subagent_registry import SubagentRegistry
        registry = SubagentRegistry.get_instance()
        registry.reload(project_dir=getattr(ctx.app, "project_dir", None))
        definition = registry.get_definition(subagent_type)

        subagent.system_prompt += f"\n\n{definition.system_prompt}"
        if definition.model:
            subagent.model = definition.model
        if definition.tools:
            subagent.tools = [
                t for t in subagent.tools
                if t.get("function", {}).get("name") in definition.tools
            ]

        def _record_step(step, acc):
            etype = step[0]
            val1 = step[1] if len(step) > 1 else ""
            val2 = step[2] if len(step) > 2 else ""
            val3 = step[3] if len(step) > 3 else None

            if etype == "thinking_start":
                session.add_event({"type": "thinking_start", "val1": val1})
            elif etype == "thinking_delta":
                session.add_event({"type": "thinking_delta", "val1": val1})
            elif etype == "thinking_end":
                try:
                    dur = float(val1)
                except Exception:
                    dur = 0.0
                session.add_event({"type": "thinking_end", "duration": dur, "content": val2})
            elif etype == "tool":
                targs = val3 if isinstance(val3, dict) else {}
                session.add_event({"type": "tool", "tool_type": val1, "target": val2, "args": targs})
            elif etype == "tool_result":
                session.add_event({"type": "tool_result", "result_text": val1})
            elif etype == "bot_chunk":
                session.add_event({"type": "bot_chunk", "text": val1})
                acc[0] += val1
            elif etype == "bot_delta":
                session.add_event({"type": "bot_delta", "text": val1})
                acc[0] = val1
            elif etype in ("bot_text", "outro"):
                session.add_event({"type": "bot_text", "text": val1})
                acc[0] = val1

        def _merge_metrics():
            if ctx.app and hasattr(ctx.app, "agent") and ctx.app.agent:
                main_agent = ctx.app.agent
                main_agent.tokens_input += getattr(subagent, "tokens_input", 0)
                main_agent.tokens_output += getattr(subagent, "tokens_output", 0)
                main_agent.total_tokens += getattr(subagent, "total_tokens", 0)
                main_agent.cost_usd += getattr(subagent, "cost_usd", 0.0)
                ctx.refresh_status()

        if run_in_background:
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
                    _merge_metrics()
                    for t in ctx.background_tasks:
                        if getattr(t, "task_id", "") == task_id:
                            t.is_running = False
                    ctx.refresh_status()

                    msg = (
                        f"[System Notification] Background subagent '{description}' (ID: {task_id}) completed.\n"
                        f"<task_result>\n{acc[0].strip() or 'Completed with no text output.'}\n</task_result>\n"
                        f"(Note: Full session log stored in storage file; inspect via `manage_subagent(action='status', task_id='{task_id}')`)"
                    )
                    ctx.trigger_ai_response(msg)

            bg_task = asyncio.create_task(_run_bg())
            session.async_task = bg_task
            bg_obj = BackgroundSubagent(task_id, description, bg_task)
            ctx.add_background_task(bg_obj)
            ctx.notify(f"Subagent launched in background (ID: {task_id})")

            return (
                f"Subagent '{description}' launched in background (Task ID: {task_id}). "
                "You will be notified automatically when it completes. Do not poll for status."
            )
        else:
            # Foreground execution
            acc = [""]
            try:
                async for step in subagent.stream_steps(prompt):
                    _record_step(step, acc)
                session.finish("completed")
            except Exception as err:
                session.finish("error", str(err))
                return f"Subagent execution error: {err}"
            finally:
                _merge_metrics()

            return f"<task_result>\n{acc[0].strip() or 'Subagent finished with no text output.'}\n</task_result>"
