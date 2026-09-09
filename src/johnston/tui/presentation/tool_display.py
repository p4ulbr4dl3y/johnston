"""Presentational tool-call display helpers (textual chip labels).

Moved out of ``core/application/display.py``: this module produces UI-facing
markup (escape_markup / extract_tool_display). Domain and application must not
own rendering-format output, so these helpers live in the infrastructure
presentation area consumed by core widgets and UI tests.
"""
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from johnston.core.infrastructure.runtime.lru import LruCache
from johnston.tui.utils.row_format import format_duration

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


def format_compact_dict(d: dict, max_total_len: int = 70) -> str:
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
        if total_len + len(item_str) > max_total_len:
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


_SUFFIX_RE = re.compile(r":(?:(?:\d+(?:-\d+|\+)?(?::\d+)?)|(?:\+[\d.]+[KMG]?B))$")
_HOME_DIR = os.path.abspath(os.path.expanduser("~"))
_HOME_REAL = os.path.realpath(_HOME_DIR)


def split_path_suffix(path: str) -> Tuple[str, str]:
    """Split path and line/offset suffix (e.g. 'file.py:10-20' -> ('file.py', ':10-20'))."""
    if not isinstance(path, str) or not path:
        return (path if isinstance(path, str) else "", "")
    match = _SUFFIX_RE.search(path)
    if match:
        idx = match.start()
        return path[:idx], path[idx:]
    return path, ""


def _is_child_relpath(rel: str) -> bool:
    """True if rel is a child path and not traversing upward (excluding false positive '..foo')."""
    return rel != ".." and not rel.startswith(f"..{os.sep}") and not rel.startswith("../")


def shorten_path(path: str, cwd: Optional[str] = None) -> str:
    """Shorten path for display: relative to CWD if inside, or ~/ if inside $HOME."""
    if not isinstance(path, str) or not path.strip():
        return path if isinstance(path, str) else ""

    raw_path = path.strip()
    base_path, suffix = split_path_suffix(raw_path)
    if not base_path:
        return raw_path.replace("\\", "/")

    if base_path in ("./", ".\\"):
        base_path = "."
    elif base_path.startswith("./") or base_path.startswith(".\\"):
        base_path = base_path[2:]

    is_home_start = base_path == "~" or base_path.startswith("~/") or base_path.startswith("~\\")
    if not os.path.isabs(base_path) and not is_home_start:
        return (base_path.replace("\\", "/") if base_path != "." else ".") + suffix

    try:
        norm = os.path.abspath(os.path.expanduser(base_path))
        curr_dir = os.path.abspath(cwd or os.getcwd())

        # 1. Check relative to CWD / workspace (fast path without realpath)
        try:
            rel = os.path.relpath(norm, curr_dir)
            if _is_child_relpath(rel):
                return (rel.replace("\\", "/") if rel != "." else ".") + suffix
        except (ValueError, OSError):
            pass

        # Check symlink-resolved CWD
        try:
            norm_real = os.path.realpath(norm)
            curr_real = os.path.realpath(curr_dir)
            if norm_real != norm or curr_real != curr_dir:
                rel = os.path.relpath(norm_real, curr_real)
                if _is_child_relpath(rel):
                    return (rel.replace("\\", "/") if rel != "." else ".") + suffix
        except (ValueError, OSError):
            pass

        # 2. Check relative to HOME
        try:
            rel = os.path.relpath(norm, _HOME_DIR)
            if _is_child_relpath(rel):
                return (f"~/{rel.replace(os.sep, '/')}" if rel != "." else "~") + suffix
        except (ValueError, OSError):
            pass

        try:
            norm_real = os.path.realpath(norm)
            if norm_real != norm:
                rel = os.path.relpath(norm_real, _HOME_REAL)
                if _is_child_relpath(rel):
                    return (f"~/{rel.replace(os.sep, '/')}" if rel != "." else "~") + suffix
        except (ValueError, OSError):
            pass
    except Exception:
        pass
    return raw_path.replace("\\", "/")


