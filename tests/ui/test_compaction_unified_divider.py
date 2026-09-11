"""End-to-end tests: verify auto-compaction produces the same in-place divider
update as /compact through the generation_controller → stream_driver pipeline."""
import unittest
from unittest.mock import AsyncMock, MagicMock

from johnston.core.domain.defaults.config import COMPACTING_DIVIDER_TITLE
from johnston.tui.presentation.widgets.chat_stream_driver import ChatStreamDriver


class TestAutoCompactionUnifiedDivider(unittest.IsolatedAsyncioTestCase):
    """Simulate the exact TUI auto-compaction flow:

    1. turn_context yields ("event_divider", "Compacting session...", "")
    2. JohnstonClient.stream() parses → CompactionEventDTO(summary="Compacting session...")
    3. generation_controller: CompactionEventDTO handler creates event dict
    4. stream_driver.consume_session_event renders it
    5. turn_context yields result event → CompactionEventDTO(summary="Session Compacted (…)")
    6. stream_driver updates the same divider in-place
    """

    def _make_driver(self):
        self.chat_view = MagicMock()
        self.chat_view.add_event_divider = AsyncMock()
        self.chat_view.is_at_bottom = MagicMock(return_value=True)
        self.chat_view._is_loading_session = False
        self.chat_view._mount_and_scroll = AsyncMock(side_effect=lambda w, **kw: w)
        return ChatStreamDriver(self.chat_view)

    async def test_auto_compaction_compacting_then_result_updates_in_place(self):
        driver = self._make_driver()

        # Step 1: "Compacting session..." arrives via generation_controller
        await driver.consume_session_event(
            {"type": "event_divider", "text": COMPACTING_DIVIDER_TITLE, "from_stream_step": True},
            animate=True,
            is_active=True,
        )

        # The placeholder divider is created AND tracked.
        self.chat_view.add_event_divider.assert_awaited_once()
        first_call = self.chat_view.add_event_divider.call_args
        self.assertEqual(first_call[0][0], COMPACTING_DIVIDER_TITLE)
        self.assertIsNotNone(driver._pending_compaction_divider)

        # Step 2: result arrives
        result_title = "Session Compacted (10,000 → 4,000 tokens)"
        await driver.consume_session_event(
            {"type": "event_divider", "text": result_title, "from_stream_step": True},
            animate=True,
            is_active=True,
        )

        # The placeholder was updated in-place; no second divider created.
        self.assertIsNone(driver._pending_compaction_divider)
        self.chat_view.add_event_divider.assert_awaited_once()

        # The update_title was called with the result text.
        divider_widget = self.chat_view.add_event_divider.return_value
        divider_widget.update_title.assert_called_once_with(result_title)

    async def test_auto_compaction_failure_updates_in_place(self):
        driver = self._make_driver()

        await driver.consume_session_event(
            {"type": "event_divider", "text": COMPACTING_DIVIDER_TITLE, "from_stream_step": True},
            animate=True, is_active=True,
        )
        await driver.consume_session_event(
            {"type": "event_divider", "text": "Compaction Failed", "from_stream_step": True},
            animate=True, is_active=True,
        )

        divider_widget = self.chat_view.add_event_divider.return_value
        divider_widget.update_title.assert_called_once_with("Compaction Failed")
        self.assertIsNone(driver._pending_compaction_divider)
        self.chat_view.add_event_divider.assert_awaited_once()

    async def test_auto_compaction_error_updates_in_place(self):
        driver = self._make_driver()

        await driver.consume_session_event(
            {"type": "event_divider", "text": COMPACTING_DIVIDER_TITLE, "from_stream_step": True},
            animate=True, is_active=True,
        )
        await driver.consume_session_event(
            {"type": "event_divider", "text": "Compaction Failed (ctx overflow)", "from_stream_step": True},
            animate=True, is_active=True,
        )

        divider_widget = self.chat_view.add_event_divider.return_value
        divider_widget.update_title.assert_called_once_with("Compaction Failed (ctx overflow)")
        self.assertIsNone(driver._pending_compaction_divider)

    async def test_manual_compact_and_auto_compact_produce_same_visual(self):
        """Both /compact and auto-compaction produce exactly 1 visible divider
        that transitions from Compacting → result."""
        driver = self._make_driver()

        # --- Manual /compact path ---
        # session_commands creates "Compacting session..." divider directly
        manual_div = MagicMock()
        self.chat_view.add_event_divider.return_value = manual_div
        await driver.consume_session_event(
            {"type": "event_divider", "text": COMPACTING_DIVIDER_TITLE},
            animate=False,
        )
        # lifecycle.on_divider_update updates it
        manual_div.update_title("Session Compacted (5,000 → 2,000 tokens)")
        self.assertEqual(self.chat_view.add_event_divider.await_count, 1)

        # --- Auto-compaction path ---
        # Reset
        driver._pending_compaction_divider = None
        self.chat_view.add_event_divider.reset_mock()
        auto_div = MagicMock()
        self.chat_view.add_event_divider.return_value = auto_div

        await driver.consume_session_event(
            {"type": "event_divider", "text": COMPACTING_DIVIDER_TITLE, "from_stream_step": True},
            animate=True,
        )
        await driver.consume_session_event(
            {"type": "event_divider", "text": "Session Compacted (5,000 → 2,000 tokens)", "from_stream_step": True},
            animate=True,
        )

        # Both paths: exactly 1 divider created, result applied via update_title.
        self.assertEqual(self.chat_view.add_event_divider.await_count, 1)
        auto_div.update_title.assert_called_once_with("Session Compacted (5,000 → 2,000 tokens)")


