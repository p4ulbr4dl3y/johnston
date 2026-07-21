import os
import json
import time
from typing import AsyncGenerator, Tuple, List, Dict, Any
from openai import AsyncOpenAI

from background_task import BackgroundTask
from tools.registry import execute_tool
from token_util import estimate_tokens, parse_usage
from models_dev import get_context_window, catalog
from skill_manager import SkillManager

class BaseAgent:
    def __init__(self, api_key: str, model: str, base_url: str, system_prompt: str, tools: List[Dict[str, Any]], provider_key: str = "opencode"):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.system_prompt = system_prompt
        self.tools = tools
        self.provider_key = provider_key
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        self.history = []
        self.app = None
        self.tokens_input = 0
        self.tokens_output = 0
        self.total_tokens = 0
        self.context_limit = catalog.get_context_limit(self.provider_key, self.model)
        self.context_window = get_context_window(self.provider_key, self.model)
        self.mode = "build"

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
            "context": getattr(self, "context_window", "128k"),
            "context_limit": getattr(self, "context_limit", 128000),
            "cost_usd": getattr(self, "cost_usd", 0.0)
        }

    async def stream_steps(self, user_text: str) -> AsyncGenerator[Tuple[str, str, str], None]:
        from mcp_manager import get_mcp_manager
        mcp_mgr = get_mcp_manager()
        mcp_tools = mcp_mgr.get_active_tools()
        mcp_snippet = mcp_mgr.get_system_prompt_snippet()

        skills_snippet = SkillManager().get_system_prompt_snippet()
        sys_prompt = self.system_prompt
        if skills_snippet:
            sys_prompt = f"{sys_prompt}\n\n{skills_snippet}"
        if mcp_snippet:
            sys_prompt = f"{sys_prompt}\n\n{mcp_snippet}"

        clean_mcp_tools = [
            {"type": t["type"], "function": t["function"]} for t in mcp_tools
        ]
        all_tools = (self.tools or []) + clean_mcp_tools

        agent_mode = getattr(self, "mode", "build")
        if agent_mode == "plan":
            sys_prompt += (
                "\n\n[PLAN MODE ACTIVE]\n"
                "You are in Plan mode. Analyze the codebase, research requirements, and outline a step-by-step implementation plan. "
                "Save your plan in '.tui/plans/plan.md'. Do NOT edit project code files directly while in Plan mode. "
                "When the plan is ready, call the PlanExit tool to propose switching to Build mode."
            )
            plan_tool_schema = {
                "type": "function",
                "function": {
                    "name": "PlanExit",
                    "description": "Signal that planning phase is complete and request switching to build mode to implement the plan.",
                    "parameters": {"type": "object", "properties": {}}
                }
            }
            if not any(t.get("function", {}).get("name") == "PlanExit" for t in all_tools):
                all_tools.append(plan_tool_schema)
        else:
            local_plan = os.path.join(os.getcwd(), ".tui", "plans", "plan.md")
            if os.path.exists(local_plan):
                sys_prompt += f"\n\n[BUILD MODE ACTIVE]\nA plan file exists at '{local_plan}'. Execute the implementation steps defined within it."

        task_tool_schema = {
            "type": "function",
            "function": {
                "name": "Task",
                "description": "Launch a subagent to perform a task. Use subagent_type='explore' for fast codebase search, or 'general' for multi-step tasks. Set background=true to run asynchronously.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Task prompt for the subagent"},
                        "description": {"type": "string", "description": "Short (3-5 words) description"},
                        "subagent_type": {"type": "string", "description": "Type of subagent ('general' or 'explore')"},
                        "background": {"type": "boolean", "description": "Run asynchronously in background"}
                    },
                    "required": ["prompt", "description"]
                }
            }
        }
        if not any(t.get("function", {}).get("name") in ("Task", "task") for t in all_tools):
            all_tools.append(task_tool_schema)

        messages = [{"role": "system", "content": sys_prompt}] + self.history + [{"role": "user", "content": user_text}]

        t0 = time.time()
        full_assistant_text = ""

        try:
            while True:
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
                        if not (f_path.endswith("plan.md") or ".tui/plans" in f_path or "plans/" in f_path):
                            tool_result = f"Error: Editing code file '{f_path}' is disabled in Plan mode. Save your plan to '.tui/plans/plan.md' or call PlanExit when finished."
                        else:
                            tool_result = await execute_tool(t_name, args, app=getattr(self, "app", None))
                    else:
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

    async def compact_history(self) -> Tuple[bool, str]:
        """
        Compacts the conversation history using an AI summary prompt.
        Leaves the most recent 2 messages intact, and replaces older history with a summary.
        Returns (success, message_text).
        """
        if len(self.history) <= 4:
            return False, "History is too short to compact (<= 4 messages)"

        recent_tail = self.history[-2:]
        history_to_compact = self.history[:-2]

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
