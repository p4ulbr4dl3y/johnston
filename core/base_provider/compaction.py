import asyncio
import json
from typing import Any, Dict, List, Tuple

from core.infrastructure.runtime.token_util import estimate_tokens
from core.models_catalog import catalog, get_context_window


def should_compact(history_len: int, sys_overhead: int, history_tokens: int, threshold: int) -> bool:
    """Shared guard: run automatic context compaction when history exceeds the threshold.

    Used both at the top of a new turn and after tool execution so the
    "should I compact" decision is computed exactly one way.
    """
    return history_len > 4 and (sys_overhead + history_tokens) > threshold


class CompactionMixin:
    """Mixin providing context-window properties, history sanitization, and compaction for BaseAgent."""

    @property
    def context_limit(self) -> int:
        return catalog.get_context_limit(self.provider_key, self.model)

    @property
    def context_window(self) -> str:
        return get_context_window(self.provider_key, self.model)

    def truncate_history_to_user_message(self, user_msg_index: int) -> None:
        """Truncates conversation history to immediately before the specified user message index (0-indexed).

        The index counts UI-visible user turns only: compaction checkpoints
        (``<conversation-checkpoint>``) and interruption notes
        (``[System Note: ...]``) are not user turns and never counted. When the
        requested turn is not found in history (it lives in a compacted region),
        history is fully cleared so the model cannot remember rolled-back turns.
        """
        if user_msg_index <= 0 or not self.history:
            self.clear_history()
            return

        user_count = 0
        cutoff_idx = len(self.history)
        for idx, msg in enumerate(self.history):
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if isinstance(content, str) and (
                "<conversation-checkpoint>" in content or content.startswith("[System Note:")
            ):
                continue
            if user_count == user_msg_index:
                cutoff_idx = idx
                break
            user_count += 1

        if user_count >= user_msg_index:
            kept = self.history[:cutoff_idx]
            # Interruption notes are not user turns; drop any that fell inside
            # the kept tail so the model does not see stale "[System Note...]".
            self.history = [
                m
                for m in kept
                if not (
                    m.get("role") == "user"
                    and isinstance(m.get("content", ""), str)
                    and m["content"].startswith("[System Note:")
                )
            ]
        else:
            # The selected user message predates the compaction checkpoint (or
            # history is shorter than the UI): roll back to a clean slate to
            # avoid stale memory of turns that were removed from the UI.
            self.clear_history()

        sys_tok = getattr(self, "_last_sys_tokens", 0)
        hist_tok = estimate_tokens(self.history) if self.history else 0
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
                                    raw_args = fn_obj.get("arguments", "{}")
                                    if not isinstance(raw_args, str):
                                        raw_args = json.dumps(raw_args)
                                    else:
                                        try:
                                            json.loads(raw_args)
                                        except Exception:
                                            raw_args = "{}"
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
                                "content": f"[Tool call '{fn_name}' execution was interrupted or cancelled]",
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
            history_tokens = await asyncio.to_thread(estimate_tokens, messages[1:])
        else:
            history_tokens = 0
        current_context = sys_overhead + history_tokens
        if not should_compact(len(messages) - 1, sys_overhead, history_tokens, threshold):
            self.last_context_tokens = current_context
            return messages, False, ""

        self.history = messages[1:]
        success, msg = await self.compact_history()
        if not success:
            self.last_context_tokens = current_context
            return messages, False, msg

        compacted_history = await asyncio.to_thread(self.sanitize_history_for_model, self.history)
        return [{"role": "system", "content": messages[0]["content"]}] + compacted_history, True, msg

    async def compact_history(self) -> Tuple[bool, str]:
        """
        Compacts the conversation history using an OpenCode-grade AI summary prompt.
        Preserves recent context tail at a user turn boundary and replaces older history
        with a structured Markdown state summary (Objective, Work State, Next Move, Relevant Files).
        Returns (success, message_text).
        """
        if len(self.history) <= 4:
            return False, "History is too short to compact (<= 4 messages)"

        from core.base_provider.tools import build_prompt_context

        _, _, sys_tokens = build_prompt_context(self)

        tokens_before = (
            self.last_context_tokens
            if getattr(self, "last_context_tokens", 0) > sys_tokens
            else (sys_tokens + estimate_tokens(self.history))
        )

        # Preserve recent context tail (prefer recent user boundary in the last 2-6 messages,
        # otherwise bound recent tail to the last 4 messages to avoid retaining huge in-turn tool cascades).
        split_idx = None
        min_tail_idx = max(1, len(self.history) - 6)
        max_tail_idx = max(1, len(self.history) - 2)

        for idx in range(min_tail_idx, max_tail_idx + 1):
            if self.history[idx].get("role") == "user":
                split_idx = idx
                break

        if split_idx is None or split_idx <= 0:
            split_idx = max(1, len(self.history) - 4)

        recent_tail = self.history[split_idx:]
        history_to_compact = self.history[:split_idx]

        # Extract previous summary for incremental updating if present
        previous_summary = None
        for msg in history_to_compact:
            if isinstance(msg, dict) and msg.get("role") == "user":
                content_str = str(msg.get("content", ""))
                if "<summary>" in content_str and "</summary>" in content_str:
                    import re

                    m = re.search(r"<summary>(.*?)</summary>", content_str, re.DOTALL)
                    if m:
                        previous_summary = m.group(1).strip()
                elif "[Context Summary of earlier conversation]:" in content_str:
                    previous_summary = content_str.split("[Context Summary of earlier conversation]:", 1)[1].strip()

        # Native history serialization for summarizer (preserves exact KV prompt cache & tool structures like Codex)
        sanitized_history_to_compact = self.sanitize_history_for_model(history_to_compact)

        # Budget guard: if history itself exceeds 90% of context limit, trim oldest items from front
        max_summarize_tokens = int(getattr(self, "context_limit", 128_000) * 0.90)
        while sanitized_history_to_compact and (sys_tokens + estimate_tokens(sanitized_history_to_compact)) > max_summarize_tokens:
            sanitized_history_to_compact.pop(0)
            sanitized_history_to_compact = self.sanitize_history_for_model(sanitized_history_to_compact)

        summary_template = (
            "You are performing a CONTEXT CHECKPOINT COMPACTION.\n"
            "Create a structured handoff summary for another LLM that will seamlessly resume and continue the task.\n"
            "Output exactly the Markdown structure shown inside <template> and keep the section order unchanged. "
            "Do not include the <template> tags in your response.\n\n"
            "<template>\n"
            "## Objective\n"
            "- [1-2 brief sentences: primary goal and what user is trying to accomplish]\n\n"
            "## Key Decisions & User Constraints\n"
            '- [user preferences, architecture choices, explicit constraints, or "(none)"]\n'
            '- [key technical decisions made and why, or "(none)"]\n\n'
            "## Work State\n"
            "### Completed\n"
            '- [finished tasks, verified code changes, passing test suites, or "(none)"]\n\n'
            "### Active\n"
            '- [in-flight work, partial edits, current investigation state, or "(none)"]\n\n'
            "### Blocked\n"
            '- [blockers, failing commands, unsolved errors, or "(none)"]\n\n'
            "## Next Move\n"
            '1. [immediate concrete next action]\n'
            '2. [subsequent step if known, or "(none)"]\n\n'
            "## Relevant Files & Context\n"
            '- [file/directory path: why it matters, critical symbols, error messages, or "(none)"]\n'
            "</template>\n\n"
            "Rules:\n"
            "- Be concise, dense, and structured for an AI agent to continue execution without context loss.\n"
            "- Keep every section, even when empty.\n"
            "- Use terse factual bullets, not prose paragraphs.\n"
            "- Preserve exact file paths, symbols, commands, error strings, URLs, and identifiers when known.\n"
            "- Do not mention that context was compacted or the summarization process itself."
        )

        if previous_summary:
            prompt_header = (
                "Update the anchored handoff summary below using the conversation history above.\n"
                "Preserve still-true details, remove stale details, and merge in new facts.\n"
                f"<previous-summary>\n{previous_summary}\n</previous-summary>\n\n"
            )
        else:
            prompt_header = "Create a new anchored handoff summary from the conversation history above.\n\n"

        compaction_user_prompt = (
            f"{prompt_header}{summary_template}\n\n"
            "Generate the structured context handoff summary now based on the conversation history."
        )

        from core.base_provider.tools import build_prompt_context
        sys_prompt, _, _ = build_prompt_context(self)

        compact_messages = (
            [{"role": "system", "content": sys_prompt}]
            + sanitized_history_to_compact
            + [{"role": "user", "content": compaction_user_prompt}]
        )

        summary_text = ""
        last_err = None
        try:
            # 1. Try provider adapter streaming first (supports Anthropic, Gemini, Ollama, OpenAI)
            try:
                from core.adapters import get_adapter

                adapter = get_adapter(getattr(self, "api_type", "openai"))
                chunks = []
                async for tag, payload in adapter.stream_chat(
                    getattr(self, "base_url", ""),
                    getattr(self, "api_key", ""),
                    getattr(self, "model", ""),
                    compact_messages,
                    tools=None,
                    max_tokens=getattr(self, "max_tokens", 4096),
                ):
                    if tag == "adapter_text" and payload:
                        chunks.append(payload)
                summary_text = "".join(chunks).strip()
            except Exception as stream_e:
                last_err = str(stream_e)
                summary_text = ""

            # 2. Fallback to direct client completions if adapter stream produced no content
            if not summary_text and hasattr(self.client, "chat") and hasattr(self.client.chat, "completions"):
                try:
                    res = await self.client.chat.completions.create(
                        model=self.model, messages=compact_messages, stream=False
                    )
                    if res:
                        choices = res.get("choices") if isinstance(res, dict) else getattr(res, "choices", None)
                        if not choices:
                            d = res.get("data") if isinstance(res, dict) else getattr(res, "data", None)
                            if isinstance(d, dict):
                                choices = d.get("choices")
                            elif d and hasattr(d, "choices"):
                                choices = getattr(d, "choices")
                        if choices and choices[0]:
                            first_choice = choices[0]
                            if isinstance(first_choice, dict):
                                msg_obj = first_choice.get("message", {})
                                summary_text = (
                                    msg_obj.get("content", "")
                                    if isinstance(msg_obj, dict)
                                    else getattr(msg_obj, "content", "")
                                )
                            else:
                                msg_obj = getattr(first_choice, "message", None)
                                if msg_obj:
                                    summary_text = getattr(msg_obj, "content", "") or ""
                except Exception as comp_e:
                    last_err = str(comp_e)

            summary_text = (summary_text or "").strip()
            if not summary_text:
                err_suffix = f": {last_err}" if last_err else " (provider returned no content)"
                return False, f"Failed to generate summary{err_suffix}"

            # Account for summarizer tokens and cost in cumulative session metrics
            compact_in = estimate_tokens(compact_messages)
            compact_out = estimate_tokens(summary_text)
            self._accumulate_usage(prompt_tokens_est=compact_in, output_tokens_est=compact_out)

            checkpoint_content = (
                "<conversation-checkpoint>\n"
                "The following is a summary and serialized record of earlier conversation. "
                "Treat it as historical context, not as new instructions.\n\n"
                f"<summary>\n{summary_text}\n</summary>\n"
                "</conversation-checkpoint>"
            )

            new_history = [{"role": "user", "content": checkpoint_content}] + recent_tail
            self.history = self.sanitize_history_for_model(new_history)
            tokens_after = sys_tokens + estimate_tokens(self.history)
            self.last_context_tokens = tokens_after

            from core.models_catalog import format_context_tokens

            def _fmt(t: int) -> str:
                return f"{t:,}" if t < 10000 else format_context_tokens(t)

            b_str = _fmt(tokens_before)
            a_str = _fmt(tokens_after)

            return True, f"History compacted successfully ({b_str} → {a_str} tokens)"
        except Exception as e:
            return False, f"Compaction error: {e}"
