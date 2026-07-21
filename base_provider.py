import os
import json
import time
import asyncio
from typing import AsyncGenerator, Tuple, List, Dict, Any
from openai import AsyncOpenAI

async def execute_tool(name: str, args: dict, app=None) -> str:
    """Local execution of tools Read, Create, Edit, Bash"""
    try:
        if name == "Read":
            path = os.path.expanduser(args.get("path", ""))
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    if len(content) > 4000:
                        content = content[:4000] + "\n... [content truncated]"
                    return content
            return f"Error: file '{path}' not found."

        elif name in ("Create", "Edit"):
            path = os.path.expanduser(args.get("path", ""))
            content = args.get("content", "")
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Success: file '{path}' saved ({len(content)} bytes)."

        elif name == "Bash":
            cmd = args.get("command", "")
            p = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(p.communicate(), timeout=5.0)
                res = stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")
                if len(res) > 3000:
                    res = res[:3000] + "\n... [output truncated]"
                return res if res.strip() else "Command executed with no output."
            except asyncio.TimeoutError:
                if app:
                    task_id = f"bash_{int(time.time())}"
                    async def wait_for_background_task(proc, command_str, tid, application):
                        stdout_bytes, stderr_bytes = await proc.communicate()
                        out_res = stdout_bytes.decode("utf-8", errors="replace") + stderr_bytes.decode("utf-8", errors="replace")
                        if len(out_res) > 3000:
                            out_res = out_res[:3000] + "\n... [output truncated]"
                        out_res = out_res if out_res.strip() else "Command executed with no output."
                        application.on_background_bash_completed(tid, command_str, out_res)
                    
                    asyncio.create_task(wait_for_background_task(p, cmd, task_id, app))
                    app.notify(f"Command sent to background (TID: {task_id})")
                    return f"[Background Task ID: {task_id}] Bash command is running in the background. I must wait for its completion. Do not run any other tools until notified."
                else:
                    stdout, stderr = await p.communicate()
                    res = stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")
                    if len(res) > 3000:
                        res = res[:3000] + "\n... [output truncated]"
                    return res if res.strip() else "Command executed with no output."

    except Exception as err:
        return f"Error executing tool {name}: {err}"
    
    return "Unknown tool."


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
                    if hasattr(chunk.choices[0], "delta") and hasattr(chunk.choices[0].delta, "reasoning_content"):
                        reasoning = chunk.choices[0].delta.reasoning_content
                        if reasoning:
                            if not thinking_started:
                                yield ("thinking_start", "Thinking...", "")
                                thinking_started = True
                            active_thought += reasoning
                            yield ("thinking_delta", active_thought, "")

                    delta = chunk.choices[0].delta
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

                    target = args.get("path") or args.get("command") or t_name
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
