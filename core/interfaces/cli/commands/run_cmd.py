"""CLI headless run command for Johnston."""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import sys
import time
from typing import Any, Optional

from core.domain.defaults.errors import parse_stream_step, parse_tool_result_step
from core.domain.policies.role_policy import AgentMode
from core.role_registry import RoleRegistry
from core.roles.apply import apply_role

if False:  # type checking only
    from core.provider_manager import ProviderManager

__all__ = [
    "format_args_summary",
    "format_meta_footer",
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


def _format_token_count(n: int) -> str:
    """Format token count with k/M suffixes for compact display."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def format_meta_footer(
    provider: str,
    model: str,
    duration_s: float,
    tokens_in: int,
    tokens_out: int,
    total_tokens: int,
    cost_usd: float = 0.0,
    role: Optional[str] = None,
    mode: Optional[str] = None,
    sandbox: bool = False,
    effort: Optional[str] = None,
    compacted: bool = False,
) -> str:
    """Format execution summary metadata line."""
    prov_model = f"{provider}/{model}" if model and model != "-" else provider
    if effort and str(effort).strip():
        prov_model = f"{prov_model} ({str(effort).strip().lower()})"

    if role and isinstance(role, str) and role.strip().lower() not in ("", "worker"):
        identity = f"{role.strip().lower()}: {prov_model}"
    else:
        identity = prov_model

    parts = [identity]
    if mode and isinstance(mode, str) and mode.strip().lower() not in ("", "review"):
        parts.append(mode.strip().lower())
    if sandbox:
        parts.append("sandbox")
    if compacted:
        parts.append("compacted")

    parts.append(f"{duration_s:.2f}s")

    if tokens_out > 0 and duration_s > 0:
        tps = tokens_out / duration_s
        parts.append(f"{tps:.1f} tok/s")

    if total_tokens > 0 or tokens_in > 0 or tokens_out > 0:
        parts.append(
            f"in: {_format_token_count(tokens_in)}, out: {_format_token_count(tokens_out)}, total: {_format_token_count(total_tokens)} tok"
        )
    if cost_usd > 0.0:
        parts.append(f"${cost_usd:.4f}")
    return f"[{' | '.join(parts)}]"


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
    enabled_mcp_servers: list[Any] = []
    perm_mgr: Any = None
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
        else:
            from core.infrastructure.config.config_helpers import load_sandbox_config

            agent.sandbox_enabled = load_sandbox_config()

        continue_latest = (
            getattr(args, "continue_latest", False) is True
            or getattr(args, "continue", False) is True
        )
        resume_arg = getattr(args, "resume", None)
        sess: Any = None
        store: Any = None
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

        apply_role(agent, role, mode=AgentMode.HEADLESS)

        from core.domain.policies.permission_policy import ExecutionMode
        from core.permission_manager import PermissionManager

        perm_mgr = PermissionManager.get_instance()
        if getattr(args, "yolo", False) is True:
            active_mode = perm_mgr.set_session_mode(ExecutionMode.YOLO)
        elif getattr(args, "mode", None):
            active_mode = perm_mgr.set_session_mode(getattr(args, "mode"))
        else:
            active_mode = perm_mgr.execution_mode
        mode_val = active_mode.value

        is_quiet = getattr(args, "quiet", False) is True
        is_json = getattr(args, "json", False) is True
        is_stream_json = getattr(args, "stream_json", False) is True

        extra_skills = getattr(args, "skills", None) or []
        from core.application.skills.inject import extract_and_inject_skills

        effective_prompt, activated_skills = extract_and_inject_skills(prompt, extra_skills=extra_skills)
        if activated_skills:
            if is_stream_json:
                sys.stdout.write(json.dumps({"event": "skills", "skills": activated_skills}) + "\n")
                sys.stdout.flush()
            elif not is_quiet and not is_json:
                sys.stderr.write(f"[skills] activated: {', '.join(activated_skills)}\n")
                sys.stderr.flush()

        enabled_mcp_servers.clear()
        mcp_tools_count: int = 0
        from core.infrastructure.mcp import get_mcp_manager

        try:
            mcp_mgr = get_mcp_manager()
            servers = mcp_mgr.load_servers()
            enabled_mcp_servers = [s for s in servers if mcp_mgr.server_enabled(s)]
            if enabled_mcp_servers and (
                not os.environ.get("PYTEST_CURRENT_TEST") or getattr(args, "_test_mcp_warmup", False)
            ):
                mcp_tools = await asyncio.wait_for(mcp_mgr.get_active_tools_async(), timeout=10.0)
                mcp_tools_count = len(mcp_tools) if mcp_tools else 0
                if mcp_tools_count > 0:
                    names_str = ", ".join(s.get("name", "") for s in enabled_mcp_servers if s.get("name"))
                    if is_stream_json:
                        sys.stdout.write(
                            json.dumps(
                                {
                                    "event": "mcp",
                                    "servers": [s.get("name", "") for s in enabled_mcp_servers],
                                    "tools": mcp_tools_count,
                                }
                            )
                            + "\n"
                        )
                        sys.stdout.flush()
                    elif not is_quiet and not is_json:
                        sys.stderr.write(f"[mcp] active: {names_str} ({mcp_tools_count} tools)\n")
                        sys.stderr.flush()
        except Exception as mcp_exc:
            logging.debug("Headless MCP warmup failed or timed out: %s", mcp_exc)

        response_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        has_error = False
        compacted = False

        start_time = time.perf_counter()

        has_written_text = False
        pending_lead_ws: list[str] = []

        try:
            async for step in agent.stream_steps(effective_prompt):
                parsed = parse_stream_step(step)
                if parsed is None:
                    continue
                etype = parsed.event_type

                if etype in ("content", "bot_delta"):
                    chunk = parsed.val1 or ""
                    response_parts.append(chunk)
                    if is_stream_json:
                        sys.stdout.write(json.dumps({"event": "delta", "text": chunk}) + "\n")
                        sys.stdout.flush()
                    elif not is_json:
                        if not has_written_text:
                            if chunk.strip():
                                has_written_text = True
                                pending_lead_ws.clear()
                                sys.stdout.write(chunk.lstrip("\r\n"))
                                sys.stdout.flush()
                            else:
                                pending_lead_ws.append(chunk)
                        else:
                            sys.stdout.write(chunk)
                            sys.stdout.flush()

                elif etype == "bot_text":
                    if not response_parts and parsed.val1:
                        response_parts.append(parsed.val1)
                        if is_stream_json:
                            sys.stdout.write(json.dumps({"event": "delta", "text": parsed.val1}) + "\n")
                            sys.stdout.flush()
                        elif not is_json:
                            text = parsed.val1.lstrip("\r\n") if not has_written_text else parsed.val1
                            sys.stdout.write(text)
                            sys.stdout.flush()
                            has_written_text = True

                elif etype in ("tool_call", "tool"):
                    pending_lead_ws.clear()
                    has_written_text = False
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

                    if is_stream_json:
                        sys.stdout.write(json.dumps({"event": "tool_call", "name": t_name, "args": t_args}) + "\n")
                        sys.stdout.flush()
                    elif not is_quiet and not is_json:
                        summary = format_args_summary(t_args)
                        if response_parts and "".join(response_parts).strip() and not response_parts[-1].endswith("\n"):
                            sys.stdout.write("\n")
                            sys.stdout.flush()
                        sys.stderr.write(f"[tool] {t_name}({summary})\n")
                        sys.stderr.flush()

                elif etype == "tool_result":
                    parsed_tr = parse_tool_result_step(step)
                    res_content = parsed_tr.content or parsed.val1 or ""
                    if tool_calls and "result" not in tool_calls[-1]:
                        tool_calls[-1]["result"] = res_content

                    if is_stream_json:
                        sys.stdout.write(json.dumps({"event": "tool_result", "result": res_content}) + "\n")
                        sys.stdout.flush()
                    elif not is_quiet and not is_json:
                        res_summary = format_result_summary(res_content)
                        if res_summary:
                            sys.stderr.write(f"[result] {res_summary}\n")
                            sys.stderr.flush()

                elif etype in ("event_divider", "compaction"):
                    compacted = True
                    comp_title = parsed.val1 or "Session Compacted"
                    if is_stream_json:
                        sys.stdout.write(json.dumps({"event": "compaction", "title": comp_title}) + "\n")
                        sys.stdout.flush()
                    elif not is_quiet and not is_json:
                        sys.stderr.write(f"[compaction] {comp_title}\n")
                        sys.stderr.flush()

                elif etype == "error":
                    has_error = True
                    err_msg = parsed.val1 or "Unknown stream error"
                    if is_stream_json:
                        sys.stdout.write(json.dumps({"event": "error", "error": err_msg}) + "\n")
                        sys.stdout.flush()
                    else:
                        sys.stderr.write(f"Error: {err_msg}\n")
                        sys.stderr.flush()

        except Exception as exc:
            has_error = True
            if is_stream_json:
                sys.stdout.write(json.dumps({"event": "error", "error": str(exc)}) + "\n")
                sys.stdout.flush()
            else:
                sys.stderr.write(f"Error: {exc}\n")
                sys.stderr.flush()

        duration_s = max(0.0, time.perf_counter() - start_time)
        model_name = getattr(agent, "model", None) or model or "-"
        ti = getattr(agent, "tokens_input", 0)
        to = getattr(agent, "tokens_output", 0)
        tt = getattr(agent, "total_tokens", 0)
        cu = getattr(agent, "cost_usd", 0.0)
        to_val = to if isinstance(to, (int, float)) else 0
        tps = round(to_val / duration_s, 1) if duration_s > 0 and to_val > 0 else 0.0
        usage = {
            "provider": provider_key,
            "model": model_name,
            "duration_s": round(duration_s, 3),
            "tok_per_sec": tps,
            "tokens_input": ti if isinstance(ti, (int, float)) else 0,
            "tokens_output": to_val,
            "total_tokens": tt if isinstance(tt, (int, float)) else 0,
            "cost_usd": cu if isinstance(cu, (int, float)) else 0.0,
        }
        if compacted:
            usage["compacted"] = True

        if is_stream_json:
            sys.stdout.write(json.dumps({"event": "done", "usage": usage}) + "\n")
            sys.stdout.flush()
        elif is_json:
            output_payload = {
                "response": "".join(response_parts),
                "tool_calls": tool_calls,
                "usage": usage,
            }
            if activated_skills:
                output_payload["skills"] = activated_skills
            if mcp_tools_count > 0:
                output_payload["mcp"] = {
                    "servers": [s.get("name", "") for s in enabled_mcp_servers if s.get("name")],
                    "tools": mcp_tools_count,
                }
            if compacted:
                output_payload["compacted"] = True
            if role and role.strip().lower() != "worker":
                output_payload["role"] = role.strip().lower()
            if mode_val and mode_val != "review":
                output_payload["mode"] = mode_val
            if getattr(agent, "sandbox_enabled", False) is True:
                output_payload["sandbox"] = True
            print(json.dumps(output_payload, indent=2))
            sys.stdout.flush()
        else:
            full_text = "".join(response_parts)
            if full_text and not full_text.endswith("\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()

            if not is_quiet:
                effort_val = getattr(args, "effort", None)
                sandbox_val = getattr(agent, "sandbox_enabled", False) is True
                footer = format_meta_footer(
                    provider_key,
                    model_name,
                    duration_s,
                    usage["tokens_input"],
                    usage["tokens_output"],
                    usage["total_tokens"],
                    usage["cost_usd"],
                    role=role,
                    mode=mode_val,
                    sandbox=sandbox_val,
                    effort=effort_val,
                    compacted=compacted,
                )
                from core.interfaces.cli.formatter import DIM, RESET, supports_color

                styled_footer = f"{DIM}{footer}{RESET}" if supports_color() else footer
                sys.stderr.write(f"{styled_footer}\n")
                sys.stderr.flush()

        if sess is not None and store is not None:
            try:
                if hasattr(agent, "history") and agent.history:
                    sess.agent_history = list(agent.history)
                if hasattr(agent, "messages"):
                    sess.messages = list(agent.messages)
                sess.tokens_input = getattr(agent, "tokens_input", sess.tokens_input)
                sess.tokens_output = getattr(agent, "tokens_output", sess.tokens_output)
                sess.total_tokens = getattr(agent, "total_tokens", sess.total_tokens)
                sess.cost_usd = getattr(agent, "cost_usd", sess.cost_usd)
                store.save(sess)
            except Exception as save_err:
                logging.debug("Failed to persist resumed session: %s", save_err)

        return 1 if has_error else 0

    finally:
        if perm_mgr is not None:
            try:
                perm_mgr.clear_session_overrides()
            except Exception:
                pass
        if enabled_mcp_servers:
            try:
                from core.infrastructure.mcp import get_mcp_manager

                await asyncio.wait_for(get_mcp_manager().stop_all_async(), timeout=5.0)
            except Exception:
                pass
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
