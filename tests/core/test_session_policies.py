"""Tests for the shared user-turn policy (core.domain.policies.messages).

The policy defines what counts as a "real user turn" in both message spaces
(transcript events and agent history). Fork, rewind, git-checkpoint indexing
and persistence all rely on these walks producing identical cutoffs, so the
fork/rewind equivalence test below is the regression guard against divergence.
"""

import os
import shutil
import tempfile
import unittest

from core.application.session.actions import _truncate_transcript
from core.domain.entities.session import AgentSession
from core.domain.policies.messages import (
    count_history_user_turns,
    drop_stale_system_notes,
    find_history_user_cutoff,
    find_visible_user_cutoff,
    history_before_turn,
    is_checkpoint_message,
    is_real_history_user_turn,
    is_system_note,
    is_ui_visible_user_message,
    transcript_before_turn,
)
from core.session_manager import SessionStore


def _make_store(test_dir: str) -> SessionStore:
    project_path = os.path.join(test_dir, "proj")
    os.makedirs(project_path, exist_ok=True)
    return SessionStore(project_path=project_path)


TRANSCRIPT = [
    {"type": "user", "text": "first"},
    {"type": "bot", "text": "reply1"},
    {"type": "user", "text": "[System Notification] Background shell finished"},
    {"type": "tool", "tool_type": "shell", "target": "ls", "result_text": "ok"},
    {"type": "user", "text": "[System Note: Response interrupted by user]"},
    {"type": "user", "text": "second", "show_in_ui": True},
    {"type": "bot", "text": "reply2"},
    {"type": "user", "text": "third-hidden", "show_in_ui": False},
    {"type": "user", "text": "fourth"},
]

HISTORY = [
    {"role": "user", "content": "<conversation_checkpoint>\nEarlier summary."},
    {"role": "assistant", "content": "summary text"},
    {"role": "user", "content": [{"type": "text", "text": "<conversation_checkpoint> list form"}]},
    {"role": "user", "content": "[System Note: interrupted]"},
    {"role": "user", "content": "first"},
    {"role": "assistant", "content": "reply1"},
    {"role": "user", "content": "second"},
    {"role": "assistant", "content": "reply2"},
    {"role": "user", "content": "fourth"},
]


class TestTranscriptPolicy(unittest.TestCase):
    def test_is_ui_visible_user_message(self):
        self.assertTrue(is_ui_visible_user_message({"type": "user", "text": "hello"}))
        self.assertFalse(is_ui_visible_user_message({"type": "user", "text": "hi", "show_in_ui": False}))
        self.assertFalse(is_ui_visible_user_message({"type": "user", "text": "[System Note: x]"}))
        self.assertFalse(is_ui_visible_user_message({"type": "user", "text": "[System Notification] y"}))
        self.assertFalse(is_ui_visible_user_message("not a dict"))
        self.assertFalse(is_ui_visible_user_message(None))

    def test_find_visible_user_cutoff_counts_only_visible_turns(self):
        # Visible turns: "first" (0), "second" (5), "fourth" (8).
        self.assertEqual(find_visible_user_cutoff(TRANSCRIPT, 0), 0)
        self.assertEqual(find_visible_user_cutoff(TRANSCRIPT, 1), 5)
        self.assertEqual(find_visible_user_cutoff(TRANSCRIPT, 2), 8)
        self.assertIsNone(find_visible_user_cutoff(TRANSCRIPT, 3))

    def test_drop_stale_system_notes_keeps_notifications(self):
        kept = drop_stale_system_notes(TRANSCRIPT[:6])
        texts = [m.get("text") for m in kept]
        self.assertIn("[System Notification] Background shell finished", texts)
        self.assertNotIn("[System Note: Response interrupted by user]", texts)

    def test_transcript_before_turn(self):
        kept = transcript_before_turn(TRANSCRIPT, 1)
        # Notifications are kept; only stale [System Note: entries are dropped.
        self.assertEqual(
            [m.get("text") for m in kept if m.get("type") == "user"],
            ["first", "[System Notification] Background shell finished"],
        )

    def test_transcript_before_turn_unknown_turn_returns_filtered_full(self):
        kept = transcript_before_turn(TRANSCRIPT, 99)
        self.assertEqual(len(kept), len(TRANSCRIPT) - 1)  # only the stale note dropped


