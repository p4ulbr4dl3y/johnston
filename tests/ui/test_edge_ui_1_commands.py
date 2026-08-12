"""Edge-case tests for widgets/commands.py handle_slash_command (bug-hunting round)."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestHandleSlashCommand(unittest.IsolatedAsyncioTestCase):
    async def _call(self, text, app=None):
        app = app or MagicMock()
        from widgets.commands import handle_slash_command

        return await handle_slash_command(app, text), app

    async def test_empty_command_returns_false(self):
        handled, _ = await self._call("")
        self.assertFalse(handled)

    async def test_whitespace_only_returns_false(self):
        handled, _ = await self._call("   \t  ")
        self.assertFalse(handled)

    async def test_none_command_returns_false(self):
        from widgets.commands import handle_slash_command

        self.assertFalse(await handle_slash_command(MagicMock(), None))

    async def test_unknown_command_returns_false(self):
        handled, _ = await self._call("/definitely_not_a_command")
        self.assertFalse(handled)

    async def test_registered_command_executes_with_args(self):
        app = MagicMock()
        with patch("widgets.commands.COMMAND_REGISTRY", {"/known": MagicMock()}) as registry:
            inst = AsyncMock()
            registry["/known"].return_value = inst
            handled, _ = await self._call("/known arg1 arg2", app)
        self.assertTrue(handled)
        inst.execute.assert_awaited_once()

    async def test_empty_word_after_slash_is_not_a_command(self):
        # "/ " (slash then space) has no command word; must not match registry.
        handled, _ = await self._call("/ ")
        self.assertFalse(handled)

    async def test_multiple_whitespace_between_args(self):
        # "cmd  arg" with double space must split to earliest command word.
        with patch("widgets.commands.COMMAND_REGISTRY", {}):
            handled, _ = await self._call("/xyz  arg")
        self.assertFalse(handled)


if __name__ == "__main__":
    unittest.main()
