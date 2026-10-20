import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_run import track_progress  # noqa: E402


def finding(**over):
    # A reviewer finding as the schema requires it: blocking, backed by a cited file and line.
    return {"severity": "blocking", "category": "correctness", "evidence_kind": "cited", "summary": "x", "evidence": "e",
            "file": "backend/src/a.ts", "line": "3", "requirement": "", "suggested_fix": "", "repro": "", **over}


class PreviousReport(unittest.TestCase):
    def test_round_one_has_none_and_later_rounds_point_at_the_last_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("none", str(track_progress.previous_report(tmp, 1)))
            self.assertIn("none", str(track_progress.previous_report(tmp, 2)))  # no file yet
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

    def test_identical_open_items_for_n_rounds_is_stalled(self):
        same = [self.entry(i, {"x": "failed", "y": "passed"}, ["no health route"]) for i in (1, 2, 3)]
        self.assertTrue(track_progress.stalled(same, 3))
        self.assertFalse(track_progress.stalled(same[:2], 3))

    def test_any_change_between_rounds_is_progress(self):
        a, c = self.entry(1, {"x": "failed"}), self.entry(2, {"x": "passed"}, ["new finding"])
        self.assertFalse(track_progress.stalled([a, a, c], 3))
        self.assertFalse(track_progress.stalled([a, c, c], 3))

    def test_nothing_open_is_never_stalled_and_small_n_disables_it(self):
        clean = [self.entry(i, {"x": "passed"}) for i in (1, 2, 3)]
        self.assertFalse(track_progress.stalled(clean, 3))
        failing = [self.entry(i, {"x": "failed"}) for i in (1, 2, 3)]
        self.assertFalse(track_progress.stalled(failing, 0))
        self.assertFalse(track_progress.stalled(failing, 1))


class ScoreboardCategories(unittest.TestCase):
    def test_the_scoreboard_counts_blocking_findings_by_category_and_tester_checks_apart(self):
        record = {"counts": {}, "checks": []}
        blocking = [{"source": "reviewer", "summary": "a", "category": "test_quality"}, {"source": "reviewer", "summary": "b", "category": "test_quality"},
                    {"source": "tester", "summary": "c"}]
        self.assertEqual(track_progress.scoreboard_entry(1, "sha", record, blocking)["categories"], {"test_quality": 2, "tester_check": 1})


if __name__ == "__main__":
    unittest.main()
