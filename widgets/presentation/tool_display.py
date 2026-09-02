"""Presentational tool-call display helpers (textual chip labels).

Moved out of ``core/application/display.py``: this module produces UI-facing
markup (escape_markup / extract_tool_display). Domain and application must not
own rendering-format output, so these helpers live in the infrastructure
presentation area consumed by core widgets and UI tests.
"""
import json
import re
from typing import Any, Dict, List, Optional

from core.infrastructure.runtime.lru import LruCache
from widgets.utils.row_format import format_duration

# Textual markup-aware escaping: literal [ and ] would otherwise be swallowed as
# style tags, so escape them (and backslashes) for the chat tool chip.
_ESCAPE_RE = re.compile(r"([\[\]\\])")

# LRU memo for extract_tool_display keyed by (tool_name, canonical args). The
# agent loop calls this once per tool call for the chip label; multi-tool turns
# with repeated argument signatures hit the cache instead of re-running the
# label logic. Keys are limited to a small canonical representation so two
# distinct arg dicts can't alias an entry.
_DISPLAY_CACHE_MAX = 128
_DISPLAY_CACHE: "LruCache[tuple, str]" = LruCache(_DISPLAY_CACHE_MAX)


def escape_markup(target: str) -> str:
    """Escape markup-significant characters for safe display in the tool chip."""
    return _ESCAPE_RE.sub(r"\\\1", target)


def format_compact_dict(d: dict) -> str:
    """Render a tool-args dict as a compact ``{k: v, ...}`` chip label.

    Single format for every non-builtin (MCP/custom) tool: keys are clipped to
    20 chars, values to 35, the whole entry to ~70 chars total; overflow becomes
    a trailing ``...``. Non-dict or empty input yields ``""`` (empty parens).
    """
    if not isinstance(d, dict) or not d:
        return ""

    items = []
    total_len = 0
    overflow = False
    for k, v in d.items():
        k_str = str(k)
        if len(k_str) > 20:
            k_str = k_str[:17] + "..."

        if isinstance(v, str):
            v_clean = v.replace("\n", "\\n")
            if len(v_clean) > 35:
                v_clean = v_clean[:32] + "..."
            v_str = f'"{v_clean}"'
        else:
            v_str = json.dumps(v, ensure_ascii=False, default=str)
            if len(v_str) > 35:
                v_str = v_str[:32] + "..."

        item_str = f"{k_str}: {v_str}"
        if total_len + len(item_str) > 70:
            overflow = True
            break
        items.append(item_str)
        total_len += len(item_str) + 2

    if overflow and items:
        return "{" + ", ".join(items) + ", ...}"
    elif items:
        return "{" + ", ".join(items) + "}"
    else:
        return "{...}"


def truncate(target: str, max_len: int = 60) -> str:
    """Collapse whitespace and clip a display label to a UI-friendly length."""
    if not isinstance(target, str):
        return escape_markup(str(target)) if target else ""
    target = re.sub(r"\s+", " ", target).strip()
    if len(target) > max_len:
        target = target[:25] + "..." + target[-32:]
    return escape_markup(target)


def _canonical_args(args: Dict[str, Any]) -> tuple:
    """Small stable representation of a tool-call argument dict for caching."""
    if not args:
        return ()
    try:
        return (
            tuple(sorted((k, json.dumps(v, ensure_ascii=False, sort_keys=True)) for k, v in args.items()))
            if args
            else ()
        )
    except Exception:
        return (type(args).__name__, repr(args))


def _display_cache_key(tool_name: str, args: Dict[str, Any]) -> tuple:
    return (str(tool_name), _canonical_args(args))


def extract_tool_display(tool_name: str, args: Dict[str, Any]) -> str:
    """Build a short, human-readable label describing what a tool call targets.

    This is presentation-only metadata for the chat tool chip and is intentionally
    kept out of the core agent loop so business logic stays free of rendering
    concerns. Tool names are matched case-insensitively against the canonical
    lowercase registry names. Results are memoized by (tool_name, args) so the
    agent loop doesn't rebuild identical labels on every tool call.
    """
    key = _display_cache_key(tool_name, args)
    hit = _DISPLAY_CACHE.get(key)
    if hit is not None:
        return hit

    result = _extract_tool_display_inner(tool_name, args)

    _DISPLAY_CACHE.put(key, result)
    return result


