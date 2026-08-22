"""Edge-case tests for widgets/status_footer.py update_status rendering (bug-hunting round)."""
import unittest

from rich.console import Console

from widgets.status_footer import StatusFooter


class FooterHarness(StatusFooter):
    def __init__(self, width=120):
        super().__init__()
        self.harness_width = width
        self.table = None

    @property
    def app(self):
        return None

    def update(self, markup):
        self.table = markup

    @property
    def size(self):
        class _S:
            width = self.harness_width
            height = 2

        return _S()


def _dump(table):
    con = Console(width=200, color_system=None)
    with con.capture() as cap:
        con.print(table)
    return cap.get()


class TestBasicRender(unittest.TestCase):
    def setUp(self):
        self.f = FooterHarness(width=120)

    def _render(self, **kw):
        defaults = {
            "provider_key": "openai",
            "provider_display": "OpenAI",
            "is_connected": True,
            "model_name": "gpt-4o",
            "clean_model": "GPT-4o",
        }
        defaults.update(kw)
        self.f.update_status(**defaults)
        return _dump(self.f.table)

    def test_connected_with_model_shows_context_and_tokens(self):
        out = self._render(context_used=5000, total_tokens=1234, context_window="128k", context_limit=128000)
        self.assertIn("128k", out)
        self.assertIn("1.2k tok", out)

    def test_context_display_thousands_separated(self):
        out = self._render(total_tokens=1234567, context_used=1000, context_window="200k", context_limit=200000)
        self.assertIn("1.2M tok", out)

    def test_disconnected_zero_context_no_exception(self):
        out = self._render(
            provider_key="openai",
            is_connected=False,
            model_name="",
            clean_model="",
            context_used=0,
            total_tokens=0,
            context_limit=128000,
        )
        self.assertIn("connect", out.lower())

    def test_zero_comma_format_no_crash(self):
        out = self._render(
            total_tokens=0, context_used=0, context_window="1k", context_limit=0, cost_usd=0.0, model_name="m"
        )
        self.assertIn("tok", out)

    def test_negative_context_clamped(self):
        out = self._render(context_used=-10, total_tokens=0, context_window="128k", context_limit=128000)
        self.assertIn("128k", out)

    def test_compact_mode(self):
        self.f.harness_width = 40
        out = self._render(
            context_used=0,
            total_tokens=0,
            context_window="128k",
            context_limit=128000,
            mcp_total=2,
            mcp_active=1,
        )
        self.assertIn("1mcp", out)
        self.assertIn("⚡", out)
        self.assertIn("0% ctx", out)

    def test_capitalizes_role(self):
        out = self._render(agent_role="explore")
        self.assertIn("Explore", out)


if __name__ == "__main__":
    unittest.main()
