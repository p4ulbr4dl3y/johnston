import asyncio
from typing import Any, Dict

from tools.base import BaseTool


class AskUserTool(BaseTool):
    name = "ask_user"
    description = "Ask questions to the user with pre-defined options and write-ins."
    schema = {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask questions to user with pre-defined options and write-ins.",
            "parameters": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "description": "List of questions with pre-defined options and write-in choices",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question_text": {"type": "string", "description": "Main question"},
                                "options": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "List of selectable options"
                                }
                            },
                            "required": ["question_text"]
                        }
                    }
                },
                "required": ["questions"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        ctx = self._ensure_context(app)
        questions_list = args.get("questions")
        question = args.get("question", "")

        if isinstance(questions_list, dict):
            questions_list = [questions_list]

        if not questions_list and question:
            questions_list = [{"question_text": question, "options": []}]

        if ctx.app and questions_list and isinstance(questions_list, list):
            try:
                from widgets.modal_screens import ConfirmScreen, QuestionScreen
                answers = {}
                q_idx = 0
                cancelled = False
                while q_idx <= len(questions_list):
                    if q_idx < len(questions_list):
                        q = questions_list[q_idx]
                        num_text = f"### **Question {q_idx+1}/{len(questions_list)}**"
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
                        ctx.app.push_screen(screen, callback=on_dismiss)
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
                            summary += f"**Question {idx+1}:** {q_clean}\n\n**Answer:** {ans_info['answer']}\n\n"

                        screen = ConfirmScreen(summary)
                        loop = asyncio.get_running_loop()
                        future = loop.create_future()
                        def on_dismiss_confirm(result):
                            if not future.done():
                                future.set_result(result)
                        ctx.app.push_screen(screen, callback=on_dismiss_confirm)
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
            except Exception as e:
                return f"Error prompting user: {e}"
        return "Error: App instance not available or no valid questions provided."
