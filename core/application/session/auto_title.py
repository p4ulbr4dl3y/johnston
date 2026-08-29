"""Auto-titling use-case for chat sessions."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional

from core.domain.defaults.config import (
    DEFAULT_AUTO_TITLE,
    DEFAULT_AUTO_TITLE_MAX_TOKENS,
    DEFAULT_AUTO_TITLE_TIMEOUT,
)
from core.domain.entities.session import AgentSession
from core.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)


def clean_heuristic_title(text: str, max_len: int = 45) -> str:
    """Generate a clean single-line fallback title from raw user input text."""
    if not text:
        return ""
    # Strip markdown code fences, headers, bold, links, while preserving inline code text
    clean = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    clean = re.sub(r"`([^`]+)`", r"\1", clean)
    clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
    clean = re.sub(r"[#*~>]+", " ", clean)
    clean = re.sub(r"(?<!\w)_|_(?!\w)", " ", clean)
    clean = " ".join(clean.split())
    if not clean:
        return ""
    if len(clean) <= max_len:
        return clean.strip(".,:;!?- ")

    cut = clean[:max_len]
    r_space = cut.rfind(" ")
    if r_space > 15:
        cut = cut[:r_space]
    return cut.strip(".,:;!?- ") + "..."


def sanitize_title(title: str, max_len: int = 50) -> str:
    """Sanitize LLM-generated title string."""
    if not title:
        return ""
    clean = title.strip()
    # Strip outer quotes and backticks
    clean = clean.strip("\"'`«»“”")
    # Remove leading markdown / title prefixes
    clean = re.sub(r"^[#\-\*\s]+", "", clean)
    clean = re.sub(r"^(title|topic|session title)\s*:\s*", "", clean, flags=re.IGNORECASE)
    clean = " ".join(clean.split())
    clean = clean.strip(".,:;!?- \"'`")
    if len(clean) > max_len:
        cut = clean[:max_len]
        r_space = cut.rfind(" ")
        if r_space > 15:
            cut = cut[:r_space]
        clean = cut.strip(".,:;!?- ") + "..."
    return clean


def extract_first_user_text(session: AgentSession) -> str:
    """Extract the first user prompt text from session messages or agent history."""
    for m in session.messages:
        if isinstance(m, dict) and m.get("type") == "user":
            txt = str(m.get("display_text") or m.get("text", "")).strip()
            if txt:
                return txt
    if session.agent_history:
        for m in session.agent_history:
            if isinstance(m, dict) and m.get("role") == "user":
                content = m.get("content", "")
                if isinstance(content, str) and content.strip():
                    return content.strip()
                if isinstance(content, list):
                    parts = [
                        c.get("text", "")
                        for c in content
                        if isinstance(c, dict) and c.get("type") == "text"
                    ]
                    txt = " ".join(parts).strip()
                    if txt:
                        return txt
    return ""


async def auto_title_session(
    agent: Any,
    session: AgentSession,
    *,
    timeout: Optional[float] = None,
) -> Optional[str]:
    """Generate and set a concise title for the session.

    If session._title is already set (e.g. manually renamed), it is kept untouched.
    Tries fast LLM completion first; falls back to heuristic if LLM is unavailable or fails.
    """
    if getattr(session, "_title", None):
        return session.title

    first_text = extract_first_user_text(session)
    if not first_text:
        return None

    try:
        settings = get_settings()
        auto_title_enabled = getattr(settings.llm, "auto_title", DEFAULT_AUTO_TITLE)
        configured_timeout = getattr(settings.llm, "auto_title_timeout", DEFAULT_AUTO_TITLE_TIMEOUT)
    except Exception:
        auto_title_enabled = DEFAULT_AUTO_TITLE
        configured_timeout = DEFAULT_AUTO_TITLE_TIMEOUT

    if not auto_title_enabled:
        return None

    effective_timeout = timeout if timeout is not None else configured_timeout
    generated_title = None

    # Try LLM generation if agent is configured
    if agent and getattr(agent, "api_type", None) and getattr(agent, "model", None):
        try:
            from core.adapters import get_adapter

            adapter = get_adapter(agent.api_type)
            prompt = (
                "Summarize the main topic of this user prompt into a short title (3 to 5 words, max 40 chars). "
                "Output ONLY the plain title text with no quotes, formatting, or period:\n\n"
                f"{first_text[:800]}"
            )
            messages = [{"role": "user", "content": prompt}]
            stream_kwargs: dict[str, Any] = {
                "base_url": getattr(agent, "base_url", ""),
                "api_key": getattr(agent, "api_key", ""),
                "model": getattr(agent, "model", ""),
                "messages": messages,
                "max_tokens": DEFAULT_AUTO_TITLE_MAX_TOKENS,
            }
            if getattr(agent, "api_type", "") == "openai":
                if getattr(agent, "_client", None) is not None:
                    stream_kwargs["client"] = agent._client
                if getattr(agent, "headers", None):
                    stream_kwargs["headers"] = agent.headers

            async def _call_stream() -> str:
                chunks = []
                async for tag, payload in adapter.stream_chat(**stream_kwargs):
                    if tag == "adapter_text" and payload:
                        chunks.append(payload)
                return "".join(chunks).strip()

            raw_title = await asyncio.wait_for(_call_stream(), timeout=effective_timeout)
            sanitized = sanitize_title(raw_title)
            if sanitized:
                generated_title = sanitized
        except Exception as e:
            logger.debug("Auto-title LLM call skipped/failed: %s", e)

    # Fallback to heuristic if LLM did not produce a title
    if not generated_title:
        generated_title = clean_heuristic_title(first_text)

    if generated_title and not getattr(session, "_title", None):
        session.title = generated_title
        return generated_title

    return session.title or None