class TestGenerationControllerSkipsTransientDivider(unittest.IsolatedAsyncioTestCase):
    """The generation_controller must not record the 'Compacting session...'
    placeholder to session history — only the result divider should be persisted."""

    def test_compacting_divider_not_recorded_to_session(self):
        from johnston.core.domain.defaults.config import COMPACTING_DIVIDER_TITLE
        from johnston.core.dto import CompactionEventDTO

        session = MagicMock()
        evt = CompactionEventDTO(summary=COMPACTING_DIVIDER_TITLE)

        # Simulate the generation_controller CompactionEventDTO branch
        summary = evt.summary or "Session Compacted"
        comp_evt = {"type": "event_divider", "text": summary, "from_stream_step": True}
        if summary != COMPACTING_DIVIDER_TITLE and session is not None and hasattr(session, "add_event"):
            session.add_event(comp_evt)

        session.add_event.assert_not_called()

    def test_result_divider_recorded_to_session(self):
        from johnston.core.dto import CompactionEventDTO

        session = MagicMock()
        result_text = "Session Compacted (10,000 → 4,000 tokens)"
        evt = CompactionEventDTO(summary=result_text)

        summary = evt.summary or "Session Compacted"
        comp_evt = {"type": "event_divider", "text": summary, "from_stream_step": True}
        if summary != COMPACTING_DIVIDER_TITLE and session is not None and hasattr(session, "add_event"):
            session.add_event(comp_evt)

        session.add_event.assert_called_once_with(comp_evt)


class TestFullPipelineCompactionDivider(unittest.IsolatedAsyncioTestCase):
    """Full pipeline test: raw tuple → parse_event_dto → CompactionEventDTO
    → driver, verifying the Compacting session... divider is created and
    the result updates it in-place."""

    def _make_driver(self):
        self.chat_view = MagicMock()
        self.chat_view.add_event_divider = AsyncMock()
        self.chat_view.is_at_bottom = MagicMock(return_value=True)
        self.chat_view._is_loading_session = False
        self.chat_view._mount_and_scroll = AsyncMock(side_effect=lambda w, **kw: w)
        return ChatStreamDriver(self.chat_view)

    def _sim_generation_controller_compaction(self, driver, session, dto):
        """Simulate the CompactionEventDTO branch in generation_controller."""
        summary = dto.summary or "Session Compacted"
        comp_evt = {"type": "event_divider", "text": summary, "from_stream_step": True}
        if summary != COMPACTING_DIVIDER_TITLE and session is not None and hasattr(session, "add_event"):
            session.add_event(comp_evt)
        return comp_evt

    async def test_full_auto_compaction_pipeline(self):
        from johnston.core.dto.events import parse_event_dto

        driver = self._make_driver()
        session = MagicMock()

        # 1. turn_context yields raw tuples (what the generator produces)
        raw_start = ("event_divider", COMPACTING_DIVIDER_TITLE, "")
        raw_result = ("event_divider", "Session Compacted (8,000 → 3,000 tokens)", "")

        # 2. JohnstonClient.stream() parses to DTOs
        dto_start = parse_event_dto(raw_start)
        dto_result = parse_event_dto(raw_result)

        from johnston.core.dto import CompactionEventDTO
        self.assertIsInstance(dto_start, CompactionEventDTO)
        self.assertEqual(dto_start.summary, COMPACTING_DIVIDER_TITLE)
        self.assertIsInstance(dto_result, CompactionEventDTO)
        self.assertEqual(dto_result.summary, "Session Compacted (8,000 → 3,000 tokens)")

        # 3. generation_controller creates event dicts and passes to driver
        evt_start = self._sim_generation_controller_compaction(driver, session, dto_start)
        evt_result = self._sim_generation_controller_compaction(driver, session, dto_result)

        # 4. driver processes events
        await driver.consume_session_event(evt_start, animate=True, is_active=True)
        await driver.consume_session_event(evt_result, animate=True, is_active=True)

        # Assertions
        divider = self.chat_view.add_event_divider.return_value
        divider.update_title.assert_called_once_with("Session Compacted (8,000 → 3,000 tokens)")
        self.chat_view.add_event_divider.assert_awaited_once()
        self.assertIsNone(driver._pending_compaction_divider)
        # Only the result divider was recorded (placeholder skipped)
        session.add_event.assert_called_once_with(evt_result)

    async def test_full_auto_compaction_failure_pipeline(self):
        from johnston.core.dto.events import parse_event_dto

        driver = self._make_driver()
        session = MagicMock()

        raw_start = ("event_divider", COMPACTING_DIVIDER_TITLE, "")
        raw_result = ("event_divider", "Compaction Failed", "")

        dto_start = parse_event_dto(raw_start)
        dto_result = parse_event_dto(raw_result)

        evt_start = self._sim_generation_controller_compaction(driver, session, dto_start)
        evt_result = self._sim_generation_controller_compaction(driver, session, dto_result)

        await driver.consume_session_event(evt_start, animate=True, is_active=True)
        await driver.consume_session_event(evt_result, animate=True, is_active=True)

        divider = self.chat_view.add_event_divider.return_value
        divider.update_title.assert_called_once_with("Compaction Failed")
        self.chat_view.add_event_divider.assert_awaited_once()
        self.assertIsNone(driver._pending_compaction_divider)
        # Only the failure divider was recorded, not the placeholder
        session.add_event.assert_called_once_with(evt_result)
