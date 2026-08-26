import unittest
from unittest.mock import MagicMock, patch

from widgets.app.status_state import (
    _ensure_cache,
    build_status_kwargs,
    refresh_footer_cache,
)


class TestStatusState(unittest.IsolatedAsyncioTestCase):
    def _status_app(self):
        app = MagicMock()
        cm = MagicMock()
        cm.get_active_provider_key.return_value = "openai"
        cm.load_providers.return_value = {"openai": {"name": "OpenAI"}}
        cm.is_provider_connected.return_value = False
        app.pm = cm
        agent = MagicMock()
        agent.model = "gpt"
        agent.get_metrics.return_value = {}
        app.agent = agent
        return app

    async def test_collect_cache_load_providers_raises(self):
        from widgets.app import status_state as ss

        pm = MagicMock()
        pm.load_providers.side_effect = Exception("boom")
        app = MagicMock(pm=pm)
        with patch("core.application.skills.manager.SkillManager.list_skills"), patch(
            "core.infrastructure.mcp.get_mcp_manager"
        ):
            providers, vis, total, mcp = ss._collect_cache(app)
        self.assertEqual(providers, {})

    async def test_collect_cache_skills_raises(self):
        from widgets.app import status_state as ss

        with patch(
            "core.application.skills.manager.SkillManager.list_skills", side_effect=Exception("boom")
        ), patch("core.infrastructure.mcp.get_mcp_manager"):
            vis, total = ss._collect_cache(MagicMock(pm=None))[1:3]
        self.assertEqual((vis, total), (0, 0))

    async def test_collect_cache_mcp_raises(self):
        from widgets.app import status_state as ss

        with patch("core.infrastructure.mcp.get_mcp_manager", side_effect=Exception("boom")):
            mcp = ss._collect_cache(MagicMock(pm=None))[3]
        self.assertEqual(mcp, [])

    async def test_refresh_footer_cache_collect_raises(self):
        from widgets.app import status_state as ss

        with patch.object(ss, "_collect_cache", side_effect=Exception("boom")):
            await refresh_footer_cache(MagicMock(), MagicMock())

    async def test_refresh_footer_cache_widget_refresh_raises(self):
        app = MagicMock()
        widget = MagicMock()
        widget._st_cache_time = 0
        widget.is_mounted = True
        widget.refresh_footer = MagicMock(side_effect=Exception("boom"))
        await refresh_footer_cache(app, widget)
        self.assertGreater(widget._st_cache_time, 0)

    def test_ensure_cache_sync_fallback_collect_raises(self):
        # No running loop + _collect_cache raises -> swallowed, loading cleared.
        from widgets.app import status_state as ss

        app = MagicMock()
        widget = MagicMock()
        widget._st_cache_time = 0
        widget._st_cache_loading = False
        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")), patch.object(
            ss, "_collect_cache", side_effect=Exception("boom")
        ):
            _ensure_cache(app, widget)
        self.assertFalse(widget._st_cache_loading)

    def test_ensure_cache_no_widget_returns(self):
        _ensure_cache(MagicMock(), None)

    async def test_ensure_cache_no_loop_sync_fallback(self):
        app = MagicMock()
        widget = MagicMock()
        widget._st_cache_time = 0
        widget._st_cache_loading = False
        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            _ensure_cache(app, widget)
        self.assertFalse(widget._st_cache_loading)

    async def test_build_status_kwargs_no_widget_collect_raises(self):
        from widgets.app import status_state as ss

        app = self._status_app()
        with patch.object(ss, "_collect_cache", side_effect=Exception("boom")):
            kwargs = build_status_kwargs(app, widget=None)
        self.assertIn("provider_key", kwargs)

    async def test_build_status_kwargs_no_widget_loads_providers_and_mcp(self):
        app = self._status_app()
        with patch("widgets.app.status_state.get_mcp_manager") as gm:
            mgr = MagicMock()
            mgr.load_servers.return_value = [{"command": "python"}]
            gm.return_value = mgr
            kwargs = build_status_kwargs(app, widget=None)
        self.assertEqual(kwargs["provider_key"], "openai")
        self.assertEqual(kwargs["mcp_total"], 1)


# ---------------------------------------------------------------------------
# widgets/patch.py
# ---------------------------------------------------------------------------
