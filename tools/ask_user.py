import asyncio
from typing import Any, Dict

from core.domain.defaults.errors import ToolResult
from tools.base import BaseTool


def _is_recommended_option(opt: dict) -> bool:
    """Detect a '(Recommended)' marker at the start or end of an option label."""
    s = str(opt.get("label") or "").strip().lower()
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


def _sort_recommended_first(options: list[dict]) -> list[dict]:
    """Stable sort: recommended options float to the top, the rest keep order."""
    return sorted(options, key=lambda o: not _is_recommended_option(o))



class AskUserTool(BaseTool):
    name = "ask_user"
    description = (
        "Ask interactive multiple-choice questions when requirements or design decisions are ambiguous. "
        "Each question should have 2-4 options with concise label and helpful description. "
        "Include '(Recommended)' in the label of suggested choices."
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
                        "description": "List of questions to ask the user (1-4 questions)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question": {"type": "string", "description": "Question text ending with '?'"},
                                "header": {
                                    "type": "string",
                                    "description": "Very short label/tag (e.g. 'Approach', 'Library')",
                                },
                                "is_multi_select": {
                                    "type": "boolean",
                                    "description": "Allow multiple option selections if true",
                                },
                                "options": {
                                    "type": "array",
                                    "description": "Selectable choices (2-4 options, add '(Recommended)' to suggested choice label)",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "label": {
                                                "type": "string",
                                                "description": "Short choice text (1-5 words)",
                                            },
                                            "description": {
                                                "type": "string",
                                                "description": "Explanation of trade-offs or implications",
                                            },
                                        },
                                        "required": ["label"],
                                    },
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
            valid_options = []
            for opt in options:
                if not isinstance(opt, dict):
                    continue
                label = str(opt.get("label") or "").strip()
                if not label:
                    continue
                desc = str(opt.get("description") or "").strip()
                valid_options.append({"label": label, "description": desc})
            sorted_options = _sort_recommended_first(valid_options)
            validated_questions.append({
                "question": q_text,
                "header": str(q.get("header") or "").strip(),
                "is_multi_select": bool(q.get("is_multi_select") or False),
                "options": sorted_options,
            })

        if not validated_questions:
            return ToolResult.error("params", name="questions", detail="missing or invalid")

        if not callable(getattr(ctx.host, "ask_user", None)):
            return ToolResult.error("context", name="app", detail="unavailable")
        try:
            res = await ctx.ask_user(validated_questions)
            if isinstance(res, str) and res.strip().lower() in ("cancelled", "cancelled by user", "cancelled by user."):
                return ToolResult.cancelled(content="cancelled by user", display=res)
            return ToolResult.done(content=res or "", display=res or "")
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
