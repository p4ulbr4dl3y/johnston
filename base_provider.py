import os
import json
import time
from typing import AsyncGenerator, Tuple, List, Dict, Any
from openai import AsyncOpenAI

from background_task import BackgroundTask
from tools.registry import execute_tool

class BaseAgent:
    def __init__(self, api_key: str, model: str, base_url: str, system_prompt: str, tools: List[Dict[str, Any]]):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.system_prompt = system_prompt
        self.tools = tools
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        self.history = []
        self.app = None

    def clear_history(self):
        self.history.clear()

    async def stream_steps(self, user_text: str) -> AsyncGenerator[Tuple[str, str, str], None]:
        messages = [{"role": "system", "content": self.system_prompt}] + self.history + [{"role": "user", "content": user_text}]

        t0 = time.time()
        full_assistant_text = ""

        try:
            while True:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=self.tools,
                    stream=True
                )

                tool_calls_dict = {}
                active_thought = ""
                thinking_started = False

                async for chunk in response:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    if hasattr(choice, "delta") and hasattr(choice.delta, "reasoning_content"):
                        reasoning = choice.delta.reasoning_content
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

                if thinking_started:
                    dt = time.time() - t0
                    yield ("thinking_end", f"{dt}", active_thought)
                    thinking_started = False

                if not tool_calls_dict:
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
                        args = json.loads(raw_args)
                    except Exception:
                        args = {}

                    target = args.get("path") or args.get("command") or args.get("question")
                    if not target and "questions" in args and isinstance(args["questions"], list) and args["questions"]:
                        target = args["questions"][0].get("question_text", "")
                    if not target:
                        target = t_name
                    yield ("tool", t_name, target)

                    tool_result = await execute_tool(t_name, args, app=getattr(self, "app", None))
                    yield ("tool_result", tool_result, "")

                    messages.append({
                        "role": "tool",
                        "tool_call_id": t_id,
                        "content": tool_result
                    })

            self.history.append({"role": "user", "content": user_text})
            self.history.append({"role": "assistant", "content": full_assistant_text})

        except Exception as err:
            error_msg = f"**OpenCode API Error:** `{err}`"
            yield ("bot_text", error_msg, "")
