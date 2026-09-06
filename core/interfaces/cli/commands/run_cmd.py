"""CLI headless run command for Johnston."""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import sys
from typing import Any, Optional

from core.domain.defaults.errors import parse_stream_step, parse_tool_result_step
from core.role_registry import RoleRegistry
from core.roles.apply import apply_role

if False:  # type checking only
    from core.provider_manager import ProviderManager

__all__ = [
    "format_args_summary",
    "format_result_summary",
    "resolve_prompt",
    "run_headless",
    "run_headless_async",
]


def resolve_prompt(prompt_arg: Optional[str]) -> Optional[str]:
    """Resolve prompt text from positional argument or stdin."""
    if prompt_arg == "-" or (not prompt_arg and not sys.stdin.isatty()):
        try:
            prompt_arg = sys.stdin.read()
        except Exception as exc:
            sys.stderr.write(f"Error reading from stdin: {exc}\n")
            return None

    if not prompt_arg or not prompt_arg.strip():
        sys.stderr.write("Error: No prompt provided. Specify prompt or pass via stdin.\n")
        return None

    return prompt_arg.strip()


def format_args_summary(args: Any) -> str:
    """Produce a concise string summary of tool call arguments."""
    if not args:
        return ""
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            if isinstance(parsed, dict):
                args = parsed
            else:
                return args
        except Exception:
            return args

    if isinstance(args, dict):
        parts = []
        for k, v in args.items():
            rep = repr(v)
            if len(rep) > 60:
                rep = rep[:57] + "..."
            parts.append(f"{k}={rep}")
        return ", ".join(parts)
    s = str(args)
    if len(s) > 60:
        return s[:57] + "..."
    return s


def format_result_summary(result: Any) -> str:
    """Format tool execution result for compact CLI output."""
    if result is None:
        return ""
    s = str(result).strip()
    if not s:
        return ""
    lines = s.splitlines()
    if len(lines) > 1:
        first = lines[0]
        if len(first) > 80:
            first = first[:77] + "..."
        return f"{first} (+{len(lines) - 1} lines)"
    if len(s) > 120:
        return s[:117] + "..."
    return s


