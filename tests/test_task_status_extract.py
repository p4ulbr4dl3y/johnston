"""Unit tests for the canonical background-task status extraction helper.

``extract_task_status_details`` in ``core/infrastructure/tasks/manage.py`` is the
single source of truth for status/duration used by both ``manage.py`` itself and
the UI (``widgets/presentation/screens/tasks.py``).
"""

import time
import unittest
from unittest.mock import MagicMock

from core.infrastructure.tasks.manage import extract_task_status_details


def _mk_task(**kwargs):
    t = MagicMock()
    t.is_running = False
    t.status = None
    t.created_at = None
    t.completed_at = None
    t.exit_code = None
    t.process = None
    t.was_killed = False
    for k, v in kwargs.items():
        setattr(t, k, v)
    return t


class TestExtractTaskStatusDetails(unittest.TestCase):
    def test_none(self):
        self.assertEqual(extract_task_status_details(None), ("finished", "-"))

    def test_running(self):
        t = _mk_task(is_running=True, created_at=time.time() - 5.0)
        status, dur = extract_task_status_details(t)
        self.assertEqual(status, "running")
        self.assertIn("5", dur)

    def test_running_without_created_at(self):
        t = _mk_task(is_running=True, created_at=None)
        self.assertEqual(extract_task_status_details(t), ("running", "-"))

    def test_completed_exit_zero(self):
        t = _mk_task(
            status="completed",
            created_at=100.0,
            completed_at=105.0,
            exit_code=0,
        )
        self.assertEqual(extract_task_status_details(t), ("exit:0", "5.0s"))

    def test_finished_exit_zero_without_exit_code(self):
        t = _mk_task(status="finished", created_at=None)
        self.assertEqual(extract_task_status_details(t), ("exit:0", "-"))

    def test_error_exit_one(self):
        t = _mk_task(status="error", created_at=None)
        self.assertEqual(extract_task_status_details(t), ("exit:1", "-"))

    def test_exit_code_from_process_returncode(self):
        t = _mk_task(status="", exit_code=None, process=MagicMock(returncode=2))
        self.assertEqual(extract_task_status_details(t), ("exit:2", "-"))

    def test_killed(self):
        t = _mk_task(was_killed=True, status="killed")
        self.assertEqual(extract_task_status_details(t), ("killed", "-"))

    def test_killed_via_status(self):
        t = _mk_task(was_killed=False, status="killed")
        self.assertEqual(extract_task_status_details(t), ("killed", "-"))

    def test_timeout(self):
        t = _mk_task(status="timeout")
        self.assertEqual(extract_task_status_details(t), ("timeout", "-"))

    def test_unknown_status_maps_to_finished(self):
        t = _mk_task(status="paused")
        self.assertEqual(extract_task_status_details(t), ("finished", "-"))


if __name__ == "__main__":
    unittest.main()
