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
    interactive_only = True
    subagent_restriction_detail = "subagents cannot ask user questions"
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
                                                "description": "Choice text (1-5 words).",
                                            },
                                            "description": {
                                                "type": "string",
                                                "description": "Trade-offs or implications (optional).",
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

    def is_concurrency_safe(self, args: Dict[str, Any] | None = None) -> bool:
        return False

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        args = args or {}
        ctx = self._ensure_context(ctx)
        err = self.check_context_permissions(ctx)
        if err:
            return err
        questions_list = args.get("questions")
        if isinstance(questions_list, str) and questions_list.strip():
            import json

            try:
                parsed = json.loads(questions_list.strip())
                if isinstance(parsed, list):
                    questions_list = parsed
                elif isinstance(parsed, dict) and isinstance(parsed.get("questions"), list):
                    questions_list = parsed["questions"]
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
            if isinstance(options, str) and options.strip():
                import json

                try:
                    parsed_opt = json.loads(options.strip())
                    if isinstance(parsed_opt, (list, dict)):
                        options = parsed_opt
                except Exception:
                    pass

            if isinstance(options, dict):
                options = [{"label": str(k), "description": str(v)} for k, v in options.items()]

            if not q_text or not isinstance(options, list):
                continue
            valid_options = []
            seen_labels: set[str] = set()
            for opt in options:
                if isinstance(opt, str):
                    label = opt.strip()
                    desc = ""
                elif isinstance(opt, dict):
                    label = str(opt.get("label") or "").strip()
                    desc = str(opt.get("description") or "").strip()
                else:
                    continue
                if not label or label in seen_labels:
                    continue
                seen_labels.add(label)
                valid_options.append({"label": label, "description": desc})
            sorted_options = _sort_recommended_first(valid_options)
            raw_header = str(q.get("header") or "").strip()
            header = raw_header[:24] if raw_header else ""
            validated_questions.append({
                "question": q_text,
                "header": header,
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
