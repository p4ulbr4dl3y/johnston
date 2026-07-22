import asyncio
import uuid
from typing import Any, Dict

from core.background_task import BackgroundSubagent
from tools.base import BaseTool


class SubagentTool(BaseTool):
    name = "Subagent"
    description = (
        "Launch a subagent to perform a task. "
        "Use subagent_type='explore' for quick codebase searches, or 'general' for multi-step tasks. "
        "Set background=true to run asynchronously without waiting."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "Subagent",
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
            return "Error: 'prompt' argument is required for Task tool."

        subagent = ctx.create_agent()
        if not subagent:
            return "Error: No application context available to spawn subagent."
        subagent.app = ctx.app

        # Отключаем возможность повторного вызова Task (защита от рекурсии)
        subagent.allow_task = False
        original_tools = getattr(subagent, "tools", []) or []
        subagent.tools = [
            t for t in original_tools
            if t.get("function", {}).get("name") not in ("Task", "task")
        ]

        if subagent_type == "explore":
            subagent.system_prompt += "\n\n[SUBAGENT EXPLORE MODE]\nYou are a fast exploration subagent. Find answers, search codebase, read files, and summarize findings concisely."
        else:
            subagent.system_prompt += f"\n\n[SUBAGENT MODE: {subagent_type.upper()}]\nYou are a subagent executing: {description}. Perform the task and return concise results."

        if run_in_background:
            task_id = f"subagent-{uuid.uuid4().hex[:6]}"

            async def _run_bg():
                full_text = ""
                try:
                    async for event_type, val1, val2 in subagent.stream_steps(prompt):
                        if event_type in ("bot_text", "outro", "bot_delta"):
                            full_text = val1
                        elif event_type == "bot_chunk":
                            full_text += val1
                except asyncio.CancelledError:
                    full_text = "[Subagent cancelled]"
                except Exception as err:
                    full_text = f"[Subagent error: {err}]"
                finally:
                    for t in ctx.background_tasks:
                        if getattr(t, "task_id", "") == task_id:
                            t.is_running = False
                    ctx.refresh_status()

                    msg = (
                        f"[System Notification] Background subagent '{description}' (ID: {task_id}) completed.\n"
                        f"<task_result>\n{full_text.strip() or 'Completed with no text output.'}\n</task_result>"
                    )
                    ctx.trigger_ai_response(msg)

            bg_task = asyncio.create_task(_run_bg())
            bg_obj = BackgroundSubagent(task_id, description, bg_task)
            ctx.add_background_task(bg_obj)
            ctx.notify(f"Subagent launched in background (ID: {task_id})")

            return (
                f"Subagent '{description}' launched in background (Task ID: {task_id}). "
                "You will be notified automatically when it completes. Do not poll for status."
            )
        else:
            # Foreground execution
            full_text = ""
            try:
                async for event_type, val1, val2 in subagent.stream_steps(prompt):
                    if event_type in ("bot_text", "outro", "bot_delta"):
                        full_text = val1
                    elif event_type == "bot_chunk":
                        full_text += val1
            except Exception as err:
                return f"Subagent execution error: {err}"

            return f"<task_result>\n{full_text.strip() or 'Subagent finished with no text output.'}\n</task_result>"
