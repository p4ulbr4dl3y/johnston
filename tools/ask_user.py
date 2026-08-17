import asyncio
from typing import Any, Dict

from core.domain.defaults.errors import ToolResult
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
                                    "description": "List of selectable options. If recommending an option, mark it with '(Recommended)'.",
                                },
                            },
                            "required": ["question_text", "options"],
                        },
                    }
                },
                "required": ["questions"],
            },
        },
    }

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        args = args or {}
        ctx = self._ensure_context(ctx)
        questions_list = args.get("questions")

        if not questions_list or not isinstance(questions_list, list):
            return ToolResult.error("params", name="questions", detail="missing or invalid")

        validated_questions = []
        for q in questions_list:
            if not isinstance(q, dict):
                continue
            q_text = str(q.get("question_text") or "").strip()
            options = q.get("options")
            if not q_text or not isinstance(options, list):
                continue
            validated_questions.append(
                {"question_text": q_text, "options": _sort_recommended_first([str(opt) for opt in options])}
            )

        if not validated_questions:
            return ToolResult.error("params", name="questions", detail="missing or invalid")

        if not callable(getattr(ctx.host, "ask_user", None)):
            return ToolResult.error("context", name="app", detail="unavailable")
        try:
            return ToolResult.done(await ctx.ask_user(validated_questions))
        except asyncio.CancelledError:
            # A real task cancellation (e.g. the agent run being interrupted): clear
            # any pending wizard state, then re-raise so cooperative cancellation
            # propagates. The model-facing "cancelled by user" string is produced by
            # the host's ask_user() (widgets/mixins/actions.py) for a voluntary Esc.
            if hasattr(ctx.host, "_pending_ask_user"):
                setattr(ctx.host, "_pending_ask_user", None)
            raise
        except Exception as e:
            if hasattr(ctx.host, "_pending_ask_user"):
                setattr(ctx.host, "_pending_ask_user", None)
            return ToolResult.error("prompt", detail=str(e))
