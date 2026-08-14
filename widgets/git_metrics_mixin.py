import os


class GitMetricsMixin:
    """Shared git metrics helpers for footer widgets (diff stats + branch)."""

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
                self._on_diff_updated()
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

    def _on_diff_updated(self) -> None:
        """Hook called after an async diff finishes; override in subclasses."""
