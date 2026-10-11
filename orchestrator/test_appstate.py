import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import appstate as a  # noqa: E402


def report(app="notes", outcome="released", day="2026-10-10", released=("notes.feature.search",), url="https://github.com/o/f/actions/runs/1", **kw):
    d = {"app": app, "outcome": outcome, "finished_at": f"{day}T05:00:00Z", "run_url": url, "build_kind": "update", "spent_usd": 0.456,
         "review_passes": 2, "release": {"released": list(released), "kept": []}}
    d.update(kw)
    return d


class AppState(unittest.TestCase):
    def test_a_run_and_its_flags_are_recorded_and_survive_a_rewrite(self):
        body = a.render_state("", report())
        self.assertIn("# notes: Factory state", body)
        self.assertIn("| 2026-10-10 | released | update | 2 | $0.46 | search |", body)
        self.assertIn("| `notes.feature.search` | 2026-10-10 | released |", body)
        again = a.render_state(body, report(day="2026-10-11", released=("notes.feature.tags",), url="https://x/2"))
        data = a.load(again)
        self.assertEqual(len(data["runs"]), 2)
        self.assertEqual([f["key"] for f in data["flags"]], ["notes.feature.search", "notes.feature.tags"])

    def test_only_the_most_recent_runs_are_kept_but_all_flags_are(self):
        body = ""
        for i in range(a.MAX_RUNS + 3):
            body = a.render_state(body, report(day=f"2026-09-{i + 1:02d}", released=(f"notes.feature.f{i}",), url=f"https://x/{i}"))
        data = a.load(body)
        self.assertEqual(len(data["runs"]), a.MAX_RUNS)
        self.assertEqual(len(data["flags"]), a.MAX_RUNS + 3)

    def test_a_watchdog_disable_marks_the_flag(self):
        body = a.render_state("", report(outcome="watchdog_disabled"))
        self.assertIn("switched off by the watchdog", body)
        self.assertEqual(a.load(body)["flags"][0]["state"], "switched off by the watchdog")

    def test_a_run_with_no_release_still_shows_and_a_second_release_of_a_flag_updates_it(self):
        body = a.render_state("", report(outcome="round_limit", released=(), release=None))
        self.assertIn("None yet.", body)
        self.assertIn("| round_limit |", body)
        body = a.render_state(a.render_state("", report(outcome="watchdog_disabled")), report(day="2026-10-12", url="https://x/3"))
        self.assertEqual([(f["date"], f["state"]) for f in a.load(body)["flags"]], [("2026-10-12", "released")])

    def test_data_with_double_dashes_and_pipes_survives(self):
        url = "https://github.com/o/my--app/actions/runs/1"
        body = a.render_state("", report(app="my--app", url=url, outcome="a|b"))
        self.assertEqual(a.load(body)["runs"][0]["run_url"], url)
        self.assertIn("a\\|b", body)
        self.assertEqual(body.count("<!--"), 1)
        self.assertEqual(a.load("not a state issue"), {})
        self.assertEqual(a.load("<!-- factory-data:{broken -->"), {})

    def test_the_registry_has_one_row_per_app_with_a_running_count(self):
        body = a.render_registry("", report(app="notes"), "https://github.com/o/notes/issues/3")
        body = a.render_registry(body, report(app="todo", outcome="stuck", url="https://x/9"), "https://github.com/o/todo/issues/1")
        body = a.render_registry(body, report(app="notes", day="2026-10-12", url="https://x/10"), "")
        rows = [l for l in body.splitlines() if l.startswith("| ") and "App" not in l and "---" not in l]
        self.assertEqual(len(rows), 2)
        notes = next(r for r in rows if r.startswith("| notes"))
        self.assertIn("2 (2)", notes)
        self.assertIn("[state](https://github.com/o/notes/issues/3)", notes)
        self.assertIn("1 (0)", next(r for r in rows if r.startswith("| todo")))

    def test_a_non_https_state_url_is_not_linked(self):
        body = a.render_registry("", report(), "javascript:alert(1)")
        self.assertNotIn("javascript:", body.split("<!--")[0])


if __name__ == "__main__":
    unittest.main()
