from typing import Any, Dict, Optional
from tools.context import ToolContext

class BaseTool:
    name: str = ""
    description: str = ""

    def _ensure_context(self, ctx_or_app: Any) -> ToolContext:
        if isinstance(ctx_or_app, ToolContext):
            return ctx_or_app
        return ToolContext(ctx_or_app)

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        raise NotImplementedError
