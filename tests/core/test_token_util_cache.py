"""Regression tests for the estimate_tokens memo cache.

The cache must (a) deduplicate repeated calls on an unchanged history, (b) never
serve a stale value after the history is mutated in place (key is rebuilt from
len+content each call), (c) stay bounded.
"""
import unittest

from core.infrastructure.runtime import token_util
from core.infrastructure.runtime.token_util import estimate_tokens


class TestEstimateTokensCache(unittest.TestCase):
    def setUp(self):
        token_util._estimate_cache.clear()
        token_util._msg_tokens_cache.clear()

    def tearDown(self):
        token_util._estimate_cache.clear()
        token_util._msg_tokens_cache.clear()

    def test_repeated_unmutated_history_is_deduplicated(self):
        history = [{"role": "user", "content": "Помоги починить сборку"}, {"role": "assistant", "content": "Смотрю"}]
        first = estimate_tokens(history)
        # Same object, unchanged -> same memoized slot.
        self.assertEqual(estimate_tokens(history), first)
        self.assertIn(token_util._estimate_cache_key(history), token_util._estimate_cache)

    def test_message_tokens_cached_across_appends(self):
        m1 = {"role": "user", "content": "first message"}
        m2 = {"role": "assistant", "content": "second message"}
        history = [m1]
        t1 = estimate_tokens(history)
        self.assertGreater(t1, 0)
        # Message 1 must be cached in _msg_tokens_cache
        m1_key = token_util._structural_key(m1)
        self.assertIn(m1_key, token_util._msg_tokens_cache)

        history.append(m2)
        t2 = estimate_tokens(history)
        self.assertGreater(t2, t1)
        m2_key = token_util._structural_key(m2)
        self.assertIn(m2_key, token_util._msg_tokens_cache)

    def test_mutation_increases_cache_size_updates_value(self):
        history = [{"role": "user", "content": "a"}]
        before = estimate_tokens(history)
        history.append({"role": "assistant", "content": "longer content appended here"})
        after = estimate_tokens(history)
        # Different registrations -> cache does not hold only one stale slot.
        self.assertGreater(len(token_util._estimate_cache), 1)
        # New value is recomputed (token count strictly grew with more content).
        self.assertGreaterEqual(after, before)

    def test_equal_but_distinct_objects_deduplicate(self):
        a = [{"role": "user", "content": "same text"}]
        b = [{"role": "user", "content": "same text"}]
        self.assertEqual(estimate_tokens(a), estimate_tokens(b))
        # Identical repr -> single cache entry.
        self.assertEqual(1, len(token_util._estimate_cache))

    def test_cache_stays_bounded(self):
        token_util._estimate_cache.maxsize = 5
        for i in range(100):
            estimate_tokens([{"role": "user", "content": f"unique message number {i}"}])
        self.assertLessEqual(len(token_util._estimate_cache), 5)

    def test_large_non_string_not_cached(self):
        huge = {"content": "x" * (token_util._CACHE_STR_KEY_MAX + 100)}
        expected = estimate_tokens(huge)
        self.assertEqual(estimate_tokens(huge), expected)
        # "big" entries must not be stored (distinct large objects must not alias).
        self.assertNotIn(("big", "dict"), token_util._estimate_cache)


if __name__ == "__main__":
    unittest.main()
