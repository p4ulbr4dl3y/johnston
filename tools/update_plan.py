from typing import Any, Dict, List

from tools.base import BaseTool


class UpdatePlanTool(BaseTool):
    name = "update_plan"
    description = (
        "Update the task plan. Provide an optional explanation and a list of plan items, "
        "each with a step and status ('pending', 'in_progress', 'completed'). "
        "At most one step should be in_progress at a time."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "update_plan",
            "parameters": {
                "type": "object",
                "properties": {
                    "explanation": {
                        "type": "string",
                        "description": "Optional explanation for this plan update."
                    },
                    "plan": {
                        "type": "array",
                        "description": "List of plan items",
                        "items": {
                            "type": "object",
                            "properties": {
                                "step": {
                                    "type": "string",
                                    "description": "Task step text (short, 5-7 words)."
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                    "description": "Step status."
                                }
                            },
                            "required": ["step", "status"]
                        }
                    }
                },
                "required": ["plan"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        ctx = self._ensure_context(app)
        raw_plan = args.get("plan")
        explanation = str(args.get("explanation") or "").strip()

        if not raw_plan or not isinstance(raw_plan, list):
            return "Error: 'plan' parameter must be a non-empty list of items."

        validated_plan: List[Dict[str, str]] = []
        for idx, item in enumerate(raw_plan, start=1):
            if not isinstance(item, dict):
                continue
            step_text = str(item.get("step") or item.get("text") or "").strip()
            status = str(item.get("status") or "pending").strip().lower()
            if status not in ("pending", "in_progress", "completed", "done", "todo"):
                status = "pending"
            if status in ("done",):
                status = "completed"
            if status in ("todo",):
                status = "pending"

            if not step_text:
                continue

            validated_plan.append({
                "step": step_text,
                "status": status
            })

        if not validated_plan:
            return "Error: Valid 'plan' items with 'step' and 'status' are required."

        # Store active plan in app state if app exists
        if ctx.app:
            setattr(ctx.app, "current_plan", validated_plan)
            setattr(ctx.app, "current_plan_explanation", explanation)
            on_plan_update = getattr(ctx.app, "on_plan_update", None)
            if callable(on_plan_update):
                try:
                    on_plan_update(validated_plan, explanation)
                except Exception:
                    pass

        completed_count = sum(1 for p in validated_plan if p["status"] == "completed")
        total_count = len(validated_plan)
        summary = f"Plan updated ({completed_count}/{total_count} completed)."
        if explanation:
            summary += f" {explanation}"

        return summary