class TestHistoryPolicy(unittest.TestCase):
    def test_is_checkpoint_message_matches_list_content_and_summary(self):
        self.assertTrue(is_checkpoint_message({"role": "user", "content": "<conversation_checkpoint> x"}))
        self.assertTrue(is_checkpoint_message({"role": "user", "content": "<summary> x"}))
        self.assertTrue(
            is_checkpoint_message({"role": "user", "content": [{"type": "text", "text": "<conversation_checkpoint>"}]})
        )
        self.assertFalse(is_checkpoint_message({"role": "user", "content": "plain"}))
        self.assertFalse(is_checkpoint_message(None))

    def test_is_system_note(self):
        self.assertTrue(is_system_note({"role": "user", "content": "[System Note: x]"}))
        self.assertFalse(is_system_note({"role": "user", "content": ["[System Note: x]"]}))
        self.assertFalse(is_system_note("not a dict"))

    def test_real_user_turn_excludes_checkpoints_and_notes(self):
        flags = [is_real_history_user_turn(m) for m in HISTORY]
        self.assertEqual(flags, [False, False, False, False, True, False, True, False, True])

    def test_count_history_user_turns_ignores_list_form_checkpoints(self):
        # A weak string-only walk would count the list-form checkpoint entry.
        self.assertEqual(count_history_user_turns(HISTORY), 3)

    def test_find_history_user_cutoff(self):
        self.assertEqual(find_history_user_cutoff(HISTORY, 0), 4)
        self.assertEqual(find_history_user_cutoff(HISTORY, 2), 8)
        self.assertIsNone(find_history_user_cutoff(HISTORY, 3))

    def test_history_before_turn_unknown_turn_returns_full(self):
        self.assertEqual(history_before_turn(HISTORY, 7), HISTORY)


class TestForkRewindEquivalence(unittest.TestCase):
    """Fork's partial copy and rewind's transcript truncation must agree."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = _make_store(self.tmpdir)
        self.sid = "session_equiv"
        src = self.store.create_main(self.sid)
        src.description = "equiv"
        src.messages = [dict(m) for m in TRANSCRIPT]
        src.agent_history = [dict(m) for m in HISTORY]

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _rewind_style_truncation(self, seq_idx: int) -> list:
        sess = AgentSession.from_dict(self.store.get(self.sid).to_dict())
        _truncate_transcript(sess, seq_idx)
        return sess.messages

    def test_partial_fork_matches_rewind_truncation(self):
        for seq_idx in (0, 1, 2):
            with self.subTest(seq_idx=seq_idx):
                forked = self.store.fork_session(self.sid, up_to_msg_index=seq_idx)
                expected = self._rewind_style_truncation(seq_idx) if seq_idx > 0 else []
                self.assertEqual(forked.messages, expected)
                # Fork must not mutate the source session.
                self.assertEqual(len(self.store.get(self.sid).messages), len(TRANSCRIPT))

    def test_fork_history_prefix_skips_hidden_entries(self):
        forked = self.store.fork_session(self.sid, up_to_msg_index=2)
        contents = [m.get("content") for m in forked.agent_history]
        self.assertIn("<conversation_checkpoint>\nEarlier summary.", contents)
        self.assertIn("second", contents)
        self.assertNotIn("fourth", contents)

    def test_full_fork_copies_everything(self):
        forked = self.store.fork_session(self.sid)
        self.assertEqual(forked.messages, TRANSCRIPT)
        self.assertEqual(forked.agent_history, HISTORY)


if __name__ == "__main__":
    unittest.main()
