import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import agent_usage  # noqa: E402


class TokenUsage(unittest.TestCase):
    STATE = {"stats": {"usage_to_metrics": {
        "agent": {"token_usages": [
            {"prompt_tokens": 13490, "completion_tokens": 144, "cache_read_tokens": 0},
            {"prompt_tokens": 60000, "completion_tokens": 65, "cache_read_tokens": 13616},
            {"prompt_tokens": 41000, "completion_tokens": 10, "cache_read_tokens": 0}]},
        "condenser": {"token_usages": [{"prompt_tokens": 70000}]}}}}

    def test_peak_is_the_largest_single_call_context(self):
        u = agent_usage.summarize_token_usage(self.STATE)
        self.assertEqual((u["calls"], u["condenser_calls"], u["peak_context"], u["last_context"]), (3, 1, 60000, 41000))
        self.assertEqual(u["prompt_tokens"], 114490)

    def test_missing_stats_is_zeroes_not_an_error(self):
        self.assertEqual(agent_usage.summarize_token_usage({})["peak_context"], 0)

    def test_merge_keeps_the_larger_peak_and_sums_the_rest(self):
        a = agent_usage.summarize_token_usage(self.STATE)
        m = agent_usage.merge_usage(a, agent_usage.summarize_token_usage({"stats": {"usage_to_metrics": {"agent": {"token_usages": [
            {"prompt_tokens": 90000, "completion_tokens": 1}]}}}}))
        self.assertEqual((m["calls"], m["peak_context"], m["last_context"]), (4, 90000, 90000))
        self.assertIsNone(agent_usage.merge_usage(None, None))


if __name__ == "__main__":
    unittest.main()
