import asyncio
import re
from typing import Any, Dict

from core.domain.defaults.errors import ToolResult
from tools.base import BaseTool

# Matches a standalone "recommended" marker, optionally wrapped in () or [].
_RECOMMENDED_MARK_RE = re.compile(r"\(recommended\)|\[recommended\]|\brecommended\b", re.IGNORECASE)
# Negated forms ("Not recommended", "non-recommended") must not sort first.
_RECOMMENDED_NEGATION_RE = re.compile(r"(?:\bnot\b|\bnever\b|\bnon-|n't)\s*[\(\[]?\s*$", re.IGNORECASE)


def _is_recommended_option(opt: dict) -> bool:
    """Detect a '(Recommended)' marker at the start or end of an option label.

    Negated occurrences (e.g. "Not recommended") do not count.
    """
    s = str(opt.get("label") or "").strip()
    for match in _RECOMMENDED_MARK_RE.finditer(s):
        prefix = s[: match.start()]
        suffix = s[match.end():]
        if prefix.strip() and suffix.strip():
            continue  # marker in the middle of the label, not a prefix/suffix marker
        if _RECOMMENDED_NEGATION_RE.search(prefix):
            continue
        return True
    return False


def _sort_recommended_first(options: list[dict]) -> list[dict]:
    """Stable sort: recommended options float to the top, the rest keep order."""
    return sorted(options, key=lambda o: not _is_recommended_option(o))



class AskUserTool(BaseTool):
    name = "ask_user"
    description = (
        "Prompt user with an interactive modal to clarify ambiguous requirements or choose implementation options."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Prompt user with an interactive modal to clarify ambiguous requirements or choose implementation options."
            ),
            "description_verbose": (
                "Ask the user 1-4 multiple-choice questions for ambiguous design decisions. "
                "Reserve for genuine forks, NOT routine confirmations.\n\n"
                "Format example:\n"
                "```\n"
                "ask_user(questions=[\n"
                "  {\"question\": \"Which auth strategy?\", \"header\": \"Auth\", \"options\": [\n"
                "    {\"label\": \"JWT (Recommended)\", \"description\": \"Stateless, scales horizontally\"},\n"
                "    {\"label\": \"Session cookies\", \"description\": \"Server-side state, simpler\"}\n"
                "  ]}\n"
                "])\n"
                "```\n\n"
                "Rules:\n"
                "- 1-4 questions per call; each has 2-4 options.\n"
                "- Append `(Recommended)` to the suggested option's label (UI highlights it).\n"
                "- `header` is a short tag (≤12 chars) shown above the question.\n"
                "- `is_multi_select=true` allows multiple selections; comma-separated in output.\n"
                "- User can press Esc to cancel → returns `[cancelled by user]`.\n\n"
                "Subagent behavior: REMOVED from subagent toolset. Use sparingly in main agent — every call "
                "blocks the agent loop until the user answers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "description": "List of 1-4 questions.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question": {
                                    "type": "string",
                                    "description": "Question text ending with '?'.",
                                },
                                "header": {
                                    "type": "string",
                                    "description": "Short tag (≤12 chars) shown above the question.",
                                },
                                "is_multi_select": {
                                    "type": "boolean",
                                    "default": False,
                                    "description": "Allow multiple option selections.",
                                },
                                "options": {
                                    "type": "array",
                                    "description": "2-4 options. Add '(Recommended)' to suggested choice.",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "label": {
                                                "type": "string",
                                                "description": "Short choice text (1-5 words).",
                                            },
                                            "description": {
                                                "type": "string",
                                                "description": "Trade-offs or implications.",
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
            seen_labels: set[str] = set()
            for opt in options:
                if not isinstance(opt, dict):
                    continue
                label = str(opt.get("label") or "").strip()
                if not label or label in seen_labels:
                    continue
                seen_labels.add(label)
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
                return ToolResult.cancelled(content="[cancelled by user]", display=res)
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
