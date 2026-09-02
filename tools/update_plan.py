from typing import Any, Dict, List

from core.domain.defaults.errors import ToolResult
from tools.base import BaseTool


class UpdatePlanTool(BaseTool):
    name = "update_plan"
    description = (
        "Update multi-step plan checklist. Rules: "
        "1) Short steps (<=7 words). "
        "2) Exactly one 'in_progress' step at a time. "
        "3) Update BEFORE executing step actions. "
        "4) Do not repeat plan in response text."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "update_plan",
            "parameters": {
                "type": "object",
                "properties": {
                    "explanation": {"type": "string", "description": "Optional reason for plan update"},
                    "plan": {
                        "type": "array",
                        "description": "Full ordered list of all steps",
                        "items": {
                            "type": "object",
                            "properties": {
                                "step": {"type": "string", "description": "Short step title (<=7 words)"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                    "description": "Step status",
                                },
                            },
                            "required": ["step", "status"],
                        },
                    },
                },
                "required": ["plan"],
            },
        },
    }

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        args = args or {}
        ctx = self._ensure_context(ctx)
        raw_plan = args.get("plan")
        explanation = str(args.get("explanation") or "").strip()

        if isinstance(raw_plan, str):
            import json

            try:
                parsed = json.loads(raw_plan)
                if isinstance(parsed, list):
                    raw_plan = parsed
            except Exception:
                pass

        if not raw_plan or not isinstance(raw_plan, list):
            return ToolResult.error("params", name="plan", detail="must be non-empty")

        validated_plan: List[Dict[str, str]] = []
        for item in raw_plan:
            if isinstance(item, str):
                step_text = item.strip()
                status = "pending"
            elif isinstance(item, dict):
                step_text = str(item.get("step") or "").strip()
                status = str(item.get("status") or "pending").strip().lower()
            else:
                continue

            if status not in ("pending", "in_progress", "completed"):
                status = "pending"

            if not step_text:
                continue

            validated_plan.append({"step": step_text, "status": status})

        if not validated_plan:
            return ToolResult.error("params", name="plan", detail="items need 'step'/'status'")

        # Store active plan in app state if app exists and caller is not a subagent
        if not getattr(ctx, "is_subagent", False):
            host = ctx.host
            if host:
                app_target = getattr(host, "app", None) or host
                setattr(host, "current_plan", validated_plan)
                setattr(host, "current_plan_explanation", explanation)
                if app_target is not host:
                    setattr(app_target, "current_plan", validated_plan)
                    setattr(app_target, "current_plan_explanation", explanation)

                on_plan_update = getattr(app_target, "on_plan_update", None) or getattr(host, "on_plan_update", None)
                if callable(on_plan_update):
                    try:
                        on_plan_update(validated_plan, explanation)
                    except Exception:
                        pass
        else:
            host = ctx.host
            if host:
                setattr(host, "current_plan", validated_plan)
                setattr(host, "current_plan_explanation", explanation)
                target_sess = getattr(host, "session", None)
                if target_sess:
                    setattr(target_sess, "current_plan", validated_plan)
                    setattr(target_sess, "current_plan_explanation", explanation)

        completed_count = sum(1 for p in validated_plan if p["status"] == "completed")
        total_count = len(validated_plan)
        exp_part = f" | {explanation}" if explanation else ""
        summary = f"[plan updated | {completed_count}/{total_count} done{exp_part}]"

        return ToolResult.done(content=summary, display=summary)
