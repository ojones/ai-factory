import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrospective import run_summary  # noqa: E402


class SummaryRendering(unittest.TestCase):
    def test_summary_shows_usage_per_stage_and_the_run_peak(self):
        usage = lambda peak: {"calls": 3, "condenser_calls": 1, "peak_context": peak, "last_context": peak,
                              "prompt_tokens": 90000, "completion_tokens": 500, "cache_read_tokens": 80000,
                              "seconds": 125.4, "llm_seconds": 40.2}
        d = {"app": "x", "outcome": "released", "message": "ok", "cap_usd": 2.0, "spent_usd": 0.5, "review_passes": 1,
             "head_sha": "abc", "release": {"released": ["x.feature.a"]}, "blocking": [], "context_goal_tokens": 100000,
             "stages": [{"stage": "Coder", "agent": "coder", "round": "1", "cost_usd": 0.1, "verdict": "pushed", "usage": usage(54000)},
                        {"stage": "Review", "agent": "reviewer", "round": 1, "cost_usd": 0.1, "verdict": "clean", "usage": usage(120000)},
                        {"stage": "Release", "agent": "-", "round": "-", "cost_usd": 0, "verdict": "1 flag(s) released", "usage": None}]}
        out = run_summary.render_summary(d)
        self.assertIn("| 125s (40s) | 3 | 54,000 | 90,000 (80,000) | 500 | 1 |", out)
        self.assertIn("120,000 :warning:", out)
        self.assertIn("Peak context this run**: 120,000 tokens (reviewer 1), over the goal of 100,000", out)


class VerificationSummary(unittest.TestCase):
    def test_summary_shows_verification_limitations_and_scoreboard(self):
        d = {"app": "x", "outcome": "round_limit", "message": "m", "cap_usd": 2.0, "spent_usd": 0.5, "review_passes": 2,
             "head_sha": "abc", "release": None, "blocking": [], "stages": [],
             "verification": {"round": 2, "sha": "abcdef123", "limitations": ["note 4 left behind"],
                              "counts": {"passed": 3, "failed": 1, "blocked": 1, "not_run": 0}, "checks": []},
             "scoreboard": [{"round": 1, "counts": {"passed": 2, "failed": 2, "blocked": 1, "not_run": 0}, "blocking": ["a"]},
                            {"round": 2, "counts": {"passed": 3, "failed": 1, "blocked": 1, "not_run": 0}, "blocking": []}]}
        out = run_summary.render_summary(d)
        self.assertIn("3 passed, 1 failed, 1 blocked, 0 not run", out)
        self.assertIn("- note 4 left behind", out)
        self.assertIn("- round 1: 2 / 2 / 1 / 0, 1 open", out)
        self.assertNotIn("Verification", run_summary.render_summary({**d, "verification": None, "scoreboard": []}))


if __name__ == "__main__":
    unittest.main()
