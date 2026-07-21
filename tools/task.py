import asyncio
import uuid
from typing import Any, Dict
from tools.base import BaseTool

class TaskTool(BaseTool):
    name = "Task"
    description = (
        "Launch a subagent to perform a task. "
        "Use subagent_type='explore' for quick codebase searches, or 'general' for multi-step tasks. "
        "Set background=true to run asynchronously without waiting."
    )

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        prompt = args.get("prompt", "").strip()
        description = args.get("description", prompt[:30] or "subagent task").strip()
        subagent_type = args.get("subagent_type", "general").strip().lower()
        run_in_background = bool(args.get("background", False))

        if not prompt:
            return "Error: 'prompt' argument is required for Task tool."

        if not app or not hasattr(app, "pm"):
            return "Error: No application context available to spawn subagent."

        # Создаем изолированного агента
        subagent = app.pm.create_active_agent()
        subagent.app = app

        # Отключаем возможность повторного вызова Task (защита от рекурсии)
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
                        if event_type in ("bot_text", "outro"):
                            full_text = val1
                        elif event_type == "bot_chunk":
                            full_text += val1
                except asyncio.CancelledError:
                    full_text = "[Subagent cancelled]"
                except Exception as err:
                    full_text = f"[Subagent error: {err}]"
                finally:
                    if hasattr(app, "background_tasks"):
                        for t in app.background_tasks:
                            if getattr(t, "task_id", "") == task_id:
                                t.is_running = False
                    if hasattr(app, "refresh_status_footer"):
                        app.refresh_status_footer()

                    msg = (
                        f"[System Notification] Background subagent '{description}' (ID: {task_id}) completed.\n"
                        f"<task_result>\n{full_text.strip() or 'Completed with no text output.'}\n</task_result>"
                    )
                    if hasattr(app, "generate_ai_response"):
                        app.generate_ai_response(msg, show_in_ui=False)

            bg_task = asyncio.create_task(_run_bg())

            from background_task import BackgroundSubagent
            bg_obj = BackgroundSubagent(task_id, description, bg_task)
            if hasattr(app, "background_tasks"):
                app.background_tasks.append(bg_obj)
            if hasattr(app, "refresh_status_footer"):
                app.refresh_status_footer()

            if hasattr(app, "notify"):
                app.notify(f"Subagent launched in background (ID: {task_id})")

            return (
                f"Subagent '{description}' launched in background (Task ID: {task_id}). "
                "You will be notified automatically when it completes. Do not poll for status."
            )
        else:
            # Foreground execution
            full_text = ""
            try:
                async for event_type, val1, val2 in subagent.stream_steps(prompt):
                    if event_type in ("bot_text", "outro"):
                        full_text = val1
                    elif event_type == "bot_chunk":
                        full_text += val1
            except Exception as err:
                return f"Subagent execution error: {err}"

            return f"<task_result>\n{full_text.strip() or 'Subagent finished with no text output.'}\n</task_result>"
