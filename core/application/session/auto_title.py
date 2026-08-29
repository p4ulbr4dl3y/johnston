"""Auto-titling use-case for chat sessions."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional

from core.domain.defaults.config import (
    DEFAULT_AUTO_TITLE,
    DEFAULT_AUTO_TITLE_MAX_LEN,
    DEFAULT_AUTO_TITLE_MAX_TOKENS,
    DEFAULT_AUTO_TITLE_TIMEOUT,
)
from core.domain.entities.session import AgentSession
from core.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)


TITLE_PROMPT = """You are a title generator. You output ONLY a thread title. Nothing else.

<task>
Generate a brief title that would help the user find this conversation later.
Rules:
- MUST use the same language as the user message you are summarizing
- A single line, <=50 characters
- No explanations, no conversation, no quotes, no trailing punctuation
- Keep exact: technical terms, numbers, filenames, HTTP codes
- Never include tool names
</task>

<examples>
"debug 500 errors in production" -> Debugging production 500 errors
"refactor user service" -> Refactoring user service
"why is app.js failing" -> app.js failure investigation
"implement rate limiting" -> Rate limiting implementation
"Напиши скрипт на Python для парсинга логов Nginx" -> Парсинг логов Nginx на Python
"почему падает docker compose" -> Сбои docker compose
</examples>
"""


def clean_heuristic_title(text: str, max_len: int = DEFAULT_AUTO_TITLE_MAX_LEN) -> str:
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
    # Strip think tags if present
    clean = re.sub(r"<think>[\s\S]*?</think>", "", title, flags=re.DOTALL)
    lines = [line.strip() for line in clean.split("\n") if line.strip()]
    clean = lines[0] if lines else ""
    # Strip outer quotes, brackets and backticks
    clean = clean.strip("\"'`«»“”[]()")
    # If the candidate contains sentence boundary (e.g. "Title. Explanation"), take first sentence
    if ". " in clean:
        first_sent = clean.split(". ")[0].strip()
        if len(first_sent) >= 3:
            clean = first_sent
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


def extract_title_from_thought(thought_text: str, max_len: int = 50) -> str:
    """Extract candidate title from reasoning thoughts when text output was empty."""
    if not thought_text:
        return ""
    clean = re.sub(r"<think>[\s\S]*?</think>", "", thought_text, flags=re.DOTALL)
    known_examples = {
        "debugging production 500 errors",
        "refactoring user service",
        "app.js failure investigation",
        "rate limiting implementation",
        "парсинг логов nginx на python",
        "сбои docker compose",
    }
    stop_words = {
        "maybe", "yes", "no", "title", "the", "like", "as", "or", "and", "sure", "ok",
        "only", "nothing", "else", "topic", "none", "true", "false", "null", "undefined",
    }

    def _is_valid_candidate(cand_text: str) -> bool:
        c_low = cand_text.lower()
        if len(cand_text) < 3 or len(cand_text) > max_len:
            return False
        if c_low in known_examples or c_low in stop_words:
            return False
        if any(c_low.startswith(p) for p in ("http", "debug 500", "user message", "generate", "the language", "input", ">", "length:", "count:")):
            return False
        if any(p in c_low for p in ("space (", "space(", "(8) space", " chars", " characters")):
            return False
        if re.search(r"\b[a-zA-Z]\s+[a-zA-Z]\s+[a-zA-Z]\b", cand_text):
            return False
        return True

    # 1. Look for explicit target phrases: e.g. Possible title: "...", Title should be: "..."
    target_patterns = [
        r"(?:possible|suggested|final|candidate|proposed|transform|title|named|like)\s*(?:title)?\s*(?:should be|is|like|as|to)?\s*[:=]?\s*[\"\u00ab\u201c]([^\n\"\u00bb\u201d]{3,60})[\"\u00bb\u201d]",
        r"->\s*[\"\u00ab\u201c]?([^\n\"\u00bb\u201d]{3,60})[\"\u00bb\u201d]?",
    ]
    for pat in target_patterns:
        for m in re.finditer(pat, clean, flags=re.IGNORECASE):
            val = sanitize_title(m.group(1), max_len=max_len)
            if _is_valid_candidate(val):
                return val

    # 2. General double/smart quotes from last to first (require multi-word phrase for general quotes)
    matches = re.findall(r'[\"\u00ab\u201c]([^\n\"\u00bb\u201d]{3,60})[\"\u00bb\u201d]', clean)
    if matches:
        for cand in reversed(matches):
            c = sanitize_title(cand, max_len=max_len)
            if _is_valid_candidate(c) and len(c.split()) >= 2:
                return c
    return ""


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
        auto_title_model = getattr(settings.llm, "auto_title_model", None)
    except Exception:
        auto_title_enabled = DEFAULT_AUTO_TITLE
        configured_timeout = DEFAULT_AUTO_TITLE_TIMEOUT
        auto_title_model = None

    if not auto_title_enabled:
        return None

    effective_timeout = timeout if timeout is not None else configured_timeout
    generated_title = None

    # Resolve target agent and model for title generation
    target_agent = agent
    target_model = getattr(agent, "model", "") if agent else ""

    if auto_title_model:
        raw_atm = str(auto_title_model).strip()
        if "/" in raw_atm:
            p_key, m_name = raw_atm.split("/", 1)
            p_key = p_key.strip().lower()
            m_name = m_name.strip()
            try:
                from core.provider_manager import ProviderManager

                pm = ProviderManager()
                built_agent = pm.create_agent_for_provider(p_key)
                if built_agent is not None:
                    target_agent = built_agent
                    target_model = m_name or getattr(built_agent, "model", "")
            except Exception as e:
                logger.debug("Failed creating auto_title agent for %s: %s", p_key, e)
        elif raw_atm:
            target_model = raw_atm

    # Try LLM generation if target agent is configured
    if target_agent and getattr(target_agent, "api_type", None) and target_model:
        try:
            from core.adapters import get_adapter

            adapter = get_adapter(target_agent.api_type)
            messages = [
                {"role": "system", "content": TITLE_PROMPT},
                {"role": "user", "content": f"Generate a title for this conversation:\n{first_text[:800]}"},
            ]
            stream_kwargs: dict[str, Any] = {
                "base_url": getattr(target_agent, "base_url", ""),
                "api_key": getattr(target_agent, "api_key", ""),
                "model": target_model,
                "messages": messages,
                "max_tokens": DEFAULT_AUTO_TITLE_MAX_TOKENS,
                "thinking_effort": "low",
            }
            if getattr(target_agent, "api_type", "") == "openai":
                client = getattr(target_agent, "_client", None) or getattr(target_agent, "client", None)
                if client is not None:
                    stream_kwargs["client"] = client
                if getattr(target_agent, "headers", None):
                    stream_kwargs["headers"] = target_agent.headers

            async def _call_stream() -> tuple[str, str]:
                text_chunks = []
                thought_chunks = []
                async for tag, payload in adapter.stream_chat(**stream_kwargs):
                    if tag == "adapter_text" and payload:
                        text_chunks.append(payload)
                    elif tag == "adapter_thought" and payload:
                        thought_chunks.append(payload)
                return "".join(text_chunks).strip(), "".join(thought_chunks).strip()

            raw_text, raw_thought = await asyncio.wait_for(_call_stream(), timeout=effective_timeout)
            sanitized = sanitize_title(raw_text)
            if not sanitized and raw_thought:
                sanitized = extract_title_from_thought(raw_thought)
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
