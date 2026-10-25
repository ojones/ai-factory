import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_run import track_progress  # noqa: E402


def finding(**over):
    return {"severity": "blocking", "category": "correctness", "evidence_kind": "cited", "summary": "x", "evidence": "e",
            "file": "backend/src/a.ts", "line": "3", "requirement": "", "suggested_fix": "", "repro": "", **over}


class PreviousReport(unittest.TestCase):
    def test_round_one_has_none_and_later_rounds_point_at_the_last_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("none", str(track_progress.previous_report(tmp, 1)))
            self.assertIn("none", str(track_progress.previous_report(tmp, 2)), msg="no file yet")
            (Path(tmp) / "test-report-1.json").write_text("{}")
            self.assertEqual(track_progress.previous_report(tmp, 2), Path(tmp) / "test-report-1.json")


class Scoreboard(unittest.TestCase):
    def entry(self, rnd, checks, blocking=()):
        record = {"counts": {s: 0 for s in track_progress.CHECK_STATES},
                  "checks": [{"flag": "a", "check": c, "status": st} for c, st in checks.items()]}
        return track_progress.scoreboard_entry(rnd, "sha", record, [{"summary": x} for x in blocking])

    def test_entry_keys_checks_by_flag_and_normalises_findings(self):
        e = self.entry(1, {"x": "failed"}, ["  Missing   Flag "])
        self.assertEqual(e["checks"], {"a: x": "failed"})
        self.assertEqual(e["blocking"], ["missing flag"])

    def test_the_scoreboard_counts_blocking_findings_by_category_and_tester_checks_apart(self):
        record = {"counts": {}, "checks": []}
        blocking = [{"source": "reviewer", "summary": "a", "category": "test_quality"}, {"source": "reviewer", "summary": "b", "category": "test_quality"},
                    {"source": "tester", "summary": "c"}]
        self.assertEqual(track_progress.scoreboard_entry(1, "sha", record, blocking)["categories"], {"test_quality": 2, "tester_check": 1})


if __name__ == "__main__":
    unittest.main()
