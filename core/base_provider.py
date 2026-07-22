import json
import time
from typing import Any, AsyncGenerator, Dict, List, Tuple

from openai import AsyncOpenAI

from core.models_catalog import catalog, get_context_window
from core.prompt_builder import PromptBuilder
from core.token_util import estimate_tokens, parse_usage
from tools.registry import execute_tool


class BaseAgent:
    def __init__(self, api_key: str, model: str, base_url: str, system_prompt: str, tools: List[Dict[str, Any]] = None, provider_key: str = "opencode"):
        if tools is None:
            from tools.registry import get_default_tools
            tools = get_default_tools()
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.system_prompt = system_prompt
        self.tools = tools
        self.provider_key = provider_key
        self.client = AsyncOpenAI(api_key=self.api_key or "sk-placeholder", base_url=self.base_url)
        self.history = []
        self.app = None
        self.tokens_input = 0
        self.tokens_output = 0
        self.total_tokens = 0
        self.mode = "build"

    @property
    def context_limit(self) -> int:
        return catalog.get_context_limit(self.provider_key, self.model)

    @property
    def context_window(self) -> str:
        return get_context_window(self.provider_key, self.model)

    def clear_history(self):
        self.history.clear()
        self.tokens_input = 0
        self.tokens_output = 0
        self.total_tokens = 0

    def get_metrics(self) -> Dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "context": self.context_window,
            "context_limit": self.context_limit,
            "cost_usd": getattr(self, "cost_usd", 0.0)
        }

    async def stream_steps(self, user_text: str) -> AsyncGenerator[Tuple[str, str, str], None]:
        agent_mode = getattr(self, "mode", "build")
        allow_task = getattr(self, "allow_task", True)
        builder = PromptBuilder(self.system_prompt, self.tools, mode=agent_mode, allow_task=allow_task)
        sys_prompt = builder.build_system_prompt()
        all_tools = builder.build_tools(provider_key=getattr(self, "provider_key", ""), model_id=getattr(self, "model", ""))

        # Automatic context compaction when history exceeds threshold (75% of context_limit)
        threshold = int(getattr(self, "context_limit", 32000) * 0.75)
        if len(self.history) > 4 and estimate_tokens(self.history) > threshold:
            yield ("thinking", "Auto-compacting conversation history (context reached threshold)...", "")
            try:
                await self.compact_history()
            except Exception as compact_err:
                yield ("thinking", f"Auto-compaction warning: {compact_err}", "")

        messages = [{"role": "system", "content": sys_prompt}] + self.history + [{"role": "user", "content": user_text}]
        t0 = time.time()

        try:
            while True:
                full_assistant_text = ""
                prompt_tokens_est = estimate_tokens(messages)
                step_usage = None

                try:
                    response = await self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        tools=all_tools if all_tools else None,
                        stream=True,
                        stream_options={"include_usage": True}
                    )
                except Exception:
                    response = await self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        tools=all_tools if all_tools else None,
                        stream=True
                    )

                tool_calls_dict = {}
                active_thought = ""
                thinking_started = False

                async for chunk in response:
                    if getattr(chunk, "usage", None):
                        step_usage = parse_usage(chunk.usage)

                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    delta = choice.delta
                    reasoning = (
                        getattr(delta, "reasoning_content", None)
                        or getattr(delta, "reasoning", None)
                        or (getattr(delta, "model_extra", {}) or {}).get("reasoning_content")
                        or (getattr(delta, "model_extra", {}) or {}).get("reasoning")
                    )
                    if reasoning:
                        if not thinking_started:
                            yield ("thinking_start", "Thinking...", "")
                            thinking_started = True
                        active_thought += reasoning
                        yield ("thinking_delta", active_thought, "")

                    delta = choice.delta
                    if delta.content:
                        if thinking_started:
                            dt = time.time() - t0
                            yield ("thinking_end", f"{dt}", active_thought)
                            thinking_started = False
                        full_assistant_text += delta.content
                        yield ("bot_delta", full_assistant_text, "")

                    if delta.tool_calls:
                        if thinking_started:
                            dt = time.time() - t0
                            yield ("thinking_end", f"{dt}", active_thought)
                            thinking_started = False

                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_calls_dict:
                                tool_calls_dict[idx] = {"id": tc.id, "name": "", "arguments": ""}
                            if tc.id:
                                tool_calls_dict[idx]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    tool_calls_dict[idx]["name"] = tc.function.name
                                if tc.function.arguments:
                                    tool_calls_dict[idx]["arguments"] += tc.function.arguments

                if step_usage and step_usage.get("total_tokens", 0) > 0:
                    self.tokens_input += step_usage["prompt_tokens"]
                    self.tokens_output += step_usage["completion_tokens"]
                    self.total_tokens += step_usage["total_tokens"]
                else:
                    output_tokens_est = estimate_tokens(full_assistant_text) + estimate_tokens(active_thought) + estimate_tokens(tool_calls_dict)
                    self.tokens_input += prompt_tokens_est
                    self.tokens_output += output_tokens_est
                    self.total_tokens += (prompt_tokens_est + output_tokens_est)

                if thinking_started:
                    dt = time.time() - t0
                    yield ("thinking_end", f"{dt}", active_thought)
                    thinking_started = False

                if not tool_calls_dict:
                    messages.append({"role": "assistant", "content": full_assistant_text})
                    yield ("bot_text", full_assistant_text, "")
                    break

                assistant_tool_msg = {
                    "role": "assistant",
                    "content": full_assistant_text or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"]
                            }
                        }
                        for tc in tool_calls_dict.values()
                    ]
                }
                messages.append(assistant_tool_msg)

                for tc in tool_calls_dict.values():
                    t_id = tc["id"]
                    t_name = tc["name"]
                    raw_args = tc["arguments"]

                    try:
                        args = json.loads(raw_args) if raw_args.strip() else {}
                    except Exception as json_err:
                        tool_result = f"Error: Tool '{t_name}' received invalid JSON arguments: {json_err}. Raw arguments: {raw_args}"
                        yield ("tool", t_name, t_name)
                        yield ("tool_result", tool_result, "")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": t_id,
                            "content": tool_result
                        })
                        continue

                    if t_name in ("Grep", "Glob"):
                        pattern = args.get("pattern") or args.get("query") or ""
                        path_val = args.get("path") or ""
                        if pattern and path_val:
                            target = f'"{pattern}" in {path_val}'
                        elif pattern:
                            target = f'"{pattern}"'
                        elif path_val:
                            target = path_val
                        else:
                            target = "."
                    elif t_name == "ListDir":
                        target = args.get("path") or "."
                    else:
                        target = args.get("path") or args.get("image_path") or args.get("command") or args.get("question") or args.get("file")
                        if not target and "questions" in args and isinstance(args["questions"], list) and args["questions"]:
                            target = args["questions"][0].get("question_text", "")
                        if not target:
                            str_args = [str(v) for v in args.values() if isinstance(v, (str, int, float)) and v]
                            if str_args:
                                target = str_args[0]
                        if not target:
                            target = t_name
                    yield ("tool", t_name, target)

                    if agent_mode == "plan" and t_name in ("Edit", "Create"):
                        f_path = args.get("path") or args.get("file") or ""
                        if not (f_path.endswith("plan.md") or ".johnston/plans" in f_path or "plans/" in f_path):
                            tool_result = f"Error: Editing code file '{f_path}' is disabled in Plan mode. Save your plan to '.johnston/plans/plan.md' or call PlanExit when finished."
                        else:
                            tool_result = await execute_tool(t_name, args, app=getattr(self, "app", None))
                    else:
                        tool_result = await execute_tool(t_name, args, app=getattr(self, "app", None))

                    tool_ui_result = tool_result
                    tool_content = tool_result

                    if isinstance(tool_result, str) and tool_result.startswith("{") and '"image_url"' in tool_result:
                        try:
                            t_data = json.loads(tool_result)
                            if "image_url" in t_data:
                                tool_ui_result = t_data.get("message", f"[Image Loaded: {t_data.get('path')}]")
                                tool_content = [
                                    {"type": "text", "text": tool_ui_result},
                                    {"type": "image_url", "image_url": {"url": t_data["image_url"]}}
                                ]
                        except Exception:
                            pass

                    yield ("tool_result", tool_ui_result, "")

                    messages.append({
                        "role": "tool",
                        "tool_call_id": t_id,
                        "content": tool_content
                    })

            self.history = messages[1:]

        except Exception as err:
            error_msg = f"**API Error:** `{err}`"
            yield ("bot_text", error_msg, "")

    async def compact_history(self) -> Tuple[bool, str]:
        """
        Compacts the conversation history using an AI summary prompt.
        Leaves the most recent 2 messages intact, and replaces older history with a summary.
        Returns (success, message_text).
        """
        if len(self.history) <= 4:
            return False, "History is too short to compact (<= 4 messages)"

        split_idx = len(self.history) - 2
        while split_idx > 0:
            if self.history[split_idx].get("role") == "user":
                break
            split_idx -= 1

        if split_idx <= 0:
            split_idx = len(self.history) - 2

        recent_tail = self.history[split_idx:]
        history_to_compact = self.history[:split_idx]

        compaction_prompt = (
            "You are an anchored context summarization assistant for coding sessions.\n\n"
            "Summarize the conversation history given in the messages into a concise summary.\n"
            "Preserve:\n"
            "1. Key goals and user constraints\n"
            "2. Important technical facts, decisions, and file paths\n"
            "3. Progress made and pending next steps\n\n"
            "Do NOT answer the conversation. Do NOT mention that you are summarizing.\n"
            "Respond in the same language as the conversation."
        )

        compact_messages = [
            {"role": "system", "content": compaction_prompt}
        ] + history_to_compact + [
            {"role": "user", "content": "Generate the context summary now based on the above history."}
        ]

        try:
            res = await self.client.chat.completions.create(
                model=self.model,
                messages=compact_messages,
                stream=False
            )
            summary_text = res.choices[0].message.content or ""
            if not summary_text.strip():
                return False, "Failed to generate summary"

            new_history = [
                {"role": "user", "content": f"[Context Summary of earlier conversation]:\n{summary_text}"},
                {"role": "assistant", "content": "Understood. Proceeding with summarized context."}
            ] + recent_tail

            self.history = new_history
            return True, f"History compacted successfully (summary size: {len(summary_text)} chars)"
        except Exception as e:
            return False, f"Compaction error: {e}"
