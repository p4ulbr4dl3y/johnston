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

        elif name == "Create":
            path = os.path.expanduser(args.get("path", ""))
            content = args.get("content", "")
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Success: file '{path}' saved ({len(content)} bytes)."

        elif name == "Edit":
            path = os.path.expanduser(args.get("path", ""))
            old_string = args.get("old_string", "")
            new_string = args.get("new_string", "")
            if not os.path.exists(path):
                return f"Error: file '{path}' not found."
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                return f"Error reading file '{path}': {e}"
            if old_string not in content:
                return f"Error: exact block of text (old_string) not found in '{path}'. Make sure it matches exactly (including leading whitespace/indentation)."
            new_content = content.replace(old_string, new_string, 1)
            try:
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_content)
            except Exception as e:
                return f"Error writing file '{path}': {e}"
            import difflib
            diff_lines = list(difflib.unified_diff(
                content.splitlines(),
                new_content.splitlines(),
                fromfile=path + " (old)",
                tofile=path + " (new)",
                lineterm=""
            ))
            return "\n".join(diff_lines)

        elif name == "Bash":
            cmd = args.get("command", "")
            p = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            try:
                stdout_bytes, _ = await asyncio.wait_for(p.communicate(), timeout=5.0)
                res = stdout_bytes.decode("utf-8", errors="replace")
                if len(res) > 3000:
                    res = res[:3000] + "\n... [output truncated]"
                return res if res.strip() else "Command executed with no output."
            except asyncio.TimeoutError:
                if app:
                    task_id = f"bash_{int(time.time())}"
                    task = BackgroundTask(task_id, cmd, p)
                    if hasattr(app, "background_tasks"):
                        app.background_tasks.append(task)
                    
                    task.start_reading(app, app.on_background_bash_completed)
                    app.notify(f"Command sent to background (TID: {task_id})")
                    return f"[Background Task ID: {task_id}] Bash command is running in the background. I must wait for its completion. Do not run any other tools until notified."
                else:
                    stdout_bytes, _ = await p.communicate()
                    res = stdout_bytes.decode("utf-8", errors="replace")
                    if len(res) > 3000:
                        res = res[:3000] + "\n... [output truncated]"
                    return res if res.strip() else "Command executed with no output."

        elif name == "Glob":
            pattern = args.get("pattern", "*")
            ignore_dirs = {".git", "node_modules", ".venv", "__pycache__", ".tui", ".gemini"}
            root_dir = os.getcwd()
            matches = []
            import fnmatch
            for root, dirs, files in os.walk(root_dir):
                dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
                for file in files:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, root_dir)
                    if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(file, pattern):
                        matches.append(rel_path)
                        if len(matches) >= 100:
                            break
                if len(matches) >= 100:
                    break
            if not matches:
                return "No files found matching the pattern."
            return "\n".join(matches)

        elif name == "Grep":
            pattern = args.get("pattern", "")
            if not pattern:
                return "Error: pattern is required."
            ignore_dirs = {".git", "node_modules", ".venv", "__pycache__", ".tui", ".gemini"}
            ignore_extensions = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".tar", ".gz", ".db", ".sqlite", ".pyc"}
            import re
            try:
                regex = re.compile(pattern, re.IGNORECASE)
            except Exception as e:
                return f"Error compiling regex '{pattern}': {e}"
            root_dir = os.getcwd()
            results = []
            for root, dirs, files in os.walk(root_dir):
                dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    if ext in ignore_extensions:
                        continue
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, root_dir)
                    try:
                        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                            for line_num, line in enumerate(f, 1):
                                if regex.search(line):
                                    clean_line = line.strip()
                                    if len(clean_line) > 150:
                                        clean_line = clean_line[:150] + "..."
                                    results.append(f"{rel_path}:{line_num}: {clean_line}")
                                    if len(results) >= 50:
                                        break
                    except Exception:
                        pass
                    if len(results) >= 50:
                        break
                if len(results) >= 50:
                    break
            if not results:
                return "No matches found."
            return "\n".join(results)

        elif name == "AskUser":
            questions_list = args.get("questions")
            question = args.get("question", "")
            if app:
                try:
                    if questions_list and isinstance(questions_list, list):
                        from widgets.modal_screens import QuestionScreen, ConfirmScreen
                        answers = {}
                        q_idx = 0
                        cancelled = False
                        while q_idx <= len(questions_list):
                            if q_idx < len(questions_list):
                                q = questions_list[q_idx]
                                num_text = q.get("num_text") or f"### **Question {q_idx+1}/{len(questions_list)}**"
                                q_text = q.get("question_text", "")
                                opts = q.get("options") or []
                                prev_val = answers.get(q_idx, {}).get("answer", "")
                                
                                screen = QuestionScreen(
                                    num_text=num_text,
                                    question_text=q_text,
                                    options=opts,
                                    current_val=prev_val
                                )
                                loop = asyncio.get_running_loop()
                                future = loop.create_future()
                                def on_dismiss(result):
                                    if not future.done():
                                        future.set_result(result)
                                app.push_screen(screen, callback=on_dismiss)
                                res = await future
                                
                                if not res or res.get("status") == "cancelled":
                                    cancelled = True
                                    break
                                elif res.get("status") == "back":
                                    if q_idx > 0:
                                        q_idx -= 1
                                elif res.get("status") == "next":
                                    answers[q_idx] = res
                                    q_idx += 1
                            else:
                                summary = ""
                                for idx in range(len(questions_list)):
                                    q_clean = questions_list[idx].get("question_text", "")
                                    ans_info = answers.get(idx, {"status": "skipped", "answer": "Skipped"})
                                    summary += f"**Вопрос {idx+1}:** {q_clean}\n\n**Ответ:** {ans_info['answer']}\n\n"
                                
                                screen = ConfirmScreen(summary)
                                loop = asyncio.get_running_loop()
                                future = loop.create_future()
                                def on_dismiss_confirm(result):
                                    if not future.done():
                                        future.set_result(result)
                                app.push_screen(screen, callback=on_dismiss_confirm)
                                res = await future
                                
                                if not res or res == "cancelled":
                                    cancelled = True
                                    break
                                elif res == "back":
                                    q_idx = len(questions_list) - 1
                                elif res == "confirm":
                                    q_idx += 1
                                    
                        if cancelled:
                            return "Cancelled by user."
                            
                        out_summary = ""
                        for idx in range(len(questions_list)):
                            q_clean = questions_list[idx].get("question_text", "")
                            ans_info = answers.get(idx, {"status": "skipped", "answer": "Skipped"})
                            out_summary += f"Question: {q_clean}\nAnswer: {ans_info['answer']}\n"
                        return out_summary.strip()
                    else:
                        from widgets.modal_screens import AskUserScreen
                        screen = AskUserScreen(question)
                        loop = asyncio.get_running_loop()
                        future = loop.create_future()
                        def on_dismiss(result):
                            if not future.done():
                                future.set_result(result)
                        app.push_screen(screen, callback=on_dismiss)
                        answer = await future
                        return answer if answer else "No answer provided."
                except Exception as e:
                    return f"Error prompting user: {e}"
            return "Error: App instance not available to ask user."

    except Exception as err:
        return f"Error executing tool {name}: {err}"
    
    return "Unknown tool."


class BackgroundTask:
    """Управление фоновым bash-процессом с построчным чтением вывода в реальном времени"""
    def __init__(self, task_id: str, command: str, process):
        self.task_id = task_id
        self.command = command
        self.process = process
        self.output = []
        self.is_running = True

    def start_reading(self, app, on_completed_cb):
        async def _read():
            try:
                while True:
                    line = await self.process.stdout.readline()
                    if not line:
                        break
                    self.output.append(line.decode("utf-8", errors="replace"))
            except Exception:
                pass
            finally:
                self.is_running = False
                if self.process:
                    try:
                        await self.process.wait()
                    except Exception:
                        pass
                
                # Формируем итоговый результат
                out_res = "".join(self.output)
                if len(out_res) > 3000:
                    out_res = out_res[:3000] + "\n... [output truncated]"
                out_res = out_res if out_res.strip() else "Command executed with no output."
                on_completed_cb(self.task_id, self.command, out_res)

        asyncio.create_task(_read())

    async def kill(self):
        if self.is_running and self.process:
            try:
                self.process.terminate()
                await self.process.wait()
            except Exception:
                pass
        self.is_running = False
        self.output.append("\n[Task terminated by user]\n")


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
