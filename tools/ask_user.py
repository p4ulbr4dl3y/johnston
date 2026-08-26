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
    description = (
        "Ask interactive multiple-choice questions when requirements or design decisions are ambiguous. "
        "Include '(Recommended)' suffix on suggested choices."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "ask_user",
            "parameters": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "description": "List of questions to ask the user",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question": {"type": "string", "description": "Question text"},
                                "options": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": (
                                        "Selectable options (add '(Recommended)' at the end of recommended option)"
                                    ),
                                },
                            },
                            "required": ["question", "options"],
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
        if isinstance(questions_list, str) and questions_list.strip():
            import json

            try:
                parsed = json.loads(questions_list.strip())
                if isinstance(parsed, list):
                    questions_list = parsed
            except Exception:
                pass

        if not isinstance(questions_list, list) or not questions_list:
            return ToolResult.error("params", name="questions", detail="missing or invalid")

        validated_questions = []
        for q in questions_list:
            if not isinstance(q, dict):
                continue
            q_text = str(q.get("question") or "").strip()
            options = q.get("options")
            if not q_text or not isinstance(options, list):
                continue
            validated_questions.append(
                {"question": q_text, "options": _sort_recommended_first([str(opt) for opt in options])}
            )

        if not validated_questions:
            return ToolResult.error("params", name="questions", detail="missing or invalid")

        if not callable(getattr(ctx.host, "ask_user", None)):
            return ToolResult.error("context", name="app", detail="unavailable")
        try:
            res = await ctx.ask_user(validated_questions)
            if isinstance(res, str) and res.strip().lower() in ("cancelled", "cancelled by user", "cancelled by user."):
                return ToolResult.cancelled(content='<cancelled by="user"/>', display=res)

            xml_items = []
            cur_q = None
            for line in (res or "").splitlines():
                if line.startswith("Question:"):
                    cur_q = line.split(":", 1)[1].strip()
                elif line.startswith("Answer:") and cur_q is not None:
                    ans = line.split(":", 1)[1].strip()
                    q_esc = cur_q.replace('"', "&quot;")
                    xml_items.append(f'<q text="{q_esc}">{ans}</q>')
                    cur_q = None
            if xml_items:
                xml_content = "<answers>\n" + "\n".join(xml_items) + "\n</answers>"
            else:
                xml_content = f"<answers>{res}</answers>" if res else "<answers/>"
            return ToolResult.done(content=xml_content, display=res)
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
