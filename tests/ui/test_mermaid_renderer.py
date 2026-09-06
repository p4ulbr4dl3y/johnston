from unittest.mock import MagicMock, PropertyMock, patch

from rich.text import Text
from textual._context import active_app
from textual.content import Content
from textual.widgets import Button

from widgets.presentation.widgets.chat_markdown import CustomMarkdownFence, prewarm_fences_from_markdown
from widgets.utils.mermaid_renderer import (
    _store_cache,
    clean_mermaid_code,
    clear_mermaid_cache,
    format_mermaid_content,
    is_mermaid,
    prewarm_mermaid,
    render_mermaid_to_ascii,
)


class TestMermaidRenderer:
    def setup_method(self):
        clear_mermaid_cache()

    def test_is_mermaid(self):
        assert is_mermaid("mermaid") is True
        assert is_mermaid("MERMAID") is True
        assert is_mermaid(" mmd ") is True
        assert is_mermaid("python") is False
        assert is_mermaid("") is False
        assert is_mermaid(None) is False

    def test_clean_mermaid_code(self):
        assert clean_mermaid_code("") == ""
        assert clean_mermaid_code("graph TD\n  A --> B") == "graph TD\n  A --> B"
        wrapped = "```mermaid\ngraph TD\n  A --> B\n```"
        assert clean_mermaid_code(wrapped) == "graph TD\n  A --> B"

    def test_clean_mermaid_code_normalizes_shapes(self):
        code = "flowchart TD\n  A(Round) --> B{Decision}\n  B --> C[(Database)]"
        cleaned = clean_mermaid_code(code)
        assert "A[Round]" in cleaned
        assert "B[Decision]" in cleaned
        assert "C[Database]" in cleaned

    def test_normalize_flowchart_shapes_edge_cases(self):
        code = """---
title: Sample Frontmatter
---
graph TD
    Client["Клиент (Web / Mobile)"] -->|HTTPS (secure)| Gateway(API Gateway)
    subgraph Sub (test group)
        Gateway --> Auth{Токен валиден?}
    end
    Узел(Кириллица) --> DB[(PostgreSQL)]
"""
        cleaned = clean_mermaid_code(code)
        # Quoted labels and edge labels preserved
        assert 'Client["Клиент (Web / Mobile)"]' in cleaned
        assert "|HTTPS (secure)|" in cleaned
        assert "subgraph Sub (test group)" in cleaned
        # Shapes normalized
        assert "Gateway[API Gateway]" in cleaned
        assert "Auth[Токен валиден?]" in cleaned
        assert "Узел[Кириллица]" in cleaned
        assert "DB[PostgreSQL]" in cleaned

    def test_normalize_flowchart_shapes_quoted_edges_and_escaped_quotes(self):
        code = '''graph TD
    A["Hello \\"world\\" (app)"] -->|"quoted (edge)"| B(Round)
'''
        cleaned = clean_mermaid_code(code)
        assert '__MERMAID_PH_' not in cleaned
        assert 'A["Hello \\"world\\" (app)"]' in cleaned
        assert '|"quoted (edge)"|' in cleaned
        assert 'B[Round]' in cleaned

    def test_render_mermaid_valid(self):
        code = "graph TD\n    A[Start] --> B[End]"
        result = render_mermaid_to_ascii(code)
        assert result is not None
        assert "Start" in result
        assert "End" in result

    def test_render_mermaid_utf8_encoding_param(self):
        code = "graph TD\n    A[Начало] --> B[Конец]"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="┌───┐\n│ A │\n└───┘")
            render_mermaid_to_ascii(code)
            assert mock_run.call_args.kwargs.get("encoding") == "utf-8"

    def test_fix_mojibake(self):
        from widgets.utils.mermaid_renderer import _fix_mojibake

        mojibake = "──Ð\x9dÐµÑ\x82──"
        fixed = _fix_mojibake(mojibake)
        assert "Нет" in fixed
        assert len(fixed) == len(mojibake)
        assert fixed.startswith("─") and fixed.endswith("─")

        space_mojibake = "  Ð\x94Ð°  "
        fixed_space = _fix_mojibake(space_mojibake)
        assert "Да" in fixed_space
        assert len(fixed_space) == len(space_mojibake)

    def test_render_mermaid_cached(self):
        code = "graph TD\n    A[X] --> B[Y]"
        first = render_mermaid_to_ascii(code)
        with patch("subprocess.run") as mock_run:
            second = render_mermaid_to_ascii(code)
            mock_run.assert_not_called()
        assert first == second

    def test_render_mermaid_invalid_syntax(self):
        result = render_mermaid_to_ascii("definitely not mermaid syntax 12345")
        assert result is None

    def test_render_mermaid_empty_code(self):
        assert render_mermaid_to_ascii("") is None
        assert render_mermaid_to_ascii("   ") is None

    def test_render_mermaid_missing_binary(self):
        with patch("widgets.utils.mermaid_renderer._get_mermaid_binary", return_value=None):
            assert render_mermaid_to_ascii("graph TD\n  A-->B") is None

    def test_render_mermaid_subprocess_error(self):
        with patch("subprocess.run", side_effect=Exception("binary crashed")):
            assert render_mermaid_to_ascii("graph TD\n  A-->B") is None

    def test_store_cache_eviction(self):
        with patch("widgets.utils.mermaid_renderer._CACHE_MAX_SIZE", 3):
            _store_cache("k1", "v1")
            _store_cache("k2", "v2")
            _store_cache("k3", "v3")
            _store_cache("k4", "v4")
            assert render_mermaid_to_ascii("k1") is None or "v4" in str(render_mermaid_to_ascii("k4"))

    def test_cache_thread_safety(self):
        import concurrent.futures

        def worker(idx):
            _store_cache(f"key_{idx % 10}", f"val_{idx}")
            render_mermaid_to_ascii(f"graph TD\n A{idx}-->B{idx}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(worker, i) for i in range(50)]
            for f in futures:
                f.result()

    def test_prewarm_mermaid(self):
        code = "graph TD\n    A[Pre] --> B[Warm]"
        prewarm_mermaid(code)
        with patch("subprocess.run") as mock_run:
            assert render_mermaid_to_ascii(code) is not None
            mock_run.assert_not_called()

    def test_format_mermaid_content(self):
        diagram = "┌───┐\n│ A │\n└───┘\n  ▼\n┌───┐\n│ B │\n└───┘"
        content_dark = format_mermaid_content(diagram, dark=True)
        assert isinstance(content_dark, Content)
        content_light = format_mermaid_content(diagram, dark=False)
        assert isinstance(content_light, Content)

        theme_mock = MagicMock()
        theme_mock.accent_info = "#10b981"
        theme_mock.accent_warning = "#ec4899"
        content_themed = format_mermaid_content(diagram, theme_obj=theme_mock)
        assert isinstance(content_themed, Content)


class TestCustomMarkdownFenceMermaid:
    def setup_method(self):
        clear_mermaid_cache()

    def test_compose_mermaid_fence_with_diagram(self):
        from rich.console import Console

        mock_app = MagicMock()
        mock_app._compose_stacks = [[]]
        mock_app.console = Console()
        mock_app.ansi_theme = None
        token = active_app.set(mock_app)
        try:
            fence = CustomMarkdownFence.__new__(CustomMarkdownFence)
            fence.lexer = "mermaid"
            fence.code = "graph TD\n    A[Start] --> B[Stop]"
            fence.theme = None
            fence.markdown = MagicMock(theme=None)

            # Prewarm so it is in cache
            prewarm_mermaid(fence.code)

            widgets = list(fence.compose())
            assert len(widgets) > 0
            assert fence._show_diagram is True
            assert fence._diagram_str is not None

            buttons = [w for w in widgets if isinstance(w, Button)]
            button_classes = {cls for b in buttons for cls in b.classes}
            assert "fence-toggle-btn" in button_classes
            assert "fence-copy-btn" in button_classes
        finally:
            active_app.reset(token)

    def test_toggle_diagram_view(self):
        fence = CustomMarkdownFence.__new__(CustomMarkdownFence)
        fence.code = "graph TD\n    A --> B"
        fence.lexer = "mermaid"
        fence._diagram_str = "┌───┐\n│ A │\n└───┘"
        fence._show_diagram = True
        fence._highlighted_code = Content.from_rich_text(Text(fence.code))

        toggle_btn = MagicMock(spec=Button)
        toggle_btn.classes = {"fence-toggle-btn"}
        scroll_box = MagicMock()
        fence.query_one = MagicMock(side_effect=lambda sel, cls=None: toggle_btn if "toggle" in sel else scroll_box)
        fence.set_content = MagicMock()

        # Toggle to code view
        fence.toggle_diagram_view()
        assert fence._show_diagram is False
        assert toggle_btn.label == "diagram"
        fence.set_content.assert_called_with(fence._highlighted_code)
        assert scroll_box.scroll_x == 0

        # Toggle back to diagram view
        fence.toggle_diagram_view()
        assert fence._show_diagram is True
        assert toggle_btn.label == "code"

    def test_toggle_diagram_view_no_diagram(self):
        fence = CustomMarkdownFence.__new__(CustomMarkdownFence)
        fence._diagram_str = None
        fence.set_content = MagicMock()
        fence.toggle_diagram_view()
        fence.set_content.assert_not_called()

    def test_on_button_pressed_toggle(self):
        fence = CustomMarkdownFence.__new__(CustomMarkdownFence)
        fence.toggle_diagram_view = MagicMock()

        event = MagicMock(spec=Button.Pressed)
        event.button = MagicMock(spec=Button)
        event.button.classes = {"fence-toggle-btn"}

        fence.on_button_pressed(event)
        fence.toggle_diagram_view.assert_called_once()
        event.stop.assert_called_once()

    def test_on_button_pressed_copy_diagram_and_code(self):
        fence = CustomMarkdownFence.__new__(CustomMarkdownFence)
        fence.code = "graph TD\n A-->B"
        fence._diagram_str = "┌───┐\n│ A │\n└───┘"
        mock_app = MagicMock()

        event = MagicMock(spec=Button.Pressed)
        event.button = MagicMock(spec=Button)
        event.button.classes = {"fence-copy-btn"}

        with patch.object(CustomMarkdownFence, "app", new_callable=PropertyMock, return_value=mock_app):
            # When viewing diagram -> copies diagram
            fence._show_diagram = True
            fence.on_button_pressed(event)
            mock_app.copy_to_clipboard.assert_called_with(fence._diagram_str)

            # When viewing code -> copies code
            fence._show_diagram = False
            fence.on_button_pressed(event)
            mock_app.copy_to_clipboard.assert_called_with(fence.code)

    def test_notify_style_update_mermaid(self):
        fence = CustomMarkdownFence.__new__(CustomMarkdownFence)
        fence.code = "graph TD\n  A --> B"
        fence.lexer = "mermaid"
        fence._diagram_str = "┌───┐\n│ A │\n└───┘"
        fence._show_diagram = True
        fence.set_content = MagicMock()

        fence.notify_style_update()
        fence.set_content.assert_called_once()

    def test_prewarm_fences_with_mermaid(self):
        md = "```mermaid\ngraph TD\n    A --> B\n```"
        count = prewarm_fences_from_markdown(md)
        assert count == 1

    async def test_copy_context_and_update_from_block(self):
        source = CustomMarkdownFence.__new__(CustomMarkdownFence)
        source.code = "graph TD\n  A-->B"
        source.lexer = "mermaid"
        source._diagram_str = "┌───┐\n│ A │\n└───┘"
        source._show_diagram = True
        source._highlighted_code = Content.from_rich_text(Text(source.code))
        source._token = MagicMock()

        target = CustomMarkdownFence.__new__(CustomMarkdownFence)
        target.set_content = MagicMock()
        target._classes = set()
        toggle_btn = MagicMock(spec=Button)
        target.query_one = MagicMock(return_value=toggle_btn)

        await target._update_from_block(source)
        assert target._diagram_str == source._diagram_str
        assert target._show_diagram is True
        assert toggle_btn.display is True
        assert toggle_btn.label == "code"
        target.set_content.assert_called_once()

    async def test_async_render_mermaid_on_cache_miss(self):
        fence = CustomMarkdownFence.__new__(CustomMarkdownFence)
        fence.code = "graph TD\n X-->Y"
        fence.lexer = "mermaid"
        fence._diagram_str = None
        fence._show_diagram = False
        fence._classes = set()
        fence.set_content = MagicMock()
        toggle_btn = MagicMock(spec=Button)
        fence.query_one = MagicMock(return_value=toggle_btn)

        with patch("widgets.utils.mermaid_renderer.render_mermaid_to_ascii", return_value="┌───┐\n│ X │\n└───┘"):
            await fence._async_render_mermaid()

        assert fence._diagram_str is not None
        assert fence._show_diagram is True
        assert toggle_btn.display is True
        assert toggle_btn.label == "code"
        fence.set_content.assert_called_once()

    async def test_integration_markdown_mount_pilot(self):
        from textual.app import App
        from textual.widgets import Markdown

        from widgets.presentation.widgets.chat_markdown import _apply_chat_markdown_patches

        _apply_chat_markdown_patches()

        class DummyApp(App):
            def compose(self):
                yield Markdown("```mermaid\ngraph TD\n  A-->B\n```")

        app = DummyApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            fence = app.screen.query_one(CustomMarkdownFence)
            assert fence is not None
            toggle_btn = fence.query_one(".fence-toggle-btn", Button)
            assert toggle_btn is not None