async def run_headless_async(args: Any, pm: Optional[ProviderManager] = None) -> int:
    """Async execution logic for johnston run."""
    if getattr(args, "debug", False) is True:
        logging.getLogger().setLevel(logging.DEBUG)

    candidate = getattr(args, "cwd", None)
    if isinstance(candidate, str) and candidate.strip():
        cwd_target = os.path.abspath(candidate)
        if not os.path.isdir(cwd_target):
            sys.stderr.write(f"Error: Directory '{candidate}' does not exist.\n")
            return 1
        os.chdir(cwd_target)

    prompt = resolve_prompt(getattr(args, "prompt", None))
    if prompt is None:
        return 1

    close_pm = False
    if pm is None:
        from core.provider_manager import ProviderManager

        pm = ProviderManager()
        close_pm = True

    agent: Any = None
    try:
        provider_key = getattr(args, "provider", None) or pm.get_active_provider_key()
        if not provider_key:
            sys.stderr.write("Error: No active provider configured or specified.\n")
            return 1

        pdef = pm.load_provider_def(provider_key)
        if pdef is None:
            sys.stderr.write(f"Error: Provider '{provider_key}' not found.\n")
            return 1

        if not pdef.enabled:
            sys.stderr.write(f"Error: Provider '{provider_key}' is disabled.\n")
            return 1

        needs_key = pm.provider_needs_key(provider_key, pdef)
        api_key = pm.get_api_key(pdef.key) or pdef.api_key
        if needs_key and not api_key:
            sys.stderr.write(
                f"Error: No API key configured for provider '{provider_key}'. "
                f"Set key with: johnston provider set-key {provider_key} <KEY>\n"
            )
            return 1

        agent = pm.create_agent_for_provider(provider_key)
        if agent is None:
            sys.stderr.write(f"Error: Failed to create agent for provider '{provider_key}'.\n")
            return 1

        model = getattr(args, "model", None)
        if isinstance(model, str) and model.strip():
            agent.model = model

        effort = getattr(args, "effort", None)
        if isinstance(effort, str) and effort.strip():
            agent.thinking_effort = effort
            agent.reasoning_effort = effort

        if getattr(args, "sandbox", False) is True:
            agent.sandbox_enabled = True
        elif getattr(args, "no_sandbox", False) is True:
            agent.sandbox_enabled = False

        continue_latest = (
            getattr(args, "continue_latest", False) is True
            or getattr(args, "continue", False) is True
        )
        resume_arg = getattr(args, "resume", None)
        if continue_latest or (isinstance(resume_arg, str) or resume_arg == ""):
            from core.infrastructure.storage.session_store import SessionStore

            store = SessionStore.get_instance()
            target_sid = resume_arg if isinstance(resume_arg, str) and resume_arg.strip() else None
            if not target_sid:
                main_sessions = store.list_main_sessions()
                if main_sessions:
                    target_sid = main_sessions[0]["id"]
            if target_sid:
                sess = store.get(target_sid)
                if sess:
                    if hasattr(sess, "agent_history") and sess.agent_history:
                        agent.history = list(sess.agent_history)
                    if hasattr(agent, "messages"):
                        agent.messages = list(getattr(sess, "messages", []) or getattr(sess, "agent_history", []))
                    if hasattr(sess, "tokens_input") and hasattr(agent, "tokens_input"):
                        agent.tokens_input = sess.tokens_input
                    if hasattr(sess, "tokens_output") and hasattr(agent, "tokens_output"):
                        agent.tokens_output = sess.tokens_output
                    if hasattr(sess, "total_tokens") and hasattr(agent, "total_tokens"):
                        agent.total_tokens = sess.total_tokens
                    if hasattr(sess, "cost_usd") and hasattr(agent, "cost_usd"):
                        agent.cost_usd = sess.cost_usd


        role = getattr(args, "role", None) or "worker"
        roles = RoleRegistry.get_instance().load_roles()
        if role not in roles:
            sys.stderr.write(f"Error: Role '{role}' not found.\n")
            return 1

        apply_role(agent, role, is_subagent=False)

        is_quiet = bool(getattr(args, "quiet", False))
        is_json = bool(getattr(args, "json", False))


        response_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        has_error = False

        try:
            async for step in agent.stream_steps(prompt):
                parsed = parse_stream_step(step)
                if parsed is None:
                    continue
                etype = parsed.event_type

                if etype in ("content", "bot_delta"):
                    chunk = parsed.val1 or ""
                    response_parts.append(chunk)
                    if not is_json:
                        sys.stdout.write(chunk)
                        sys.stdout.flush()

                elif etype == "bot_text":
                    if not response_parts and parsed.val1:
                        response_parts.append(parsed.val1)
                        if not is_json:
                            sys.stdout.write(parsed.val1)
                            sys.stdout.flush()

                elif etype in ("tool_call", "tool"):
                    t_name = parsed.val1
                    if isinstance(parsed.val3, (dict, list)):
                        t_args = parsed.val3
                    elif isinstance(parsed.val2, (dict, list)):
                        t_args = parsed.val2
                    elif isinstance(parsed.val2, str) and etype == "tool_call":
                        try:
                            t_args = json.loads(parsed.val2)
                        except Exception:
                            t_args = parsed.val2
                    elif isinstance(parsed.val3, str) and etype == "tool":
                        try:
                            t_args = json.loads(parsed.val3)
                        except Exception:
                            t_args = parsed.val3
                    else:
                        t_args = parsed.val2 if etype == "tool_call" else (parsed.val3 or {})

                    if isinstance(t_name, dict):
                        raw_dict = t_name
                        t_name = raw_dict.get("name", "")
                        t_args = raw_dict.get("args") or raw_dict.get("arguments") or {}

                    tool_calls.append({"name": t_name, "args": t_args})

                    if not is_quiet and not is_json:
                        summary = format_args_summary(t_args)
                        print(f"[tool] {t_name}({summary})")
                        sys.stdout.flush()

                elif etype == "tool_result":
                    parsed_tr = parse_tool_result_step(step)
                    res_content = parsed_tr.content or parsed.val1 or ""
                    if tool_calls and "result" not in tool_calls[-1]:
                        tool_calls[-1]["result"] = res_content

                    if not is_quiet and not is_json:
                        res_summary = format_result_summary(res_content)
                        print(f"[result] {res_summary}")
                        sys.stdout.flush()

                elif etype == "error":
                    has_error = True
                    err_msg = parsed.val1 or "Unknown stream error"
                    sys.stderr.write(f"Error: {err_msg}\n")
                    sys.stderr.flush()

        except Exception as exc:
            has_error = True
            sys.stderr.write(f"Error: {exc}\n")
            sys.stderr.flush()

        if not is_json:
            full_text = "".join(response_parts)
            if full_text and not full_text.endswith("\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
        else:
            usage = {
                "tokens_input": getattr(agent, "tokens_input", 0),
                "tokens_output": getattr(agent, "tokens_output", 0),
                "total_tokens": getattr(agent, "total_tokens", 0),
                "cost_usd": getattr(agent, "cost_usd", 0.0),
            }
            output_payload = {
                "response": "".join(response_parts),
                "tool_calls": tool_calls,
                "usage": usage,
            }
            print(json.dumps(output_payload, indent=2))
            sys.stdout.flush()

        return 1 if has_error else 0

    finally:
        if agent and hasattr(agent, "close") and callable(agent.close):
            res = agent.close()
            if inspect.isawaitable(res):
                await res
        if close_pm:
            await pm.close()


def run_headless(args: Any, pm: Optional[ProviderManager] = None) -> int:
    """Headless run command synchronous entrypoint."""
    if getattr(args, "debug", False) is True:
        logging.getLogger().setLevel(logging.DEBUG)

    candidate = getattr(args, "cwd", None)
    if isinstance(candidate, str) and candidate.strip():
        cwd_target = os.path.abspath(candidate)
        if not os.path.isdir(cwd_target):
            sys.stderr.write(f"Error: Directory '{candidate}' does not exist.\n")
            return 1
        os.chdir(cwd_target)

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(asyncio.run, run_headless_async(args, pm=pm)).result()
        return asyncio.run(run_headless_async(args, pm=pm))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
