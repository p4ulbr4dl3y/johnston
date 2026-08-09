import asyncio
from typing import Any, Dict

from tools.base import BaseTool


def _is_recommended_option(opt: str) -> bool:
    """Detect a '(Recommended)' marker at the start or end of an option label."""
    s = opt.strip().lower()
    return (
        s.startswith("(recommended)")
        or s.startswith("[recommended]")
        or s.startswith("recommended")
        or s.endswith("(recommended)")
        or s.endswith("[recommended]")
        or s.endswith("recommended)")
        or s.endswith("recommended]")
        or s.endswith("recommended")
    )


def _sort_recommended_first(options: list[str]) -> list[str]:
    """Stable sort: recommended options float to the top, the rest keep order."""
    return sorted(options, key=lambda o: not _is_recommended_option(o))


class AskUserTool(BaseTool):
    name = "ask_user"
    description = "Ask the user questions with options and write-in answers. Use when intent is ambiguous."
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
                                    "description": "List of selectable options. If recommending an option, mark it with '(Recommended)'."
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

        # Fallback: a single question passed as {question|question_text, options/choices}.
        single_q_text = args.get("question") or args.get("question_text")
        if (not questions_list or not isinstance(questions_list, list)) and single_q_text:
            questions_list = [{
                "question_text": single_q_text,
                "options": args.get("options") or args.get("choices"),
            }]

        if not questions_list or not isinstance(questions_list, list):
            return "ERR: invalid or missing 'questions' list"

        validated_questions = []
        for q in questions_list:
            if not isinstance(q, dict):
                continue
            q_text = str(q.get("question_text") or q.get("question") or "").strip()
            options = q.get("options")
            if options is None:
                options = q.get("choices")
            if not q_text or not isinstance(options, list):
                continue
            validated_questions.append({
                "question_text": q_text,
                "options": _sort_recommended_first([str(opt) for opt in options])
            })

        if not validated_questions:
            return "ERR: invalid or missing 'questions' list"

        if ctx.app and hasattr(ctx.app, "push_screen"):
            try:
                from widgets.screens.ask_user import AskUserWizardScreen

                loop = asyncio.get_running_loop()
                future = loop.create_future()

                def _show_wizard(questions, answers=None, q_idx=0):
                    screen = AskUserWizardScreen(questions, answers=answers, q_idx=q_idx)

                    def on_dismiss(result):
                        if isinstance(result, dict) and result.get("action") == "minimize":
                            saved_answers = result.get("answers", {})
                            saved_q_idx = result.get("q_idx", 0)
                            setattr(ctx.app, "_pending_ask_user", lambda: _show_wizard(questions, saved_answers, saved_q_idx))
                            if hasattr(ctx.app, "notify"):
                                try:
                                    ctx.app.notify("Questions minimized: type /questions to resume", severity="info")
                                except Exception:
                                    pass
                        else:
                            if hasattr(ctx.app, "_pending_ask_user"):
                                setattr(ctx.app, "_pending_ask_user", None)
                            if not future.done():
                                future.set_result(result)

                    ctx.app.push_screen(screen, callback=on_dismiss)

                _show_wizard(validated_questions)

                try:
                    res = await future
                finally:
                    if hasattr(ctx.app, "_pending_ask_user") and future.done():
                        setattr(ctx.app, "_pending_ask_user", None)

                if isinstance(res, str) and res.strip() and res != "cancelled":
                    return res
                return "OK: cancelled by user"
            except asyncio.CancelledError:
                if hasattr(ctx.app, "_pending_ask_user"):
                    setattr(ctx.app, "_pending_ask_user", None)
                return "OK: cancelled by user"
            except Exception as e:
                if hasattr(ctx.app, "_pending_ask_user"):
                    setattr(ctx.app, "_pending_ask_user", None)
                return f"ERR: prompt failed: {e}"
        return "ERR: app instance not available"



