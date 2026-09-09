import asyncio
import json
import re
from typing import Any, Dict, List, Tuple

from johnston.core.domain.defaults.config import (
    DEFAULT_COMPACTION_SUMMARIZE_RATIO,
    DEFAULT_CONTEXT_LIMIT,
    DEFAULT_MAX_TOKENS,
)
from johnston.core.domain.defaults.prompts import (
    COMPACTION_CREATE_HEADER,
    COMPACTION_SUMMARY_TEMPLATE,
    COMPACTION_UPDATE_HEADER,
)
from johnston.core.domain.policies.messages import is_checkpoint_message, is_system_note
from johnston.core.domain.policies.models_catalog import catalog, get_context_window
from johnston.core.infrastructure.llm.base.compaction.helpers import (
    CHECKPOINT_CLOSE_TAG,
    CHECKPOINT_OPEN_TAG,
    DEFAULT_SUMMARY_TOKEN_BUDGET,
    _clean_plan_items,
    _sanitize_summary_text,
    _strip_checkpoint,
    _summary_signature,
    _validate_summary_shape,
    _wrap_checkpoint,
    collect_user_messages,
    extract_plan_from_history,
    resolve_auto_compact_limit,
    should_compact,
)
from johnston.core.infrastructure.llm.models.base import build_stream_kwargs, normalize_tool_arguments_str
from johnston.core.infrastructure.runtime.token_util import estimate_message_tokens, estimate_tokens


