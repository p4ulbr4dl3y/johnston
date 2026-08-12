"""Edge-case tests hunting for bugs in circuit_breaker and token_util.

These intentionally probe boundary conditions and hostile inputs that the
"happy path" tests in test_circuit_breaker.py / test_token_util.py do not
cover. A failing assertion here may indicate a real defect in core/.
"""
import unittest
from unittest import mock

from core.circuit_breaker import CircuitBreaker
from core.token_util import estimate_tokens, parse_usage


class _ControlledTime:
    """Allows deterministic manipulation of time.time() via mock.patch."""

    now = 1000.0

    @classmethod
    def time(cls):
        return cls.now


class TestCircuitBreakerEdgeCases(unittest.TestCase):
    def setUp(self):
        self.clock = _ControlledTime
        self.clock.now = 1000.0
        self.time_patcher = mock.patch("core.circuit_breaker.time.time", self.clock.time)
        self.time_patcher.start()
        self.addCleanup(self.time_patcher.stop)

    def test_zero_failure_threshold_opens_on_first_failure(self):
        # threshold=0: any failure >= 0 -> should OPEN immediately.
        cb = CircuitBreaker(failure_threshold=0, cooldown_seconds=60.0)
        cb.record_failure("p")
        self.assertEqual(cb.get_state("p"), "OPEN")

    def test_negative_failure_threshold_opens_on_first_failure(self):
        cb = CircuitBreaker(failure_threshold=-1, cooldown_seconds=60.0)
        cb.record_failure("p")
        # 1 >= -1 is True -> OPEN. Assert what the code does.
        self.assertEqual(cb.get_state("p"), "OPEN")

    def test_zero_cooldown_never_reports_open(self):
        # cooldown=0 -> time.time()-opened >= 0 always -> immediate HALF_OPEN.
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.0)
        cb.record_failure("p")
        # get_state immediately flips OPEN->HALF_OPEN because 0 elapsed >= 0.
        self.assertEqual(cb.get_state("p"), "HALF_OPEN")
        self.assertTrue(cb.allow_request("p"))

    def test_negative_cooldown_never_reports_open(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=-5.0)
        cb.record_failure("p")
        self.assertEqual(cb.get_state("p"), "HALF_OPEN")

    def test_get_state_open_exactly_at_expiry_boundary(self):
        # OPEN at opened=1000, cooldown=10 -> expiry exactly at now=1010.
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        cb.record_failure("p")
        self.clock.now = 1009.999
        self.assertEqual(cb.get_state("p"), "OPEN")
        self.clock.now = 1010.0  # exactly == cooldown
        # >= 0 boundary -> HALF_OPEN
        self.assertEqual(cb.get_state("p"), "HALF_OPEN")

    def test_remaining_cooldown_open_before_expiry(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        cb.record_failure("p")
        self.clock.now = 1005.0
        self.assertAlmostEqual(cb.remaining_cooldown("p"), 5.0)

    def test_remaining_cooldown_open_exactly_halfway(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        cb.record_failure("p")
        self.clock.now = 1005.0
        self.assertAlmostEqual(cb.remaining_cooldown("p"), 5.0)
        self.assertEqual(cb.get_state("p"), "OPEN")

    def test_remaining_cooldown_after_expiry_is_zero_and_flips_half_open(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        cb.record_failure("p")
        self.clock.now = 1011.0
        # remaining_cooldown calls get_state which mutates OPEN->HALF_OPEN.
        self.assertEqual(cb.remaining_cooldown("p"), 0.0)
        self.assertEqual(cb.get_state("p"), "HALF_OPEN")

    def test_record_success_on_unknown_provider(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_success("never_seen")
        self.assertEqual(cb.get_state("never_seen"), "CLOSED")
        self.assertEqual(cb._failures["never_seen"], 0)
        self.assertTrue(cb.allow_request("never_seen"))

    def test_record_failure_threshold_one_opens(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure("p")
        self.assertEqual(cb.get_state("p"), "OPEN")

    def test_half_open_success_vs_failure_after_reopen(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        cb.record_failure("p")
        self.clock.now = 1011.0  # -> HALF_OPEN
        self.assertEqual(cb.get_state("p"), "HALF_OPEN")

        # Failure in HALF_OPEN reopens immediately.
        cb.record_failure("p")
        self.assertEqual(cb.get_state("p"), "OPEN")

        # Reopen then success in HALF_OPEN closes.
        self.clock.now = 1022.0
        self.assertEqual(cb.get_state("p"), "HALF_OPEN")
        cb.record_success("p")
        self.assertEqual(cb.get_state("p"), "CLOSED")

    def test_empty_string_provider_key(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure("")
        self.assertEqual(cb.get_state(""), "OPEN")
        self.assertFalse(cb.allow_request(""))

    def test_none_provider_key(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure(None)
        self.assertEqual(cb.get_state(None), "OPEN")

    def test_many_providers_state_isolation(self):
        cb = CircuitBreaker(failure_threshold=4, cooldown_seconds=60.0)
        for i in range(10):
            cb.record_failure(f"p{i}")
        for i in range(10):
            self.assertEqual(cb.get_state(f"p{i}"), "CLOSED")

        cb.record_failure("p0")
        cb.record_failure("p0")
        cb.record_failure("p0")
        cb.record_failure("p0")
        self.assertEqual(cb.get_state("p0"), "OPEN")
        # Others untouched.
        self.assertEqual(cb.get_state("p1"), "CLOSED")
        self.assertTrue(cb.allow_request("p1"))
        self.assertFalse(cb.allow_request("p0"))

    def test_get_state_repeated_calls_half_open_are_stable(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        cb.record_failure("p")
        self.clock.now = 1011.0
        self.assertEqual(cb.get_state("p"), "HALF_OPEN")
        self.assertEqual(cb.get_state("p"), "HALF_OPEN")
        # get_state does not flip HALF_OPEN back to OPEN on its own.
        self.assertEqual(cb.get_state("p"), "HALF_OPEN")


class _NoStr:
    def __init__(self):
        pass


class _Recursive:
    def __init__(self):
        self.me = self


class _Usage:
    def __init__(self, prompt=None, completion=None, total=None, details=None):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = total
        self.prompt_tokens_details = details


class _Details:
    def __init__(self, cached=None):
        self.cached_tokens = cached


class TestTokenUtilEdgeCases(unittest.TestCase):
    def test_object_without_str_or_repr(self):
        # json.dumps raises TypeError -> fallback str() -> default repr.
        self.assertIsInstance(estimate_tokens(_NoStr()), int)

    def test_deep_dict(self):
        # Deep nesting is fine for json.dumps (no recursion limit hit).
        val = {}
        cur = val
        for _ in range(50):
            cur["k"] = {}
            cur = cur["k"]
        self.assertGreaterEqual(estimate_tokens(val), 0)

    def test_cyclic_dict_falls_back_to_str(self):
        val = {}
        val["self"] = val
        # json.dumps raises ValueError (circular) -> fallback str() must not crash.
        self.assertGreaterEqual(estimate_tokens(val), 0)

    def test_cyclic_object_falls_back_to_str(self):
        self.assertGreaterEqual(estimate_tokens(_Recursive()), 0)

    def test_set_frozenset_bytes_tuple(self):
        for val in ({1, 2, 3}, frozenset({"a", "b"}), b"bytes data", (1, 2, 3)):
            self.assertGreaterEqual(estimate_tokens(val), 0)

    def test_mixed_ascii_cyrillic_cjk_emoji(self):
        val = "abc " + "Я" + "汉字" + "😀" + "def"
        self.assertGreater(estimate_tokens(val), 0)

    def test_lone_surrogate_string(self):
        # Lone surrogate in a plain str. isascii() is False -> slow path.
        s = "a\ud800b"
        self.assertGreaterEqual(estimate_tokens(s), 0)

    def test_lone_surrogate_in_dict(self):
        # json.dumps(ensure_ascii=False) with a lone surrogate must not crash.
        self.assertGreaterEqual(estimate_tokens({"k": "a\udcffb"}), 0)

    def test_very_long_string(self):
        s = "x" * 1_000_000
        self.assertEqual(estimate_tokens(s), 250_000)

    def test_cyrillic_boundary_chars(self):
        # Single char cost 0.5 -> round(0.5)=0 (however Python rounds half to even).
        # Class boundaries: U+0400 (cyrillic start) vs U+03FF (other).
        self.assertEqual(estimate_tokens("\u0400"), 0)
        self.assertEqual(estimate_tokens("\u03ff"), 0)
        self.assertEqual(estimate_tokens("\u04ff"), 0)  # cyrillic end
        self.assertEqual(estimate_tokens("\u0500"), 0)  # other

    def test_cjk_boundary_chars(self):
        # U+4E00 (CJK start) vs U+9FFF (CJK end) vs U+A000 (other).
        # CJK cost 0.7 -> round to 1; other cost 0.5 -> round(0.5)=0.
        for ch in ("\u4e00", "\u9fff"):
            self.assertEqual(estimate_tokens(ch), 1)
        self.assertEqual(estimate_tokens("\ua000"), 0)

    def test_kana_boundary_chars(self):
        # U+3040 (kana start) vs U+30FF (kana end) vs U+3100 (other).
        for ch in ("\u3040", "\u30ff"):
            self.assertEqual(estimate_tokens(ch), 1)
        self.assertEqual(estimate_tokens("\u3100"), 0)

    def test_parse_usage_none_attributes(self):
        usage = _Usage()
        parsed = parse_usage(usage)
        self.assertEqual(parsed["prompt_tokens"], 0)
        self.assertEqual(parsed["completion_tokens"], 0)
        self.assertEqual(parsed["total_tokens"], 0)
        self.assertEqual(parsed["cache_read_tokens"], 0)

    def test_parse_usage_string_attributes(self):
        usage = _Usage(prompt="10", completion="20", total="30")
        parsed = parse_usage(usage)
        self.assertEqual(parsed["prompt_tokens"], "10")
        self.assertEqual(parsed["completion_tokens"], "20")
        self.assertEqual(parsed["total_tokens"], "30")

    def test_parse_usage_negative_and_float(self):
        usage = _Usage(prompt=-5, completion=2.5, total=-3)
        parsed = parse_usage(usage)
        # -5 is truthy so kept as-is; floats passed through.
        self.assertEqual(parsed["prompt_tokens"], -5)
        self.assertEqual(parsed["completion_tokens"], 2.5)
        self.assertEqual(parsed["total_tokens"], -3)

    def test_parse_usage_zero_total_falls_back(self):
        usage = _Usage(prompt=100, completion=50, total=0)
        parsed = parse_usage(usage)
        self.assertEqual(parsed["total_tokens"], 150)
        self.assertEqual(parsed["prompt_tokens"], 100)
        self.assertEqual(parsed["completion_tokens"], 50)

    def test_parse_usage_missing_total_falls_back(self):
        usage = _Usage(prompt=7, completion=3, total=None)
        parsed = parse_usage(usage)
        self.assertEqual(parsed["total_tokens"], 10)

    def test_parse_usage_details_missing_cached_tokens(self):
        usage = _Usage(prompt=1, completion=1, total=2, details=_Details())
        parsed = parse_usage(usage)
        self.assertEqual(parsed["cache_read_tokens"], 0)

    def test_parse_usage_details_none(self):
        usage = _Usage(prompt=1, completion=1, total=2, details=None)
        parsed = parse_usage(usage)
        self.assertEqual(parsed["cache_read_tokens"], 0)

    def test_parse_usage_details_cached_present(self):
        usage = _Usage(prompt=1, completion=1, total=2, details=_Details(cached=42))
        parsed = parse_usage(usage)
        self.assertEqual(parsed["cache_read_tokens"], 42)

    def test_parse_usage_dict_input(self):
        # parse_usage reads attributes via getattr; a plain dict yields zeros.
        parsed = parse_usage({"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10})
        self.assertEqual(parsed["prompt_tokens"], 0)
        self.assertEqual(parsed["total_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