def truncate_path(path: str, max_len: int = 60) -> str:
    """Truncate path preserving filename and innermost directories."""
    if not isinstance(path, str):
        return ""
    path = shorten_path(path)
    if len(path) <= max_len:
        return path
    parts = path.replace("\\", "/").split("/")
    if len(parts) <= 1:
        head = max(1, min(len(path), (max_len - 3) * 2 // 5))
        tail = max(0, max_len - 3 - head)
        return path[:head] + "..." + (path[-tail:] if tail > 0 else "")
    filename = parts[-1]
    if len(filename) >= max_len - 4:
        half = max(1, (max_len - 3) // 2)
        tail = max(0, max_len - 3 - half)
        return filename[:half] + "..." + (filename[-tail:] if tail > 0 else "")
    res = filename
    for p in reversed(parts[:-1]):
        if not p:
            continue
        candidate = f"{p}/{res}"
        if len(candidate) + 4 > max_len:
            break
        res = candidate
    return f".../{res}"


def truncate(target: str, max_len: int = 60, mode: str = "middle") -> str:
    """Collapse whitespace and clip a display label to a UI-friendly length.

    Modes:
    - 'middle': preserves head and tail (default for general finished strings).
    - 'right': preserves head and truncates tail (best for live streaming).
    - 'path': preserves filename and innermost directories.
    """
    if not isinstance(target, str):
        return escape_markup(str(target)) if target else ""
    target = re.sub(r"\s+", " ", target).strip()
    if mode == "path":
        target = truncate_path(target, max_len)
        return escape_markup(target)
    if len(target) <= max_len:
        return escape_markup(target)
    if mode == "right":
        target = target[: max(0, max_len - 3)] + "..."
    else:
        if max_len == 60:
            target = target[:25] + "..." + target[-32:]
        else:
            head = max(1, min(len(target), (max_len - 3) * 2 // 5))
            tail = max(0, max_len - 3 - head)
            target = target[:head] + "..." + (target[-tail:] if tail > 0 else "")
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


def _display_cache_key(tool_name: str, args: Dict[str, Any], max_len: int = 60, mode: str = "middle") -> tuple:
    try:
        cwd = os.getcwd()
    except Exception:
        cwd = ""
    return (str(tool_name), _canonical_args(args), max_len, mode, cwd)


def extract_tool_display(tool_name: str, args: Dict[str, Any], max_len: int = 60, mode: str = "middle") -> str:
    """Build a short, human-readable label describing what a tool call targets."""
    key = _display_cache_key(tool_name, args, max_len, mode)
    hit = _DISPLAY_CACHE.get(key)
    if hit is not None:
        return hit

    result = _extract_tool_display_inner(tool_name, args, max_len=max_len, mode=mode)

    _DISPLAY_CACHE.put(key, result)
    return result


def _extract_tool_display_inner(tool_name: str, args: Dict[str, Any], max_len: int = 60, mode: str = "middle") -> str:
    from johnston.core.infrastructure.runtime.tool_name import normalize_tool_name as _normalize
    from johnston.core.tools.registry import REGISTRY

    name = _normalize(tool_name)
    args = args if isinstance(args, dict) else {}
    is_builtin = name in REGISTRY

    if not is_builtin:
        # MCP/custom tools: single predefined format — compact ``{k: v, ...}``
        # args label (empty parens when no args).
        return format_compact_dict(args, max_total_len=max_len + 10)

    if name == "ask_user":
        qs = args.get("questions")
        if isinstance(qs, list) and qs:
            formatted = []
            for q in qs:
                q_text = q.get("question") if isinstance(q, dict) else ""
                if q_text:
                    formatted.append(str(q_text).strip())
            if formatted:
                return truncate(", ".join(f'"{t}"' for t in formatted), max_len=max_len, mode=mode)
        return ""

    if name == "invoke_subagent":
        title = str(args.get("title") or "").strip()
        role = str(args.get("type") or args.get("role") or "worker").strip()
        from johnston.core.application.roles.role_registry import get_role_display_name

        role_cap = get_role_display_name(role)
        if title:
            return truncate(f'{role_cap}: "{title}"', max_len=max_len, mode=mode)
        return truncate(role_cap, max_len=max_len, mode=mode)
    if name == "kill":
        tid = str(args.get("id") or args.get("task_id") or args.get("session_id") or "").strip()
        if tid:
            return truncate(tid, max_len=max_len, mode=mode)
        return ""

    if name == "message_subagent":
        tid = str(args.get("id") or args.get("session_id") or "").strip()
        msg = str(args.get("message") or "").strip()
        if tid and msg:
            return truncate(f'to {tid}: "{msg}"', max_len=max_len, mode=mode)
        if tid:
            return truncate(f"to {tid}", max_len=max_len, mode=mode)
        if msg:
            return truncate(f'"{msg}"', max_len=max_len, mode=mode)
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
                return truncate(f"{completed}/{total}: {active_step}", max_len=max_len, mode=mode)
            return f"{completed}/{total} done"
        return ""

    file_mode = "path" if mode in ("middle", "path") else mode

    if name == "read":
        val = args.get("path")
        if isinstance(val, str) and val:
            path_str = shorten_path(val.strip())

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
            return truncate(f"{path_str}{suffix}", max_len=max_len, mode=file_mode)
        return ""

    if name in ("create", "edit"):
        val = args.get("path")
        if isinstance(val, str) and val:
            return truncate(shorten_path(val.strip()), max_len=max_len, mode=file_mode)
        return ""

    if name == "shell":
        cmd = args.get("command")
        if isinstance(cmd, str) and cmd:
            return truncate(cmd, max_len=max_len, mode=mode)
        return ""

    if name == "web_fetch":
        url = args.get("url")
        if isinstance(url, str) and url:
            return truncate(url, max_len=max_len, mode=mode)
        return ""

    if name == "search":
        q = str(args.get("query") or "").strip()
        p = str(args.get("path") or "").strip()
        search_mode = str(args.get("mode") or "").strip()
        glob_pat = str(args.get("glob") or "").strip()
        include_hidden = bool(args.get("include_hidden", False))
        parts = []
        if search_mode and search_mode != "content":
            parts.append(search_mode)
        if q:
            parts.append(f'"{q}"')
        if p:
            short_p = shorten_path(p)
            if short_p and short_p != ".":
                parts.append(f"in {short_p}")
        if glob_pat:
            parts.append(f"[{glob_pat}]")
        if include_hidden:
            parts.append("(+hidden)")
        return truncate(" ".join(parts) if parts else "codebase", max_len=max_len, mode=mode)

    return ""


def _format_active_tool_progress(
    tool_name: str,
    args: Dict[str, Any],
    target: str = "",
    turn_events: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Format an active tool invocation into a short, human-like activity badge."""
    from johnston.core.infrastructure.runtime.tool_name import normalize_tool_name as _normalize

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

    if name in ("search", "search_code"):
        n_searches = _count_tool_invocations(("search", "search_code"))
        return f"searching codebase ({n_searches})" if n_searches > 1 else "searching codebase"

    if name == "update_plan":
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


def _count_session_turns(session: Any) -> int:
    """Count agent loop iterations / turns for a session."""
    if session is None:
        return 0
    step_cnt = session.get("step_count") if isinstance(session, dict) else getattr(session, "step_count", None)
    if isinstance(step_cnt, int) and step_cnt > 0:
        return step_cnt
    turn_cnt = session.get("turn_count") if isinstance(session, dict) else getattr(session, "turn_count", None)
    if isinstance(turn_cnt, int) and turn_cnt > 0:
        return turn_cnt
    messages = session.get("messages") if isinstance(session, dict) else getattr(session, "messages", None)
    if isinstance(messages, list) and messages:
        cnt = sum(
            1
            for m in messages
            if isinstance(m, dict) and (m.get("type") == "bot" or (m.get("type") == "tool" and m.get("tool_type")))
        )
        if cnt > 0:
            return cnt
    history = session.get("agent_history") if isinstance(session, dict) else getattr(session, "agent_history", None)
    if isinstance(history, list) and history:
        cnt = sum(1 for m in history if isinstance(m, dict) and m.get("role") == "assistant")
        if cnt > 0:
            return cnt
    return 0


_count_session_steps = _count_session_turns


def extract_subagent_plan_status(session: Any) -> Optional[Tuple[int, int]]:
    """Return (done_count, total_count) if session has an active/completed plan."""
    if session is None:
        return None
    plan = getattr(session, "current_plan", None) if not isinstance(session, dict) else session.get("current_plan")
    if not isinstance(plan, list):
        plan = None
    if not plan:
        agent = getattr(session, "agent", None)
        if agent:
            plan = getattr(agent, "current_plan", None)
            if not isinstance(plan, list):
                plan = None
    if not plan:
        messages = session.get("messages") if isinstance(session, dict) else getattr(session, "messages", None)
        if messages and isinstance(messages, (list, tuple)):
            for msg in reversed(messages):
                if isinstance(msg, dict) and msg.get("type") == "tool" and msg.get("tool_type") == "update_plan":
                    args = msg.get("args") or {}
                    if isinstance(args, dict) and isinstance(args.get("plan"), list):
                        p = [it for it in args.get("plan") if isinstance(it, dict)]
                        if p:
                            plan = p
                            break
    if plan and isinstance(plan, list) and len(plan) > 0:
        done = sum(1 for item in plan if isinstance(item, dict) and item.get("status") == "completed")
        total = len(plan)
        return done, total
    return None


def extract_subagent_progress(session: Any) -> str:
    """Extract a short, human-like activity/status badge for a subagent session.

    Used by the /subagents modal to display live progress on the right side.
    """
    if session is None:
        return ""

    plan_status = extract_subagent_plan_status(session)
    plan_prefix = f"[{plan_status[0]}/{plan_status[1]}] " if plan_status is not None else ""

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

        turns = _count_session_turns(session)
        if turns > 0:
            turn_str = "turn" if turns == 1 else "turns"
            parts.append(f"{turns} {turn_str}")

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

        return f"{plan_prefix}{' • '.join(parts)}"

    messages = getattr(session, "messages", [])
    if not isinstance(messages, (list, tuple)) or not messages:
        return f"{plan_prefix}starting..." if plan_prefix else "starting..."

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
                raw_badge = _format_active_tool_progress(tool_type, args, target, turn_events=batch_events)
                if plan_prefix:
                    return f"{plan_prefix}{raw_badge}"
                return raw_badge
            continue
        elif etype == "thinking":
            if evt.get("duration") is None or evt.get("duration") == 0:
                return f"{plan_prefix}thinking..." if plan_prefix else "thinking..."
            continue
        elif etype == "bot":
            txt = evt.get("text", "")
            if isinstance(txt, str) and txt.strip():
                return f"{plan_prefix}generating..." if plan_prefix else "generating..."
        elif etype == "user":
            return f"{plan_prefix}starting..." if plan_prefix else "starting..."

    return f"{plan_prefix}running..." if plan_prefix else "running..."