class CompactionMixin:
    """Mixin providing context-window properties, history sanitization, and compaction for BaseAgent."""

    @property
    def context_limit(self) -> int:
        return catalog.get_context_limit(self.provider_key, self.model)

    @property
    def context_window(self) -> str:
        return get_context_window(self.provider_key, self.model)

    def _set_history(self, history: List[Dict[str, Any]]) -> None:
        """Replace self.history wholesale and recompute the token accumulator.

        Used on every full-history replacement (sanitize, compaction, truncate,
        turn start) so the accumulator never drifts. The O(history) recompute is
        paid once per replacement instead of once per tool step.
        """
        self.history = history
        self._history_tokens = estimate_tokens(history)
        self._history_ident = id(self.history)
        self._history_len = len(self.history)

    def _append_history(self, msg: Dict[str, Any]) -> None:
        """Append one message to self.history, adding only its token estimate.

        The single-message estimate is cheap and cache-friendly, avoiding a full
        O(history) re-walk per tool step.
        """
        self.history.append(msg)
        self._history_tokens = getattr(self, "_history_tokens", 0) + estimate_message_tokens(msg)
        self._history_len = getattr(self, "_history_len", 0) + 1

    def _current_history_tokens(self) -> int:
        """Return the accumulator, self-healing if history was mutated directly.

        Direct external mutations (e.g. ``agent.history.append(...)`` or a
        wholesale assignment outside this module) change the list identity or
        length; the guard catches those and recomputes once so callers always
        observe an exact ``estimate_tokens(self.history)``. Falls back to a full
        recompute when the accumulator was never initialized (e.g. a bare mixin).
        """
        if (
            getattr(self, "_history_ident", None) != id(self.history)
            or getattr(self, "_history_len", None) != len(self.history)
        ):
            self._history_tokens = estimate_tokens(self.history)
            self._history_ident = id(self.history)
            self._history_len = len(self.history)
        return getattr(self, "_history_tokens", 0)

    def truncate_history_to_user_message(self, user_msg_index: int) -> None:
        """Truncates conversation history to immediately before the specified user message index (0-indexed).

        The index counts UI-visible user turns only: compaction checkpoints
        (``<compaction_checkpoint>``) and interruption notes
        (``<system_note kind="...">``) are not user turns and never counted.
        When the requested turn is not found in history (it lives in a
        compacted region), history is fully cleared so the model cannot
        remember rolled-back turns.
        """
        if user_msg_index <= 0 or not self.history:
            self.clear_history()
            return

        user_count = 0
        cutoff_idx = len(self.history)
        for idx, msg in enumerate(self.history):
            if msg.get("role") != "user":
                continue
            if is_checkpoint_message(msg) or is_system_note(msg):
                continue
            if user_count == user_msg_index:
                cutoff_idx = idx
                break
            user_count += 1

        if user_count >= user_msg_index:
            kept = self.history[:cutoff_idx]
            self._set_history(
                [
                    m
                    for m in kept
                    if not (
                        m.get("role") == "user"
                        and is_system_note(m)
                    )
                ]
            )
        else:
            self.clear_history()

        sys_tok = getattr(self, "_last_sys_tokens", 0)
        hist_tok = self._current_history_tokens() if self.history else 0
        self.last_context_tokens = sys_tok + hist_tok

    def sanitize_history_for_model(self, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Adapts and normalizes session history for the active provider & model.
        Ensures seamless model switching across different providers and capabilities.
        Guarantees strict LLM wire contract compliance:
        - Filters invalid message objects and roles
        - Ensures every assistant tool_call has matching tool response messages before subsequent user/assistant messages
        - Injects synthetic tool cancellation results for missing/interrupted tool calls
        - Normalizes orphaned tool responses without prior assistant tool calls to user role
        """
        if not history:
            return []

        # Pass 1: Map all valid tool_call_ids that have tool responses in history
        tool_responses_by_id = set()
        for msg in history:
            if isinstance(msg, dict) and msg.get("role") == "tool":
                tc_id = msg.get("tool_call_id")
                if tc_id:
                    tool_responses_by_id.add(tc_id)

        sanitized = []
        known_tool_call_ids = set()

        i = 0
        n = len(history)

        while i < n:
            msg = history[i]
            if not isinstance(msg, dict):
                i += 1
                continue
            role = msg.get("role")
            if role not in ("user", "assistant", "tool", "system"):
                i += 1
                continue

            item = dict(msg)

            if role == "assistant":
                if "reasoning_content" not in item or item.get("reasoning_content") is None:
                    item["reasoning_content"] = ""
                tool_calls = item.get("tool_calls")
                if tool_calls and isinstance(tool_calls, list):
                    valid_calls = []
                    valid_tc_ids = set()
                    missing_tool_call_ids = []
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            tc_id = tc.get("id")
                            if tc_id:
                                known_tool_call_ids.add(tc_id)
                                valid_tc_ids.add(tc_id)
                                tc_clean = dict(tc)
                                fn_obj = tc.get("function")
                                if isinstance(fn_obj, dict):
                                    raw_args = normalize_tool_arguments_str(fn_obj.get("arguments", "{}"))
                                    fn_clean = dict(fn_obj)
                                    fn_clean["arguments"] = raw_args
                                    tc_clean["function"] = fn_clean
                                valid_calls.append(tc_clean)
                                if tc_id not in tool_responses_by_id:
                                    fn_name = (
                                        fn_obj.get("name")
                                        if isinstance(fn_obj, dict)
                                        else (tc.get("name") or "tool")
                                    )
                                    missing_tool_call_ids.append((tc_id, fn_name))

                    item["tool_calls"] = valid_calls
                    sanitized.append(item)
                    i += 1

                    # Collect contiguous tool responses that belong to THIS assistant message
                    while i < n and isinstance(history[i], dict) and history[i].get("role") == "tool":
                        t_item = dict(history[i])
                        tc_id = t_item.get("tool_call_id")
                        if tc_id and tc_id in valid_tc_ids:
                            sanitized.append(t_item)
                            i += 1
                        else:
                            break

                    # Inject synthetic tool responses for any missing tool_call_ids in this assistant message
                    for missing_id, fn_name in missing_tool_call_ids:
                        sanitized.append(
                            {
                                "role": "tool",
                                "tool_call_id": missing_id,
                                "name": fn_name,
                                "content": f"[interrupted | tool {fn_name}]",
                            }
                        )
                        known_tool_call_ids.add(missing_id)

                    continue

            elif role == "tool":
                tc_id = item.get("tool_call_id")
                if tc_id and tc_id not in known_tool_call_ids:
                    item = {
                        "role": "user",
                        "content": f"[Tool Output ({item.get('name', 'tool')}): {item.get('content', '')}]",
                    }

            if role == "user":
                raw_content = item.get("content")
                if isinstance(raw_content, str):
                    if not raw_content.strip():
                        # A user message with empty content is invalid on the OpenAI
                        # wire contract (400 "user message must have content"). Drop it.
                        i += 1
                        continue
                elif raw_content is None:
                    i += 1
                    continue

            sanitized.append(item)
            i += 1

        return sanitized

    async def _compact_messages_if_needed(
        self,
        messages: List[Dict[str, Any]],
        sys_overhead: int,
        threshold: int,
    ) -> Tuple[List[Dict[str, Any]], bool, str]:
        if len(messages) > 1:
            # self.history == messages[1:] is maintained by the stream loop, so the
            # accumulator replaces the per-step O(history) walk + thread hop here.
            history_tokens = self._current_history_tokens()
        else:
            history_tokens = 0
        if not should_compact(len(messages) - 1, sys_overhead, history_tokens, threshold):
            # NOTE: do NOT clobber last_context_tokens here. When a step reports
            # real prompt_tokens (API usage), the footer's context_used reflects
            # the true context size; overwriting it with the heuristic
            # estimate_tokens() on every non-compacting tool step made the
            # counter oscillate on multilingual sessions (e.g. "65k" -> "37k").
            return messages, False, ""

        self._set_history(messages[1:])
        success, msg = await self.compact_history()
        if not success:
            return messages, False, msg

        compacted_history = await asyncio.to_thread(self.sanitize_history_for_model, self.history)
        return [{"role": "system", "content": messages[0]["content"]}] + compacted_history, True, msg

    async def compact_history(self) -> Tuple[bool, str]:
        """Compacts conversation history into a single canonical checkpoint.

        The summarizer runs against the full system prompt (so it sees the same
        role/rules/skills) but produces structured Markdown with mandatory
        sections. The output is sanitized (instruction-shaped text stripped),
        shape-validated (required sections present), wrapped in the canonical
        envelope with explicit "historical context only" framing, and inserted
        as a single user message at the head of the preserved history.
        """
        if len(self.history) <= 4:
            return False, "History is too short to compact (<= 4 messages)"

        try:
            from johnston.core.infrastructure.llm.base.tools import build_prompt_context_async

            sys_prompt, all_tools, sys_tokens = await build_prompt_context_async(self)

            raw_tokens_before = sys_tokens + self._current_history_tokens()
            api_context = getattr(self, "last_context_tokens", 0)
            if api_context > 0 and raw_tokens_before > 0:
                tokens_before = api_context
                scale_factor = api_context / raw_tokens_before
            else:
                tokens_before = raw_tokens_before
                scale_factor = 1.0

            # Preserved recent context tail: prefer a real user turn within
            # the last few messages; fall back to a hard cutoff so we always
            # make forward progress even on long tool-only tails.
            split_idx = None
            min_tail_idx = max(1, len(self.history) - 6)
            max_tail_idx = max(1, len(self.history) - 2)

            for idx in range(min_tail_idx, max_tail_idx + 1):
                if (
                    self.history[idx].get("role") == "user"
                    and not is_checkpoint_message(self.history[idx])
                    and not is_system_note(self.history[idx])
                ):
                    split_idx = idx
                    break

            if split_idx is None or split_idx <= 0:
                split_idx = max(1, len(self.history) - 4)

            recent_tail = self.history[split_idx:]

            # Extract previous summary for incremental updating if present.
            # The strict parser rejects malformed checkpoints: those become
            # "no previous summary" rather than being fed back in.
            previous_summary = None
            for msg in self.history:
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content_str = str(msg.get("content") or "")
                    if CHECKPOINT_OPEN_TAG in content_str and CHECKPOINT_CLOSE_TAG in content_str:
                        previous_summary = _strip_checkpoint(content_str)
                        break

            # Budget guard: if history itself exceeds the configurable
            # llm.compaction_summarize_ratio of the context limit, trim the
            # oldest items from the front.
            try:
                from johnston.core.infrastructure.config.settings import get_settings

                summarize_ratio = get_settings().llm.compaction_summarize_ratio
            except Exception:
                summarize_ratio = DEFAULT_COMPACTION_SUMMARIZE_RATIO
            limit_for_compaction = getattr(self, "context_limit", DEFAULT_CONTEXT_LIMIT)
            compact_limit = resolve_auto_compact_limit(self)
            if compact_limit is not None and compact_limit > 0:
                limit_for_compaction = min(limit_for_compaction, compact_limit)
            max_summarize_tokens = int(limit_for_compaction * summarize_ratio)
            available_tokens = max(0, max_summarize_tokens - sys_tokens)

            # Estimate tokens on individual messages and slice in a single pass from the tail
            start_idx = 0
            total_tokens = 0
            for i in range(len(self.history) - 1, -1, -1):
                msg_tokens = estimate_tokens(self.history[i])
                if total_tokens + msg_tokens > available_tokens:
                    start_idx = i + 1
                    break
                total_tokens += msg_tokens

            trimmed_history = self.history[start_idx:]
            # Native history serialization for summarizer (preserves exact KV prompt cache & tool structures like Codex)
            sanitized_history_to_compact = await asyncio.to_thread(self.sanitize_history_for_model, trimmed_history)

            # Build the summarizer prompt. Tool schemas are passed to the
            # summarizer so it can preserve tool-result anchors faithfully;
            # the summarizer is told (via the absence of any role/task
            # instructions in this user prompt) to treat them as facts to
            # record, not as actions to take.
            summary_template = COMPACTION_SUMMARY_TEMPLATE.format(
                summary_token_budget=DEFAULT_SUMMARY_TOKEN_BUDGET
            )
            if previous_summary:
                prompt_header = COMPACTION_UPDATE_HEADER.format(previous_summary=previous_summary)
            else:
                prompt_header = COMPACTION_CREATE_HEADER

            compaction_user_prompt = (
                f"{prompt_header}{summary_template}\n\n"
                "Generate the structured context handoff summary now based on the conversation history."
            )

            compact_messages = (
                [{"role": "system", "content": sys_prompt}]
                + sanitized_history_to_compact
                + [{"role": "user", "content": compaction_user_prompt}]
            )

            summary_text = ""
            last_err = None
            tools_payload = all_tools if all_tools else None
            try:
                from johnston.core.infrastructure.llm.providers import get_adapter

                adapter = get_adapter(getattr(self, "api_type", "openai"))
                stream_kwargs = build_stream_kwargs(
                    self,
                    messages=compact_messages,
                    tools=tools_payload,
                    max_tokens=getattr(self, "max_tokens", DEFAULT_MAX_TOKENS) or DEFAULT_MAX_TOKENS,
                )

                if hasattr(self, "_stream_response_with_retry"):
                    summary_text, _ = await self._stream_response_with_retry(adapter, stream_kwargs)
                else:
                    chunks = []
                    async for tag, payload in adapter.stream_chat(**stream_kwargs):
                        if tag == "adapter_text" and payload:
                            chunks.append(payload)
                    summary_text = "".join(chunks).strip()
            except Exception as stream_e:
                last_err = str(stream_e)
                summary_text = ""

            summary_text = (summary_text or "").strip()
            if not summary_text:
                err_suffix = f": {last_err}" if last_err else " (provider returned no content)"
                return False, f"Failed to generate summary{err_suffix}"

            # Defense in depth: strip instruction-shaped content the
            # summarizer may have emitted despite the prompt forbidding it.
            sanitized_summary = _sanitize_summary_text(summary_text)

            # Validate shape; reject malformed output rather than persisting it.
            ok, reason = _validate_summary_shape(sanitized_summary)
            if not ok:
                return False, f"Failed to generate summary: invalid_shape ({reason})"

            # Account for summarizer tokens and cost in cumulative session metrics
            compact_in = estimate_tokens(compact_messages)
            compact_out = estimate_tokens(sanitized_summary)
            self._accumulate_usage(prompt_tokens_est=compact_in, output_tokens_est=compact_out)

            # Preserve active plan in checkpoint if available: prefer domain session.plan
            sess = getattr(self, "session", None)
            active_plan = getattr(sess, "plan", None) if sess is not None else None
            if not active_plan and sess is not None:
                active_plan = getattr(sess, "current_plan", None)
            if not active_plan:
                active_plan = getattr(self, "current_plan", None)
            if not active_plan and hasattr(self, "history"):
                active_plan = extract_plan_from_history(self.history)

            if active_plan:
                clean_items = _clean_plan_items(active_plan)
                if clean_items and any(p.get("status") in ("in_progress", "pending") for p in clean_items):
                    plan_json = json.dumps(clean_items, indent=2)
                    plan_block = f"\n\n### Plan\n```json\n{plan_json}\n```"
                    if re.search(r"(?m)^### Plan\b", sanitized_summary):
                        sanitized_summary = re.sub(
                            r"(?m)^### Plan\b.*?(?=\n### |\Z)",
                            lambda _: plan_block.strip(),
                            sanitized_summary,
                            flags=re.DOTALL,
                        )
                    else:
                        sanitized_summary = sanitized_summary.strip() + plan_block

            checkpoint_content = _wrap_checkpoint(sanitized_summary)
            checkpoint_item = {"role": "user", "content": checkpoint_content}

            # Collect preserved user messages
            preserve_root = getattr(self, "preserve_root_prompt", None)
            if preserve_root is None:
                preserve_root = getattr(self, "is_subagent", False)
            preserved_users = collect_user_messages(self.history, preserve_root_prompt=preserve_root)

            # Avoid duplicate user messages that are already in recent_tail.
            # Use content signature (not id()) so dedup survives sanitize
            # re-allocation of message dicts.
            tail_sigs = {sig for m in recent_tail if (sig := _summary_signature(m.get("content")))}
            preserved_prefix = [
                m
                for m in preserved_users
                if not (sig := _summary_signature(m.get("content"))) or sig not in tail_sigs
            ]

            new_history = preserved_prefix + [checkpoint_item] + recent_tail
            sanitized_new_history = await asyncio.to_thread(self.sanitize_history_for_model, new_history)
            self._set_history(sanitized_new_history)
            raw_tokens_after = sys_tokens + self._current_history_tokens()
            tokens_after = max(1, round(raw_tokens_after * scale_factor))
            self.last_context_tokens = tokens_after

            from johnston.core.domain.ports.tool_registry import reset_tool_circuit_breakers

            sid = (
                getattr(self, "session_id", None)
                or getattr(getattr(self, "session", None), "id", None)
                or getattr(getattr(self, "host", None), "current_session_id", None)
            )
            reset_tool_circuit_breakers(sid)

            from johnston.core.domain.policies.models_catalog import format_context_tokens

            def _fmt(t: int) -> str:
                return f"{t:,}" if t < 10000 else format_context_tokens(t)

            b_str = _fmt(tokens_before)
            a_str = _fmt(tokens_after)

            return True, f"History compacted successfully ({b_str} → {a_str} tokens)"
        except Exception as e:
            return False, f"Compaction error: {e}"
