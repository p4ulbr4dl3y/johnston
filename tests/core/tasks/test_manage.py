import unittest
from unittest.mock import MagicMock

from core.infrastructure.tasks.manage import filter_to_session, find_any, list_lines, not_found_message


def _mk_task(tid: str, sid: str = None, running: bool = True) -> MagicMock:
    t = MagicMock()
    t.task_id = tid
    t.id = tid
    t.command = f"cmd {tid}"
    t.is_running = running
    t.session_id = sid
    t.status = "running" if running else "finished"
    t.created_at = None
    t.completed_at = None
    t.exit_code = None
    t.process = None
    t.was_killed = False
    return t


class TestFilterToSession(unittest.TestCase):
    def test_no_session_returns_all(self):
        t1 = _mk_task("a")
        t2 = _mk_task("b")
        self.assertEqual(filter_to_session([t1, t2], ""), [t1, t2])

    def test_session_filters(self):
        t1 = _mk_task("a", sid="s1")
        t2 = _mk_task("b", sid="s2")
        result = filter_to_session([t1, t2], "s1")
        self.assertEqual(result, [t1])


class TestListLines(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(list_lines([]), "no tasks active")

    def test_rows(self):
        t1 = _mk_task("a", running=True)
        t2 = _mk_task("b", running=False)
        t2.created_at = 100.0
        t2.completed_at = 105.0
        out = list_lines([t1, t2])
        self.assertIn("RUNNING", out)
        self.assertIn("EXIT:0 (5.0s)", out)


class TestFindAny(unittest.TestCase):
    def test_returns_match(self):
        t = _mk_task("tt")
        self.assertIs(find_any([t], "tt"), t)

    def test_none(self):
        self.assertIsNone(find_any([_mk_task("a")], "zz"))


    def test_with_active_ids(self):
        msg = not_found_message("ghost", [_mk_task("live")], "background")
        self.assertIn("ERR: notfound 'ghost'", msg)
        self.assertTrue("'live'" in msg or "&apos;live&apos;" in msg)

    def test_empty(self):
        msg = not_found_message("ghost", [], "background")
        self.assertIn("no active background tasks", msg.lower())


if __name__ == "__main__":
    unittest.main()
