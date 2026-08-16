import os
import time


class GitMetricsMixin:
    """Shared git metrics helpers for footer widgets (diff stats + branch)."""

    _BRANCH_TTL = 5.0

    def _git_branch(self, cwd: str | None = None) -> str:
        """Return the current git branch name or '' when not in a repo.

        Branch lookups funnel through ``get_git_info`` which already caches
        per-directory for 30s; layer a small TTL cache here too so the footer
        spinner tick never triggers a git subprocess even off the event loop.
        """
        now = time.time()
        target_cwd = cwd or os.getcwd()
        if (
            getattr(self, "_branch_text", None) is not None
            and getattr(self, "_branch_cwd", None) == target_cwd
            and now - getattr(self, "_branch_time", 0.0) < self._BRANCH_TTL
        ):
            return self._branch_text
        try:
            from core.application.generation.prompt_builder import get_git_info

            info = (get_git_info(cwd=target_cwd) or "").strip()
            if info.startswith("branch '"):
                branch = info[len("branch '") : -1]
            elif info.startswith("detached HEAD"):
                branch = info.replace("detached HEAD (", "detached (").rstrip(")")
            else:
                branch = ""
        except Exception:
            branch = ""
        if branch or getattr(self, "_branch_cwd", None) != target_cwd:
            self._branch_text = branch
            self._branch_cwd = target_cwd
            self._branch_time = now
        return branch or getattr(self, "_branch_text", "")

    def _git_diff_stats(self, cwd: str | None = None) -> str:
        """Return '+add/-del' line-count diff vs HEAD, cached 5s. Returns '' when unavailable."""
        now = time.time()
        target_cwd = cwd or os.getcwd()
        if (
            getattr(self, "_diff_text", None) is not None
            and getattr(self, "_diff_cwd", None) == target_cwd
            and now - getattr(self, "_diff_time", 0.0) < 5.0
        ):
            return self._diff_text
        # Kick off an async computation so the footer never blocks on git when
        # the diff isn't cached yet; render shows the last known value meanwhile.
        if getattr(self, "_diff_loading", False):
            return getattr(self, "_diff_text", "") or ""
        self._diff_loading = True
        self._diff_cwd = target_cwd
        import asyncio

        try:
            asyncio.get_running_loop().create_task(self._compute_diff_async(target_cwd))
        except RuntimeError:
            text = self._compute_diff_sync(target_cwd)
            self._diff_loading = False
            self._diff_text = text
            self._diff_time = time.time()
        return getattr(self, "_diff_text", "") or ""

    async def _compute_diff_async(self, cwd: str | None = None) -> None:
        import asyncio
        import time

        try:
            text = await asyncio.to_thread(self._compute_diff_sync, cwd)
        finally:
            self._diff_loading = False
        self._diff_text = text
        self._diff_time = time.time()
        try:
            if self.is_mounted:
                self._on_diff_updated()
        except Exception:
            pass

    def _compute_diff_sync(self, cwd: str | None = None) -> str:
        text = ""
        try:
            import subprocess

            target_cwd = cwd or os.getcwd()
            res = subprocess.run(
                ["git", "diff", "HEAD", "--numstat"],
                capture_output=True,
                text=True,
                timeout=2,
                cwd=target_cwd,
            )
            if res.returncode != 0:
                res = subprocess.run(
                    ["git", "diff", "--numstat"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    cwd=target_cwd,
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

    def _on_diff_updated(self) -> None:
        """Hook called after an async diff finishes; override in subclasses."""
