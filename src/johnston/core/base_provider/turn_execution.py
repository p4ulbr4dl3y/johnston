import asyncio
import logging
from typing import Any, AsyncGenerator, Dict, List, Tuple

from johnston.core.base_provider.compaction import format_compaction_title
from johnston.core.domain.defaults.errors import ToolResult
from johnston.core.infrastructure.adapters.base import (
    extract_image_payload,
    normalize_tool_arguments_str,
    parse_tool_call_args,
)
from johnston.core.roles.role_registry import RoleRegistry

logger = logging.getLogger("johnston.core.base_provider.agent")

__all__ = [
    "TurnExecutionMixin",
]


class TurnExecutionMixin:
    """Mixin handling tool call dispatch, batching, and execution for BaseAgent."""

    async def _execute_single_tool(self, tc: dict, role_def: Any) -> tuple[str, Any, Any]:
        """Execute a single tool call and return (tool_call_id, display_result, resolved_tool_result)."""
        t_id = tc["id"]
        t_name = tc["name"]
        raw_args = tc.get("arguments", "{}")
        _, args = parse_tool_call_args({"function": {"name": t_name, "arguments": raw_args}})

        policy_err = self._tool_policy_error(t_name, role_def)
        if policy_err:
            tool_result: Any = policy_err
        else:
            tool_result = None

        if tool_result is None:
            if getattr(self, "tool_executor", None):
                try:
                    tool_result = await self.tool_executor(t_name, args, self)
                except Exception as e:
                    tool_result = ToolResult.error("execute", detail=str(e), name=t_name)
            else:
                tool_result = ToolResult.error("error", "tool_executor not provided", t_name)

        resolved = await self._normalize_tool_result(tool_result)

        source_for_image = resolved.content if isinstance(tool_result, ToolResult) else tool_result
        display_result = tool_result
        parsed_img = extract_image_payload(source_for_image)
        if parsed_img is not None and parsed_img.get("type") == "image":
            display_result = parsed_img.get("summary", f"[Image file: {parsed_img.get('path')}]")
        elif isinstance(tool_result, ToolResult):
            display_result = (
                resolved.display
                if (resolved.display is not None and resolved.display.strip() != "")
                else (resolved.content or "")
            )

        return t_id, display_result, resolved

    async def _execute_tool_calls(
        self,
        messages: List[Dict[str, Any]],
        tool_calls_dict: Dict[int, Dict[str, Any]],
        full_assistant_parts: List[str],
        active_thought_parts: List[str],
        threshold: int,
        result: Dict[str, Any],
    ) -> AsyncGenerator[Tuple[Any, ...], None]:
        """Execute a step's tool calls, append results to history, and compact.

        Yields the ``tool`` / ``tool_result`` / compaction-divider events and
        writes the (possibly compaction-replaced) ``messages`` list into
        ``result`` before returning (an async generator cannot carry a return
        value).
        """
        # Execute tool calls in the order the model emitted them. Dict insertion
        # order usually matches, but delta tool_calls can arrive out of order on
        # some providers, so sort explicitly by the tool-call index key.
        ordered_calls = [tool_calls_dict[k] for k in sorted(tool_calls_dict.keys())]

        cleaned_tool_calls = []
        for tc in ordered_calls:
            raw_args = normalize_tool_arguments_str(tc.get("arguments", "{}"))
            cleaned_tool_calls.append(
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": raw_args},
                }
            )

        assistant_tool_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": "".join(full_assistant_parts) or None,
            "tool_calls": cleaned_tool_calls,
            "reasoning_content": "".join(active_thought_parts),
        }
        messages.append(assistant_tool_msg)
        self._append_history(assistant_tool_msg)

        current_role = getattr(self, "role", "worker").lower()
        role_def = RoleRegistry.get_instance().get_role(current_role)

        # Partition tool calls into batches: consecutive concurrency-safe
        # tools run in parallel via asyncio.gather; mutating/barrier tools
        # execute sequentially.
        batches: list[tuple[bool, list[tuple[dict, Any]]]] = []
        for tc in ordered_calls:
            raw_args = tc.get("arguments", "{}")
            _, parsed_args = parse_tool_call_args({"function": {"name": tc["name"], "arguments": raw_args}})
            is_safe = self._is_tool_concurrency_safe(
                tc["name"], parsed_args if isinstance(parsed_args, dict) else None
            )
            if batches and batches[-1][0] and is_safe:
                batches[-1][1].append((tc, parsed_args))
            else:
                batches.append((is_safe, [(tc, parsed_args)]))

        for is_safe, batch in batches:
            if is_safe and len(batch) > 1:
                # Concurrent batch: announce all tool cards first
                for tc, args in batch:
                    t_name = tc["name"]
                    target = (
                        (args.get("path") or args.get("command") or args.get("url") or "")
                        if isinstance(args, dict)
                        else ""
                    )
                    yield ("tool", t_name, str(target), args, tc.get("id"))

                # Execute concurrently and preserve original order
                batch_results = await asyncio.gather(*(self._execute_single_tool(tc, role_def) for tc, _ in batch))
                for (tc, _), (t_id, display_result, resolved) in zip(batch, batch_results, strict=True):
                    cur_name = tc.get("name", "")
                    tid = getattr(resolved, "task_id", None) or getattr(resolved, "background_task_id", None)
                    log_p = getattr(resolved, "log_path", None)
                    yield (
                        "tool_result",
                        display_result,
                        "",
                        resolved.is_error,
                        resolved.status,
                        resolved.returncode,
                        t_id,
                        tid,
                        log_p,
                    )
                    messages.append(
                        {"role": "tool", "name": cur_name, "tool_call_id": t_id, "content": resolved.content or ""}
                    )
                    self._append_history(messages[-1])
            else:
                # Sequential execution (single tool or mutating barrier)
                for tc, args in batch:
                    t_name = tc["name"]
                    target = (
                        (args.get("path") or args.get("command") or args.get("url") or "")
                        if isinstance(args, dict)
                        else ""
                    )
                    yield ("tool", t_name, str(target), args, tc.get("id"))

                    t_id, display_result, resolved = await self._execute_single_tool(tc, role_def)
                    tid = getattr(resolved, "task_id", None) or getattr(resolved, "background_task_id", None)
                    log_p = getattr(resolved, "log_path", None)
                    yield (
                        "tool_result",
                        display_result,
                        "",
                        resolved.is_error,
                        resolved.status,
                        resolved.returncode,
                        t_id,
                        tid,
                        log_p,
                    )
                    messages.append(
                        {"role": "tool", "name": t_name, "tool_call_id": t_id, "content": resolved.content or ""}
                    )
                    self._append_history(messages[-1])

        # self.history was maintained incrementally via _append_history
        # throughout this iteration (queued users, assistant msg, tool
        # results), so no full messages[1:] copy is needed here. Only a
        # mid-loop compaction (below) replaces the prefix and forces a
        # wholesale resync.
        compacted_count = getattr(self, "_compacted_count_this_turn", 0)
        if compacted_count < 10:
            messages, compacted_in_loop, compact_msg = await self._compact_messages_if_needed(
                messages, getattr(self, "_last_sys_tokens", 0), threshold
            )
        else:
            compacted_in_loop, compact_msg = False, ""

        if compacted_in_loop:
            self._compacted_count_this_turn = compacted_count + 1
            # Compaction replaced the messages prefix (self.history is now
            # the compacted history but messages[1:] is a re-sanitization of
            # it); resync the accumulator so self.history == messages[1:]
            # holds for the next step's estimate.
            self._set_history(messages[1:])
            yield ("event_divider", format_compaction_title(compact_msg), "")

        result["messages"] = messages
