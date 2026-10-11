import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dashboard as db  # noqa: E402


def report(app="notes", outcome="released", rounds=1, cost=0.5, url="https://github.com/o/f/actions/runs/1",
           started="2026-10-10T01:00:00Z", finished="2026-10-10T01:30:00Z", **kw):
    d = {"app": app, "outcome": outcome, "review_passes": rounds, "spent_usd": cost, "cap_usd": 2.0, "run_url": url,
         "started_at": started, "finished_at": finished, "build_kind": "update", "release": {"released": ["x.feature.a"]},
         "verification": {"counts": {"passed": 3, "failed": 0, "blocked": 0, "not_run": 0}}, "audit": []}
    d.update(kw)
    return d


class Dashboard(unittest.TestCase):
    def test_a_report_becomes_a_small_row_with_the_duration(self):
        row = db.summarize_run(report())
        self.assertEqual((row["app"], row["outcome"], row["rounds"], row["minutes"]), ("notes", "released", 1, 30.0))
        self.assertEqual(row["released"], ["x.feature.a"])
        self.assertIsNone(db.summarize_run(report(finished=""))["minutes"])
        self.assertEqual(db.summarize_run({})["app"], "?")

    def test_history_keeps_one_row_per_run_oldest_first(self):
        old = db.summarize_run(report(url="u1", started="2026-10-10T03:00:00Z"))
        first = db.summarize_run(report(url="u2", started="2026-10-10T01:00:00Z"))
        newer_u1 = dict(old, outcome="crash")
        merged = db.merge_history([old], [first, newer_u1])
        self.assertEqual([r["run_url"] for r in merged], ["u2", "u1"])
        self.assertEqual(merged[1]["outcome"], "crash")

    def test_metrics_overall_and_per_app(self):
        rows = [db.summarize_run(report(app="a", url="1", rounds=1, cost=0.4)),
                db.summarize_run(report(app="a", url="2", rounds=3, cost=0.8)),
                db.summarize_run(report(app="b", url="3", outcome="stuck", rounds=3, cost=1.0)),
                db.summarize_run(report(app="b", url="4", outcome="watchdog_disabled", audit=[{"rule": "INV-09"}]))]
        m = db.metrics(rows)
        self.assertEqual((m["all"]["runs"], m["all"]["ok"], m["all"]["first_pass_rate"]), (4, 2, 0.5))
        self.assertEqual((m["all"]["stuck"], m["all"]["watchdog_disabled"], m["all"]["needs_human"], m["all"]["audit_violations"]), (1, 1, 2, 1))
        self.assertEqual(m["apps"]["a"]["avg_rounds"], 2.0)
        self.assertEqual(m["apps"]["a"]["total_cost_usd"], 1.2)
        self.assertEqual(list(m["apps"]), ["a", "b"])

    def test_no_runs_is_not_a_crash(self):
        m = db.metrics([])
        self.assertIsNone(m["all"]["ok_rate"])
        self.assertIn("0 Build Run(s)", db.render_digest([], m, "2026-10-09T00:00:00Z"))
        self.assertIn("Factory dashboard", db.render_html([], m, "now"))

    def test_digest_lists_only_recent_problems_and_broken_invariants(self):
        rows = [db.summarize_run(report(url="old", outcome="crash", started="2026-10-01T00:00:00Z")),
                db.summarize_run(report(url="https://x/r2", app="b", outcome="stuck", started="2026-10-10T02:00:00Z")),
                db.summarize_run(report(url="https://x/r3", app="c", started="2026-10-10T03:00:00Z", audit=[{"rule": "INV-03 x"}]))]
        digest = db.render_digest(rows, db.metrics(rows, {"open": 2, "fix_ineffective": 1}), "2026-10-09T00:00:00Z")
        self.assertIn("2 Build Run(s), 1 ended OK", digest)
        self.assertIn("`b`: stuck", digest)
        self.assertNotIn("`b`: crash", digest)
        self.assertIn("INV-03 x", digest)
        self.assertIn("2 open, 1 marked fix-ineffective", digest)
        quiet = db.render_digest(rows[:1], db.metrics(rows[:1]), "2026-10-09T00:00:00Z")
        self.assertIn("Nothing needs a person", quiet)

    def test_html_escapes_what_it_shows_and_only_links_https(self):
        rows = [db.summarize_run(report(app="<script>x</script>", url="javascript:alert(1)")),
                db.summarize_run(report(app="ok", url="https://github.com/o/f/actions/runs/9", started="2026-10-11T00:00:00Z"))]
        page = db.render_html(rows, db.metrics(rows), "now")
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("javascript:", page)
        self.assertIn("href='https://github.com/o/f/actions/runs/9'", page)


if __name__ == "__main__":
    unittest.main()
