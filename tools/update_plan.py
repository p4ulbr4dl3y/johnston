from typing import Any, Dict, List

from core.domain.defaults.errors import ToolResult
from tools.base import BaseTool


class UpdatePlanTool(BaseTool):
    name = "update_plan"
    description = (
        "Update the task plan. Each item: step + status (pending/in_progress/completed). "
        "Max one step in_progress at a time."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "update_plan",
            "parameters": {
                "type": "object",
                "properties": {
                    "explanation": {"type": "string", "description": "Explanation for this plan update"},
                    "plan": {
                        "type": "array",
                        "description": "List of plan items",
                        "items": {
                            "type": "object",
                            "properties": {
                                "step": {"type": "string", "description": "Task step text (short)"},
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

        if not raw_plan or not isinstance(raw_plan, list):
            return ToolResult.error("params", name="plan", detail="must be non-empty")

        validated_plan: List[Dict[str, str]] = []
        for idx, item in enumerate(raw_plan, start=1):
            if not isinstance(item, dict):
                continue
            step_text = str(item.get("step") or item.get("text") or "").strip()
            status = str(item.get("status") or "pending").strip().lower()
            if status not in ("pending", "in_progress", "completed"):
                status = "pending"

            if not step_text:
                continue

            validated_plan.append({"step": step_text, "status": status})

        if not validated_plan:
            return ToolResult.error("params", name="plan", detail="items need 'step'/'status'")

        # Store active plan in app state if app exists
        if ctx.host:
            setattr(ctx.host, "current_plan", validated_plan)
            setattr(ctx.host, "current_plan_explanation", explanation)
            on_plan_update = getattr(ctx.host, "on_plan_update", None)
            if callable(on_plan_update):
                try:
                    on_plan_update(validated_plan, explanation)
                except Exception:
                    pass

        completed_count = sum(1 for p in validated_plan if p["status"] == "completed")
        total_count = len(validated_plan)
        summary = f"plan updated ({completed_count}/{total_count} completed)"
        if explanation:
            summary += f" {explanation}"

        return ToolResult.done(summary)
