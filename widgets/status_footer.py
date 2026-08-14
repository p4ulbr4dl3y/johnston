import os

from rich.table import Table
from textual.widgets import Static

from core.defaults.config import THEME_PRIMARY, THEME_SECONDARY, THEME_SUBTLE
from core.models_catalog import catalog, format_context_tokens
from core.thinking_effort import display_thinking_effort

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class StatusFooter(Static):
    """Two-line status footer below chat"""

    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, *args, is_subagent: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.is_subagent: bool = is_subagent
        self.is_generating: bool = False
        self._spinner_idx: int = 0
        self._spinner_timer = None
        self._resize_timer = None
        self._last_resize_size = None

    def set_generating(self, generating: bool) -> None:
        if self.is_generating == generating:
            return
        self.is_generating = generating
        if generating:
            if not self._spinner_timer:
                self._spinner_timer = self.set_interval(0.2, self._spin)
        else:
            if self._spinner_timer:
                self._spinner_timer.stop()
                self._spinner_timer = None
            self._spinner_idx = 0
        self.refresh_footer()

    def _spin(self) -> None:
        self._spinner_idx = (self._spinner_idx + 1) % len(SPINNER_FRAMES)
        if hasattr(self, "_last_status_args"):
            self.update_status(**self._last_status_args)
        else:
            self.refresh_footer()

    def on_mount(self) -> None:
        self.refresh_footer()
        # While MCP servers are still warming up (or their tool counts change),
        # poll so the footer spinner and loaded-server count stay current even
        # when not generating.
        self._mcp_poll_timer = self.set_interval(1.0, self._poll_mcp_refresh)

    def _poll_mcp_refresh(self) -> None:
        try:
            from core.mcp_manager import get_mcp_manager

            mm = get_mcp_manager()
            is_loading = mm.is_loading()
            was_loading = getattr(self, "_mcp_was_loading", False)
            if is_loading or was_loading:
                self._mcp_was_loading = is_loading
                self.refresh_footer()
                return
            # Not loading: keep the loaded-server count live so the footer
            # reflects MCP servers that finished warming up after the window
            # above (or drifted since). `refresh_footer` caches mcp servers for
            # 5s, but the client/tool state is read fresh each call, so this is
            # cheap enough at a 1s cadence.
            active = self._active_mcp_count(get_mcp_manager().load_servers())
            if active != getattr(self, "_mcp_last_active", None):
                self._mcp_last_active = active
                self.refresh_footer()
        except Exception:
            pass

    def _active_mcp_count(self, servers) -> int:
        """Count enabled MCP servers that finished loading tools (no error, has tools)."""
        from core.mcp_manager import get_mcp_manager

        mm = get_mcp_manager()
        count = 0
        for s in servers:
            s_name = s.get("name")
            cmd = s.get("command")
            url = s.get("url")
            if url and not cmd:
                continue
            if s.get("disabled", False):
                continue
            client = mm.clients.get(s_name) if hasattr(mm, "clients") else None
            if client is None:
                continue
            if getattr(client, "last_error", None):
                continue
            if not getattr(client, "tools", None):
                continue
            count += 1
        return count

    def refresh_footer(self) -> None:
        try:
            import time

            from core.mcp_manager import get_mcp_manager
            from core.skill_manager import SkillManager

            pm = getattr(self.app, "pm", None)
            pkey = pm.get_active_provider_key() if pm else "default"
            agent = getattr(self.app, "agent", None)
            model_name = getattr(agent, "model", "")
            providers = pm.load_providers() if pm else {}
            provider_info = providers.get(pkey, {}) if isinstance(providers, dict) else {}
            provider_display = provider_info.get("name", pkey) if provider_info else pkey
            is_connected = pm.is_provider_connected(pkey, provider_info) if (pm and pkey) else False
            clean_model = catalog.get_model_display_name(pkey, model_name)
            if not clean_model:
                clean_model = "[Select model: /models]"
            if pm and hasattr(pm, "get_provider_thinking_effort"):
                effort_val = pm.get_provider_thinking_effort(pkey, model_name)
            else:
                effort_val = getattr(agent, "thinking_effort", None)
            thinking_effort = display_thinking_effort(effort_val)
            metrics = agent.get_metrics() if (agent and hasattr(agent, "get_metrics")) else {}

            now = time.time()
            if not hasattr(self, "_cached_skills") or (now - getattr(self, "_skills_cache_time", 0) > 5.0):
                all_skills = SkillManager().list_skills(include_hidden=True)
                skills_total = len(all_skills)
                skills_visible = sum(1 for s in all_skills if not s.get("hidden"))
                self._cached_skills = (skills_visible, skills_total)
                self._skills_cache_time = now
            skills_visible, skills_total = getattr(self, "_cached_skills", (0, 0))

            if not hasattr(self, "_cached_mcp_servers") or (now - getattr(self, "_mcp_cache_time", 0) > 5.0):
                self._cached_mcp_servers = get_mcp_manager().load_servers()
                self._mcp_cache_time = now
            mcp_servers = self._cached_mcp_servers

            # Count only servers that are actually loading (enabled, stdio
            # command) and of those, only the ones that finished loading: a
            # running client that discovered tools and has no error. Pending or
            # errored servers don't count, so while loading the footer flips to
            # the spinner.
            mcp_total = 0
            for s in mcp_servers:
                if s.get("url") and not s.get("command"):
                    continue
                mcp_total += 1
            mcp_active = self._active_mcp_count(mcp_servers)
            from core.task_collection import collect_current_tasks

            bg_tasks, sessions = collect_current_tasks(self.app, getattr(self.app, "current_session_id", None))

            active_bg_tasks = len(
                [t for t in bg_tasks if getattr(t, "is_running", False) and getattr(t, "is_background", True)]
            )

            subagents_active = len([s for s in sessions if getattr(s, "status", "") == "running"])
            subagents_total = len(sessions)

            agent_role = getattr(agent, "role", "worker")

            kwargs = {
                "provider_key": pkey,
                "provider_display": provider_display,
                "is_connected": is_connected,
                "model_name": model_name,
                "clean_model": clean_model,
                "agent_role": agent_role,
                "directory": os.path.basename(os.path.realpath(os.getcwd())),
                "active_bg_tasks": active_bg_tasks,
                "subagents_active": subagents_active,
                "subagents_total": subagents_total,
                "context_used": metrics.get("context_used", 0),
                "total_tokens": metrics.get("total_tokens", 0),
                "context_window": metrics.get("context", "128k"),
                "context_limit": metrics.get("context_limit", 128000),
                "cost_usd": metrics.get("cost_usd", 0.0),
                "thinking_effort": thinking_effort,
                "skills_visible": skills_visible,
                "skills_total": skills_total,
                "mcp_active": mcp_active,
                "mcp_total": mcp_total,
            }
            self._last_status_args = kwargs
            self.update_status(**kwargs)
        except Exception:
            self.update_status(provider_key="default")

    def update_subagent_footer(self, session) -> None:
        """Render footer for a subagent session using its own agent/dir/branch/metrics."""
        try:
            agent = getattr(session, "agent", None)
            model_name = getattr(agent, "model", "") if agent else ""
            role = getattr(agent, "role", "worker") if agent else getattr(session, "role", "worker")
            effort_val = getattr(agent, "thinking_effort", None) if agent else None
            thinking_effort = display_thinking_effort(effort_val) if effort_val else "auto"
            metrics = agent.get_metrics() if (agent and hasattr(agent, "get_metrics")) else {}
            provider_key = getattr(agent, "provider_key", "") if agent else ""

            pm = getattr(self.app, "pm", None)
            if not provider_key and pm:
                provider_key = pm.get_active_provider_key()
            providers = pm.load_providers() if pm else {}
            provider_info = providers.get(provider_key, {}) if isinstance(providers, dict) else {}
            provider_display = provider_info.get("name", provider_key) if provider_info else provider_key
            is_connected = pm.is_provider_connected(provider_key, provider_info) if (pm and provider_key) else False
            clean_model = catalog.get_model_display_name(provider_key, model_name) if model_name else ""
            if not clean_model:
                clean_model = "[Select model: /models]"

            directory = getattr(session, "project_dir", "") or os.path.basename(os.path.realpath(os.getcwd()))
            if os.path.basename(directory) != directory:
                directory = os.path.basename(os.path.normpath(directory)) or directory

            context_used = metrics.get("context_used") or getattr(session, "last_context_tokens", 0)
            total_tokens = metrics.get("total_tokens") or getattr(session, "total_tokens", 0)
            cost_usd = metrics.get("cost_usd") or getattr(session, "cost_usd", 0.0)
            context_window = metrics.get("context", "128k")
            context_limit = metrics.get("context_limit", 128000)

            role_formatted = f"{SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]} " if self.is_generating else ""
            role_formatted += role.capitalize()

            self._render_subagent(
                role_formatted=role_formatted,
                provider_display=provider_display or provider_key.capitalize(),
                clean_model=clean_model or "[Select model: /models]",
                is_connected=is_connected,
                model_name=model_name,
                context_used=context_used,
                total_tokens=total_tokens,
                context_limit=context_limit,
                context_window=context_window,
                cost_usd=cost_usd,
                thinking_effort=thinking_effort,
                directory=directory,
                branch_name=getattr(session, "branch_name", ""),
            )
        except Exception:
            self.refresh_footer()

    def _render_subagent(
        self,
        role_formatted: str,
        provider_display: str,
        clean_model: str,
        is_connected: bool,
        model_name: str,
        context_used: int,
        total_tokens: int,
        context_limit: int,
        context_window: str,
        cost_usd: float,
        thinking_effort: str,
        directory: str = "",
        branch_name: str = "",
    ) -> None:
        """Footer for the subagent screen: role/model, context/tokens, dir/branch."""
        branch = branch_name or self._git_branch()
        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")

        row1_left_parts = [f"[bold {THEME_PRIMARY}]{role_formatted}[/bold {THEME_PRIMARY}]"]
        if is_connected and provider_display and clean_model and clean_model != "[Select model: /models]":
            row1_left_parts.append(f"[{THEME_SECONDARY}]{provider_display} › {clean_model}[/]")
        grid.add_row("  •  ".join(row1_left_parts), "")

        # Line 2: [context]  [tokens • cost • effort]
        if is_connected and bool(model_name):
            pct = (context_used / context_limit * 100) if context_limit > 0 else 0.0
            pct = min(100.0, max(0.0, pct))
            bar_len = 8
            filled = int(round((pct / 100) * bar_len))
            bar_str = "█" * filled + "░" * (bar_len - filled)
            row2_left = (
                f"Context: [{THEME_SUBTLE}][{bar_str}][/] "
                f"[{THEME_SECONDARY}]{pct:.1f}% ({format_context_tokens(context_used)}/{context_window})[/]"
            )
        else:
            row2_left = f"[{THEME_SUBTLE}]Run /connect to set up API key.[/{THEME_SUBTLE}]"
        cost_str = "$0" if cost_usd == 0 else f"${cost_usd:.4f}"
        row2_right_parts = [
            f"[{THEME_SECONDARY}]{total_tokens:,} tok[/]",
            f"[{THEME_SECONDARY}]{cost_str}[/]",
            f"[{THEME_SECONDARY}]effort:{thinking_effort}[/]",
        ]
        row2_right = "  •  ".join(row2_right_parts)
        grid.add_row(row2_left, row2_right)

        # Line 3: [directory • branch]  [+N / -M]
        dir_text = f"~/{directory}" if directory else ""
        row3_left_parts = [f"[{THEME_SECONDARY}]{dir_text}[/]"]
        if branch:
            row3_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/]")
        row3_left = "  •  ".join(row3_left_parts)
        grid.add_row(row3_left, self._git_diff_right())

        self.update(grid)

    def _mcp_footer_text(self, mcp_active: int, mcp_total: int, prefix: str = "MCP:") -> str:
        """MCP indicator: show active/total count as 'N/M'."""
        return f"{prefix} [{THEME_SECONDARY}]{mcp_active}/{mcp_total}[/{THEME_SECONDARY}]"

    def update_status(
        self,
        provider_key: str,
        provider_display: str | None = None,
        is_connected: bool | None = None,
        model_name: str = "",
        clean_model: str | None = None,
        agent_role: str = "action",
        directory: str = "",
        active_bg_tasks: int = 0,
        subagents_active: int = 0,
        subagents_total: int = 0,
        context_used: int = 0,
        total_tokens: int = 0,
        context_window: str = "128k",
        context_limit: int = 128000,
        cost_usd: float = 0.0,
        thinking_effort: str = "auto",
        skills_visible: int = 0,
        skills_total: int = 0,
        mcp_active: int = 0,
        mcp_total: int = 0,
    ) -> None:
        if not directory:
            directory = os.path.basename(os.path.realpath(os.getcwd())) or "root"

        dir_text = f"~/{directory}"
        if provider_display is None:
            provider_display = provider_key.capitalize() if provider_key else ""
        if is_connected is None:
            pm = getattr(self.app, "pm", None)
            is_connected = pm.is_provider_connected(provider_key) if (pm and provider_key) else bool(provider_key)
        if clean_model is None:
            clean_model = catalog.get_model_display_name(provider_key, model_name)
            if not clean_model:
                clean_model = "[Select model: /models]"
        role_str = agent_role.capitalize()
        if self.is_generating:
            frame = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
            role_formatted = f"{frame} {role_str}"
        else:
            role_formatted = role_str

        if self.is_subagent:
            self._render_subagent(
                role_formatted=role_formatted,
                provider_display=provider_display or provider_key.capitalize(),
                clean_model=clean_model or "[Select model: /models]",
                is_connected=is_connected,
                model_name=model_name,
                context_used=context_used,
                total_tokens=total_tokens,
                context_limit=context_limit,
                context_window=context_window,
                cost_usd=cost_usd,
                thinking_effort=thinking_effort,
                directory=directory,
            )
            return

        width = (
            self.size.width
            if (self.size and self.size.width > 0)
            else (self.app.size.width if (self.app and self.app.size) else 80)
        )
        is_compact = width > 0 and width < 75

        if is_compact:
            branch = self._git_branch()

            row1_parts = [f"[bold {THEME_PRIMARY}]{role_formatted}[/]"]
            if is_connected and provider_display and clean_model and clean_model != "[Select model: /models]":
                row1_parts.append(f"[{THEME_SECONDARY}]{clean_model}[/]")
            row1_parts.append(self._mcp_footer_text(mcp_active, mcp_total))
            row1 = " • ".join(row1_parts)

            row2_parts = [f"[{THEME_SECONDARY}]{dir_text}[/]"]
            if branch:
                row2_parts.append(f"[{THEME_PRIMARY}]{branch}[/]")
            row2_parts.append(f"[{THEME_SECONDARY}]{total_tokens:,}t[/]")
            diff_text = self._git_diff_stats()
            if diff_text:
                row2_parts.append(f"[{THEME_SECONDARY}]{diff_text}[/]")
            row2 = " • ".join(row2_parts)

            if is_connected and bool(model_name):
                pct = (context_used / context_limit * 100) if context_limit > 0 else 0.0
                pct = min(100.0, max(0.0, pct))
                pct_str = "0%" if pct == 0 else f"{pct:.0f}%"
                row3 = f"Ctx: [{THEME_SECONDARY}]{pct_str}[/]"
                task_parts = []
                if subagents_active > 0:
                    task_parts.append(f"{subagents_active}agent")
                if active_bg_tasks > 0:
                    task_parts.append(f"{active_bg_tasks}shell")
                if task_parts:
                    row3 += f" • [{THEME_SECONDARY}]{', '.join(task_parts)}[/]"
            else:
                row3 = f"[{THEME_SUBTLE}]Run /connect[/{THEME_SUBTLE}]"

            grid = Table.grid(expand=True)
            grid.add_column(justify="left")
            grid.add_row(row1)
            grid.add_row(row2)
            if row3:
                grid.add_row(row3)
            grid.add_row("", "")
            self.update(grid)
            return
        else:
            branch = self._git_branch()

            # Line 1: [role • provider › model]  [skills • mcp]
            row1_left_parts = [f"[bold {THEME_PRIMARY}]{role_formatted}[/]"]
            if is_connected and provider_display and clean_model and clean_model != "[Select model: /models]":
                row1_left_parts.append(f"[{THEME_SECONDARY}]{provider_display} › {clean_model}[/]")
            row1_left = "  •  ".join(row1_left_parts)
            row1_right_parts = [
                f"Skills: [{THEME_SECONDARY}]{skills_visible}/{skills_total}[/]"
                if skills_total > 0
                else f"Skills: [{THEME_SECONDARY}]0[/]",
                self._mcp_footer_text(mcp_active, mcp_total, prefix="MCP:"),
            ]
            row1_right = "  •  ".join(row1_right_parts)

            # Line 2: [context]  [tokens • cost • effort]
            if is_connected and bool(model_name):
                ctx_val = context_used
                pct = (ctx_val / context_limit * 100) if context_limit > 0 else 0.0
                pct = min(100.0, max(0.0, pct))
                bar_len = 8
                filled = int(round((pct / 100) * bar_len))
                bar_str = "█" * filled + "░" * (bar_len - filled)
                used_formatted = format_context_tokens(ctx_val)
                row2_left = (
                    f"Context: [{THEME_SUBTLE}][{bar_str}][/] "
                    f"[{THEME_SECONDARY}]{pct:.1f}% ({used_formatted}/{context_window})[/]"
                )
            else:
                row2_left = f"[{THEME_SUBTLE}]Run /connect to set up API key.[/{THEME_SUBTLE}]"
            cost_str = "$0" if cost_usd == 0 else f"${cost_usd:.4f}"
            row2_right_parts = [
                f"[{THEME_SECONDARY}]{total_tokens:,} tok[/]",
                f"[{THEME_SECONDARY}]{cost_str}[/]",
                f"[{THEME_SECONDARY}]effort:{thinking_effort}[/]",
            ]
            row2_right = "  •  ".join(row2_right_parts)

            # Line 3: [directory • branch]  [diff • agents • shells]
            row3_left_parts = [f"[{THEME_SECONDARY}]{dir_text}[/]"]
            if branch:
                row3_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/]")
            row3_left = "  •  ".join(row3_left_parts)

            row3_right_parts = []
            diff_text = self._git_diff_right()
            if diff_text:
                row3_right_parts.append(diff_text)
            task_parts = []
            if subagents_active > 0:
                task_parts.append(
                    f"{subagents_active} agent" if subagents_active == 1 else f"{subagents_active} agents"
                )
            if active_bg_tasks > 0:
                task_parts.append(f"{active_bg_tasks} shell")
            if task_parts:
                row3_right_parts.extend(f"[{THEME_SECONDARY}]{p}[/]" for p in task_parts)
            row3_right = "  •  ".join(row3_right_parts)

            grid = Table.grid(expand=True)
            grid.add_column(justify="left")
            grid.add_column(justify="right")
            grid.add_row(row1_left, row1_right)
            grid.add_row(row2_left, row2_right)
            grid.add_row(row3_left, row3_right)
            grid.add_row("", "")

            self.update(grid)
            return

    def _git_diff_stats(self) -> str:
        """Return '+add/-del' line-count diff vs HEAD, cached 5s. Returns '' when unavailable."""
        import time

        now = time.time()
        if getattr(self, "_diff_text", None) is not None and now - getattr(self, "_diff_time", 0.0) < 5.0:
            return self._diff_text
        # Kick off an async computation so the footer never blocks on git when
        # the diff isn't cached yet; render shows the last known value meanwhile.
        if getattr(self, "_diff_loading", False):
            return getattr(self, "_diff_text", "") or ""
        self._diff_loading = True
        import asyncio

        try:
            asyncio.get_running_loop().create_task(self._compute_diff_async())
        except RuntimeError:
            text = self._compute_diff_sync()
            self._diff_loading = False
            self._diff_text = text
            self._diff_time = time.time()
        return getattr(self, "_diff_text", "") or ""

    async def _compute_diff_async(self) -> None:
        import asyncio
        import time

        try:
            text = await asyncio.to_thread(self._compute_diff_sync)
        finally:
            self._diff_loading = False
        self._diff_text = text
        self._diff_time = time.time()
        try:
            if self.is_mounted:
                self.refresh_footer()
        except Exception:
            pass

    def _compute_diff_sync(self) -> str:
        text = ""
        try:
            import subprocess

            res = subprocess.run(
                ["git", "diff", "HEAD", "--numstat"],
                capture_output=True,
                text=True,
                timeout=2,
                cwd=os.getcwd(),
            )
            if res.returncode == 0 and res.stdout.strip():
                adds = dels = 0
                for line in res.stdout.splitlines():
                    parts = line.split("\t")
                    if len(parts) < 2:
                        continue
                    try:
                        adds += int(parts[0])
                        dels += int(parts[1])
                    except ValueError:
                        pass
                if adds or dels:
                    text = f"+{adds} / -{dels}"
        except Exception:
            pass
        return text

    def _git_diff_right(self) -> str:
        """Coloured '+N / -M' git diff counts for the footer's right column."""
        diff = self._git_diff_stats()
        if not diff:
            return ""
        return f"[{THEME_SECONDARY}]{diff}[/]"

    def _git_branch(self) -> str:
        """Return the current git branch name or '' when not in a repo."""
        try:
            from core.prompt_builder import get_git_info

            info = (get_git_info() or "").strip()
            if info.startswith("branch '"):
                return info[len("branch '") : -1]
            if info.startswith("detached HEAD"):
                return info.replace("detached HEAD (", "detached (").rstrip(")")
            return ""
        except Exception:
            return ""

    def on_resize(self, event) -> None:
        size = getattr(event, "size", None)
        if size is not None and size == self._last_resize_size:
            return
        self._last_resize_size = size
        if self._resize_timer is not None:
            self._resize_timer.stop()
            self._resize_timer = None
        self._resize_timer = self.set_timer(0.15, self._debounced_refresh)

    def _debounced_refresh(self) -> None:
        self._resize_timer = None
        self.refresh_footer()
