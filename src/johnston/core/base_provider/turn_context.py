import asyncio
import hashlib
import json
import logging
import os
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from johnston.core.base_provider.compaction import (
    format_compaction_title,
    resolve_auto_compact_limit,
    should_compact,
)
from johnston.core.base_provider.history_cache import (
    _get_tools_digest,
    sanitize_history_cached,
)
from johnston.core.base_provider.tools import build_prompt_context_async
from johnston.core.domain.defaults.config import DEFAULT_CONTEXT_LIMIT
from johnston.core.infrastructure.adapters.base import image_url_block
from johnston.core.infrastructure.config.settings import get_settings

logger = logging.getLogger("johnston.core.base_provider.agent")

__all__ = [
    "_warmup_mcp_tools",
    "TurnContextMixin",
]


async def _warmup_mcp_tools() -> None:
    """Kick off MCP tool warmup in the background WITHOUT blocking the first
    user turn and WITHOUT cancelling it when that turn wins the race.
    ``ensure_tools_ready_async`` coalesces concurrent callers and returns
    already-cached tools when the warmup task is still running; the prompt
    builder snapshots whatever MCP tools are ready at build time and the
    still-running warmup fills the cache so a later turn picks the rest up.
    A slow server (npx/uvx cold start) never stalls the send path.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    from johnston.core.infrastructure.mcp import get_mcp_manager

    try:
        await get_mcp_manager().ensure_tools_ready_async(max_age=60.0)
    except Exception:
        pass


class TurnContextMixin:
    """Mixin handling turn context preparation and image attachment processing for BaseAgent."""

    async def _process_attachment_image(
        self, att_path: str, error_prefix: str = "Error processing attachment image"
    ) -> Optional[Dict[str, Any]]:
        if not getattr(self, "image_processor", None):
            return None
        try:
            img_data_str = await asyncio.to_thread(self.image_processor, att_path)
            img_dict = json.loads(img_data_str) if isinstance(img_data_str, str) else img_data_str
            if isinstance(img_dict, dict) and img_dict.get("base64"):
                media_type = img_dict.get("media_type", "image/jpeg")
                b64_data = img_dict.get("base64")
                detail_val = img_dict.get("detail", "high")
                return image_url_block(media_type, b64_data, detail_val)
        except Exception as e:
            import johnston.core.base_provider.agent as agent_mod

            agent_mod.logger.warning("%s: %s", error_prefix, e)
        return None

    async def _prepare_turn_context(
        self, user_text: str, attachments: Optional[List[Any]], result: Dict[str, Any]
    ) -> AsyncGenerator[Tuple[Any, ...], None]:
        """Build the full message list for this turn and the compaction threshold.

        Runs MCP warmup, builds the system prompt/tool schema, computes the
        auto-compaction threshold and applies turn-start compaction, assembles
        the user message (attachments become image blocks), and resyncs
        ``self.history`` to ``messages[1:]`` so the incremental token
        accumulator stays exact through the multi-step loop.

        Yields the turn-start compaction events and writes ``messages``,
        ``all_tools`` and ``threshold`` into ``result`` before returning (an
        async generator cannot carry a return value, so the caller reads the
        out-param on ``StopAsyncIteration``).
        """
        await _warmup_mcp_tools()
        sys_prompt, all_tools, sys_tokens = await build_prompt_context_async(self)
        self._last_sys_tokens = sys_tokens

        # Automatic context compaction when total context (system prompt + tools + history)
        # exceeds 75% of the context window, when switching to a smaller model (downshift),
        # or when system prompt/tool schemas changed significantly.
        cur_limit = getattr(self, "context_limit", DEFAULT_CONTEXT_LIMIT)
        settings = get_settings()
        compaction_ratio = settings.llm.compaction_threshold_ratio
        threshold = int(cur_limit * compaction_ratio)
        compact_limit = resolve_auto_compact_limit(self)
        if compact_limit is not None and compact_limit > 0:
            threshold = min(threshold, compact_limit)
        sys_overhead = getattr(self, "_last_sys_tokens", 0) or 0
        history_tokens = self._current_history_tokens() if getattr(self, "history", None) else 0
        total_tokens = sys_overhead + history_tokens

        # 1. Model Downshift detection
        last_limit = getattr(self, "_last_model_limit", None)
        self._last_model_limit = cur_limit
        model_downshift = last_limit is not None and last_limit > cur_limit and total_tokens > cur_limit

        # 2. Instruction / Tool schema hash change detection
        tools_digest = _get_tools_digest(all_tools)
        cur_hash = hashlib.sha256(f"{sys_prompt}:{tools_digest}".encode("utf-8")).hexdigest()
        last_hash = getattr(self, "_last_comp_hash", None)
        self._last_comp_hash = cur_hash
        hash_changed = (
            last_hash is not None
            and last_hash != cur_hash
            and len(self.history) > 4
            and total_tokens > threshold * 0.8
        )

        need_compact = (
            should_compact(len(self.history), sys_overhead, history_tokens, threshold)
            or model_downshift
            or hash_changed
        )
        self._compacted_count_this_turn = 0
        if need_compact:
            yield ("thinking", "Auto-compacting conversation history (context reached threshold)...", "")
            try:
                success, msg = await self.compact_history()
                if success:
                    yield ("event_divider", format_compaction_title(msg), "")
                else:
                    yield ("event_divider", "Compaction Failed", "")
            except Exception as compact_err:
                yield ("thinking", f"Auto-compaction warning: {compact_err}", "")

        sanitized_history = await sanitize_history_cached(self, self.history)
        if attachments:
            att_paths = [getattr(att, "path", str(att)) for att in attachments if getattr(att, "path", str(att))]
            header_parts = []
            if len(att_paths) == 1:
                header_parts.append(f"[Attached: {att_paths[0]}]")
            elif len(att_paths) > 1:
                items_str = "\n".join(f"- {p}" for p in att_paths)
                header_parts.append(f"[Attached:\n{items_str}]")

            if user_text and user_text.strip():
                header_parts.append(user_text.strip())

            text_content = "\n\n".join(header_parts) if header_parts else "What is in this image?"
            user_content: List[Dict[str, Any]] = [{"type": "text", "text": text_content}]
            for att in attachments:
                att_path = getattr(att, "path", str(att))
                img_item = await self._process_attachment_image(att_path)
                if img_item:
                    user_content.append(img_item)
            messages = (
                [{"role": "system", "content": sys_prompt}]
                + sanitized_history
                + [{"role": "user", "content": user_content}]
            )
        else:
            messages = (
                [{"role": "system", "content": sys_prompt}]
                + sanitized_history
                + [{"role": "user", "content": user_text}]
            )

        # Sync self.history to messages[1:] (history sans the system prefix) once
        # per turn so the incremental token accumulator and in-place appends below
        # keep self.history == messages[1:] through the multi-step loop.
        self._set_history(messages[1:])
        result["messages"] = messages
        result["all_tools"] = all_tools
        result["threshold"] = threshold
