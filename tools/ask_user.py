import asyncio
from typing import Any, Dict

from tools.base import BaseTool


class AskUserTool(BaseTool):
    name = "ask_user"
    description = "Ask the user questions with pre-defined options and write-in answers. Use when user intent or requirements are ambiguous."
    schema = {
        "type": "function",
        "function": {
            "name": "ask_user",
            "parameters": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "description": "List of questions with pre-defined options and write-in choices",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question_text": {"type": "string", "description": "Main question"},
                                "options": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "List of selectable options. If recommending an option, list it first and prefix with '(Recommended)'."
                                }

                            },
                            "required": ["question_text", "options"]
                        }
                    }
                },
                "required": ["questions"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        ctx = self._ensure_context(app)
        questions_list = args.get("questions")

        if not questions_list or not isinstance(questions_list, list):
            return "Error: Invalid or missing 'questions' list."

        validated_questions = []
        for q in questions_list:
            if not isinstance(q, dict):
                continue
            q_text = str(q.get("question_text") or q.get("question") or "").strip()
            options = q.get("options")
            if not q_text or not isinstance(options, list):
                continue
            validated_questions.append({
                "question_text": q_text,
                "options": [str(opt) for opt in options]
            })

        if not validated_questions:
            return "Error: Invalid or missing 'questions' list."

        if ctx.app and hasattr(ctx.app, "push_screen"):
            try:
                from widgets.screens.ask_user import AskUserWizardScreen
                screen = AskUserWizardScreen(validated_questions)
                loop = asyncio.get_running_loop()
                future = loop.create_future()

                def on_dismiss(result):
                    if not future.done():
                        future.set_result(result)

                ctx.app.push_screen(screen, callback=on_dismiss)
                try:
                    res = await future
                finally:
                    if getattr(screen, "is_mounted", False):
                        try:
                            screen.dismiss("cancelled")
                        except Exception:
                            pass

                if isinstance(res, str) and res.strip() and res != "cancelled":
                    return res
                return "Cancelled by user."
            except asyncio.CancelledError:
                return "Cancelled by user."
            except Exception as e:
                return f"Error prompting user: {e}"
        return "Error: App instance not available."



