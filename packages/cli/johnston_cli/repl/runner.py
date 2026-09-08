"""Agent execution runner for Johnston CLI REPL turns."""
from __future__ import annotations

import sys
import time
from typing import Any, Optional

from johnston_cli.repl.terminal import format_turn_footer
from johnston_core.domain.defaults.errors import parse_stream_step
from johnston_core.provider_manager import ProviderManager


class AgentReplRunner:
    """Manages LLM provider and streams turns for an interactive session."""

    def __init__(
        self,
        model: Optional[str] = None,
        role: Optional[str] = None,
        pm: Optional[ProviderManager] = None,
    ) -> None:
        self.pm = pm or ProviderManager()
        self.model_override = model
        self.role_name = role or "worker"
        self.agent: Any = None
        self.provider_key: str = ""
        self.model_name: str = ""
        self.total_session_tokens: int = 0
        self._init_agent()

    def _init_agent(self) -> None:
        """Initialize provider and agent instance."""
        self.provider_key = self.pm.get_active_provider_key() or "openai"
        try:
            self.agent = self.pm.create_agent_for_provider(self.provider_key)
        except Exception:
            self.agent = None

        if self.agent is not None:
            if self.model_override:
                self.agent.model = self.model_override
            self.model_name = getattr(self.agent, "model", "default")
        else:
            self.model_name = self.model_override or "default"

    async def run_turn(self, user_prompt: str) -> None:
        """Run a single interactive turn with live text streaming."""
        if not user_prompt.strip():
            return

        start_time = time.perf_counter()
        has_written = False

        try:
            async for step in self.agent.stream_steps(user_prompt):
                parsed = parse_stream_step(step)
                if parsed is None:
                    continue

                event_type = parsed.event_type
                val1 = parsed.val1

                if event_type in ("bot_delta", "delta") and val1:
                    sys.stdout.write(str(val1))
                    sys.stdout.flush()
                    has_written = True
                elif event_type == "bot_text" and val1 and not has_written:
                    sys.stdout.write(str(val1))
                    sys.stdout.flush()
                    has_written = True
                elif event_type == "error":
                    err_msg = str(val1 or "Unknown generation error")
                    sys.stderr.write(f"\n\033[31mError: {err_msg}\033[0m\n")
                    sys.stderr.flush()
        except KeyboardInterrupt:
            sys.stdout.write("\n\033[33m[Generation interrupted]\033[0m\n")
            sys.stdout.flush()
        except Exception as exc:
            sys.stderr.write(f"\n\033[31mError during stream: {exc}\033[0m\n")
            sys.stderr.flush()

        duration_s = max(0.0, time.perf_counter() - start_time)

        # Token accounting from agent turn
        turn_tokens = getattr(self.agent, "last_context_tokens", 0)
        if not turn_tokens:
            turn_tokens = getattr(self.agent, "total_tokens", 0)
        self.total_session_tokens = turn_tokens

        # Render turn summary footer
        display_model = f"{self.provider_key}/{self.model_name}" if self.provider_key else self.model_name
        footer = format_turn_footer(display_model, self.total_session_tokens, duration_s)
        sys.stdout.write(footer)
        sys.stdout.flush()