def _extract_tool_display_inner(tool_name: str, args: Dict[str, Any]) -> str:
    from core.infrastructure.runtime.tool_name import normalize_tool_name as _normalize
    from tools.registry import REGISTRY

    name = _normalize(tool_name)
    args = args if isinstance(args, dict) else {}
    is_builtin = name in REGISTRY

    if not is_builtin:
        # MCP/custom tools: single predefined format — compact ``{k: v, ...}``
        # args label (empty parens when no args).
        return format_compact_dict(args)

    if name == "ask_user":
        qs = args.get("questions")
        if isinstance(qs, list) and qs:
            formatted = []
            for q in qs:
                q_text = q.get("question") if isinstance(q, dict) else ""
                if q_text:
                    formatted.append(truncate(q_text))
            if formatted:
                return truncate(", ".join(f'"{t}"' for t in formatted))
        return ""

    if name == "invoke_subagent":
        title = str(args.get("title") or "").strip()
        role = str(args.get("type") or args.get("role") or "worker").strip()
        from core.role_registry import get_role_display_name

        role_cap = get_role_display_name(role)
        if title:
            return truncate(f'{role_cap}: "{title}"')
        return truncate(role_cap)
    if name in ("manage_shell", "manage_subagent"):
        act = args.get("action") or ""
        tid = args.get("session_id" if name == "manage_subagent" else "task_id") or ""
        if act and tid:
            if act in ("send_input", "send_message"):
                verb = "send message to" if act == "send_message" else "send input to"
                return truncate(f"{verb} {tid}")
            return truncate(f"{act} {tid}")
        if tid:
            return truncate(tid)
        if act:
            return truncate(act)
        return ""

    if name == "update_plan":
        plan_data = args.get("plan")
        if isinstance(plan_data, list) and plan_data:
            total = len(plan_data)
            completed = sum(
                1 for item in plan_data if isinstance(item, dict) and item.get("status") == "completed"
            )
            if completed == total:
                return f"{completed}/{total} done"

            active_step = ""
            for item in plan_data:
                if isinstance(item, dict) and item.get("status") == "in_progress":
                    active_step = str(item.get("step") or "").strip()
                    break

            if not active_step and completed == 0:
                for item in plan_data:
                    if isinstance(item, dict) and item.get("status") == "pending":
                        active_step = str(item.get("step") or "").strip()
                        break

            if active_step:
                return truncate(f"{completed}/{total}: {active_step}")
            return f"{completed}/{total} done"
        return ""

    if name == "read":
        val = args.get("path")
        if isinstance(val, str) and val:
            path_str = val.strip()

            def _to_int(v: Any) -> Optional[int]:
                if isinstance(v, int):
                    return v
                if isinstance(v, str) and v.strip().isdigit():
                    try:
                        return int(v.strip())
                    except ValueError:
                        return None
                return None

            s_line = _to_int(args.get("start_line"))
            e_line = _to_int(args.get("end_line"))
            offset = _to_int(args.get("content_offset"))

            if s_line is not None and e_line is not None:
                suffix = f":{s_line}" if s_line == e_line else f":{s_line}-{e_line}"
            elif s_line is not None:
                suffix = f":{s_line}+"
            elif e_line is not None:
                suffix = f":1-{e_line}"
            elif offset is not None and offset > 0:
                if offset >= 1024 * 1024:
                    mb = offset / (1024 * 1024)
                    suffix = f":+{mb:.1f}MB" if mb != int(mb) else f":+{int(mb)}MB"
                elif offset >= 1024:
                    kb = offset / 1024
                    suffix = f":+{kb:.1f}KB" if kb != int(kb) else f":+{int(kb)}KB"
                else:
                    suffix = f":+{offset}B"
            else:
                suffix = ""
            return truncate(f"{path_str}{suffix}")
        return ""

    if name in ("create", "edit"):
        val = args.get("path")
        if isinstance(val, str) and val:
            return truncate(val.strip())
        return ""

    if name == "shell":
        cmd = args.get("command")
        if isinstance(cmd, str) and cmd:
            return truncate(cmd)
        return ""

    if name == "web_fetch":
        url = args.get("url")
        if isinstance(url, str) and url:
            return truncate(url)
        return ""

    return ""


def _format_active_tool_progress(
    tool_name: str,
    args: Dict[str, Any],
    target: str = "",
    turn_events: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Format an active tool invocation into a short, human-like activity badge."""
    from core.infrastructure.runtime.tool_name import normalize_tool_name as _normalize

    name = _normalize(tool_name) if tool_name else ""
    if not isinstance(args, dict):
        args = {}

    def _extract_path(targs: Any, ttgt: str = "") -> str:
        if not isinstance(targs, dict):
            return str(ttgt or "").strip()
        return str(
            targs.get("path")
            or targs.get("file_path")
            or ttgt
            or ""
        ).strip()

    def _count_unique_files(tool_names: tuple[str, ...]) -> int:
        if not turn_events:
            return 1
        files = set()
        for evt in turn_events:
            if not isinstance(evt, dict) or evt.get("type") != "tool" or not evt.get("tool_type"):
                continue
            t_name = _normalize(evt.get("tool_type") or "")
            if t_name in tool_names:
                p = _extract_path(evt.get("args") or {}, evt.get("target") or "")
                if p:
                    files.add(p)
                else:
                    files.add(f"__anon_file_{id(evt)}")
        return max(1, len(files))

    def _count_tool_invocations(tool_names: tuple[str, ...]) -> int:
        if not turn_events:
            return 1
        cnt = sum(
            1
            for evt in turn_events
            if isinstance(evt, dict)
            and evt.get("type") == "tool"
            and evt.get("tool_type")
            and _normalize(evt.get("tool_type") or "") in tool_names
        )
        return max(1, cnt)

    if name in ("read", "view_file"):
        n_files = _count_unique_files(("read", "view_file"))
        return f"reading {n_files} files" if n_files > 1 else "reading file"

    if name in ("create", "write_to_file"):
        n_files = _count_unique_files(("create", "write_to_file"))
        return f"creating {n_files} files" if n_files > 1 else "creating file"

    if name in ("edit", "replace_file_content", "multi_edit"):
        n_files = _count_unique_files(("edit", "replace_file_content", "multi_edit"))
        return f"editing {n_files} files" if n_files > 1 else "editing file"

    if name in ("shell", "run_command"):
        n_cmds = _count_tool_invocations(("shell", "run_command"))
        return f"running {n_cmds} commands" if n_cmds > 1 else "running command"

    if name == "update_plan":
        plan = args.get("plan")
        if isinstance(plan, list) and plan:
            done = sum(1 for item in plan if isinstance(item, dict) and item.get("status") == "completed")
            return f"plan [{done}/{len(plan)}]"
        return "updating plan"

    if name in ("web_fetch", "read_url_content", "search_web"):
        n_web = _count_tool_invocations(("web_fetch", "read_url_content", "search_web"))
        if "search" in name:
            return f"searching web ({n_web})" if n_web > 1 else "searching web"
        return f"fetching web ({n_web})" if n_web > 1 else "fetching web"

    # Generic or MCP tool
    if not name:
        return "running..."
    clean_name = name
    if len(clean_name) > 16:
        clean_name = clean_name[:13] + "..."
    return f"tool: {clean_name}"


def is_subagent_running(session: Any) -> bool:
    """Canonical running predicate for subagent sessions.

    Single source of truth for UI grouping (running vs completed), the live
    progress badge and kill availability. Sessions are created as ACTIVE and
    flip to RUNNING once their stream starts, so both count as running.
    """
    if session is None:
        return False
    if isinstance(session, dict):
        if "is_running" in session and isinstance(session["is_running"], bool):
            return session["is_running"]
        st = str(session.get("status") or "").lower()
        return st in ("running", "active")
    if hasattr(session, "is_running"):
        val = getattr(session, "is_running")
        if isinstance(val, bool):
            return val
    st_str = (getattr(session, "status", "") or "").lower()
    return st_str in ("running", "active") or getattr(session, "is_running", None) is True


def _count_session_steps(session: Any) -> int:
    """Count agent loop iterations / steps for a session."""
    if session is None:
        return 0
    step_cnt = session.get("step_count") if isinstance(session, dict) else getattr(session, "step_count", None)
    if isinstance(step_cnt, int) and step_cnt > 0:
        return step_cnt
    history = session.get("agent_history") if isinstance(session, dict) else getattr(session, "agent_history", None)
    if isinstance(history, list) and history:
        cnt = sum(1 for m in history if isinstance(m, dict) and m.get("role") == "assistant")
        if cnt > 0:
            return cnt
    messages = session.get("messages") if isinstance(session, dict) else getattr(session, "messages", None)
    if isinstance(messages, list) and messages:
        cnt = sum(1 for m in messages if isinstance(m, dict) and m.get("type") in ("bot", "tool"))
        if cnt > 0:
            return cnt
    return 0


def extract_subagent_progress(session: Any) -> str:
    """Extract a short, human-like activity/status badge for a subagent session.

    Used by the /subagents modal to display live progress on the right side.
    """
    if session is None:
        return ""

    st_str = (
        (session.get("status") if isinstance(session, dict) else getattr(session, "status", "")) or "unknown"
    ).lower()
    if not is_subagent_running(session):
        parts = []
        if st_str in ("completed", "done"):
            parts.append("done")
        elif st_str in ("cancelled", "canceled"):
            parts.append("cancelled")
        elif st_str in ("error", "failed"):
            parts.append("error")
        else:
            parts.append(st_str or "done")

        steps = _count_session_steps(session)
        if steps > 0:
            step_str = "step" if steps == 1 else "steps"
            parts.append(f"{steps} {step_str}")

        created_at = session.get("created_at") if isinstance(session, dict) else getattr(session, "created_at", None)
        updated_at = session.get("updated_at") if isinstance(session, dict) else getattr(session, "updated_at", None)
        if (
            created_at is not None
            and updated_at is not None
            and isinstance(created_at, (int, float))
            and isinstance(updated_at, (int, float))
            and created_at > 0
            and updated_at >= created_at
        ):
            dur = format_duration(max(0.0, updated_at - created_at))
            if dur:
                parts.append(dur)

        return " • ".join(parts)

    messages = getattr(session, "messages", [])
    if not isinstance(messages, (list, tuple)) or not messages:
        return "starting..."

    # Slice events belonging to the current step / batch
    batch_events: List[Dict[str, Any]] = []
    for evt in reversed(messages):
        if not isinstance(evt, dict):
            continue
        etype = evt.get("type")
        batch_events.append(evt)
        if etype == "user":
            break
        if etype == "bot":
            if any(e.get("type") == "tool" and e.get("tool_type") for e in batch_events):
                batch_events.pop()
                break
        elif etype == "thinking":
            if any(e.get("type") == "tool" and e.get("tool_type") for e in batch_events):
                batch_events.pop()
                break
    batch_events.reverse()

    for evt in reversed(batch_events):
        etype = evt.get("type")
        if etype == "tool":
            tool_type = evt.get("tool_type") or ""
            args = evt.get("args") or {}
            target = evt.get("target") or ""
            if tool_type:
                return _format_active_tool_progress(tool_type, args, target, turn_events=batch_events)
            continue
        elif etype == "thinking":
            if evt.get("duration") is None or evt.get("duration") == 0:
                return "thinking..."
            continue
        elif etype == "bot":
            txt = evt.get("text", "")
            if isinstance(txt, str) and txt.strip():
                return "generating..."
        elif etype == "user":
            return "starting..."

    return "running..."
