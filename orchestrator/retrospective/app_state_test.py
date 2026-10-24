import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import app_state_record, shell  # noqa: E402

from retrospective import app_state as a  # noqa: E402


def report(app="notes", outcome="released", day="2026-10-10", released=("notes.feature.search",), url="https://github.com/o/f/actions/runs/1", **kw):
    d = {"app": app, "outcome": outcome, "finished_at": f"{day}T05:00:00Z", "run_url": url, "build_kind": "update", "spent_usd": 0.456,
         "review_passes": 2, "release": {"released": list(released), "kept": []}}
    d.update(kw)
    return d


class StateIssueRead(unittest.TestCase):
    def test_an_unreadable_issue_list_raises_instead_of_creating_a_duplicate_state_issue(self):
        down = mock.Mock(returncode=1, stdout="", stderr="down")
        with mock.patch.object(shell, "run_bounded", return_value=down), \
                mock.patch.object(a, "create_state_issue") as create, self.assertRaises(RuntimeError):
            a.upsert_state_issue("o/app", "t", "state", "title", "ffffff", lambda prev: prev)
        create.assert_not_called()


class AppState(unittest.TestCase):
    def test_a_run_and_its_flags_are_recorded_and_survive_a_rewrite(self):
        body = a.render_state("", report())
        self.assertIn("# notes: Factory state", body)
        self.assertIn("| 2026-10-10 | released | update | 2 | $0.46 | search |", body)
        self.assertIn("| `notes.feature.search` | 2026-10-10 | released |", body)
        again = a.render_state(body, report(day="2026-10-11", released=("notes.feature.tags",), url="https://x/2"))
        data = app_state_record.load(again)
        self.assertEqual(len(data["runs"]), 2)
        self.assertEqual([f["key"] for f in data["flags"]], ["notes.feature.search", "notes.feature.tags"])

    def test_only_the_most_recent_runs_are_kept_but_all_flags_are(self):
        body = ""
        for i in range(a.MAX_RUNS + 3):
            body = a.render_state(body, report(day=f"2026-09-{i + 1:02d}", released=(f"notes.feature.f{i}",), url=f"https://x/{i}"))
        data = app_state_record.load(body)
        self.assertEqual(len(data["runs"]), a.MAX_RUNS)
        self.assertEqual(len(data["flags"]), a.MAX_RUNS + 3)

    def test_a_watchdog_disable_marks_the_flag(self):
        body = a.render_state("", report(outcome="watchdog_disabled"))
        self.assertIn("switched off by the watchdog", body)
        self.assertEqual(app_state_record.load(body)["flags"][0]["state"], "switched off by the watchdog")

    def test_a_run_with_no_release_still_shows_and_a_second_release_of_a_flag_updates_it(self):
        body = a.render_state("", report(outcome="round_limit", released=(), release=None))
        self.assertIn("None yet.", body)
        self.assertIn("| round_limit |", body)
        body = a.render_state(a.render_state("", report(outcome="watchdog_disabled")), report(day="2026-10-12", url="https://x/3"))
        self.assertEqual([(f["date"], f["state"]) for f in app_state_record.load(body)["flags"]], [("2026-10-12", "released")])

    def test_a_dark_feature_is_listed_but_is_never_taken_for_a_released_flag_and_a_later_release_replaces_it(self):
        dark = report(outcome="round_limit", released=(), flags=["pin"], commits=["h"], issue_number="12")
        body = a.render_state("", dark)
        self.assertIn("| `notes.feature.pin` | 2026-10-10 | dark (failed its checks", body)
        self.assertEqual([f["state"].split(" ")[0] for f in app_state_record.load(body)["flags"]], ["dark"])
        released = a.render_state(body, report(day="2026-10-11", released=("notes.feature.pin",), flags=["pin"], commits=["h2"], issue_number="12"))
        self.assertEqual([(f["key"], f["state"]) for f in app_state_record.load(released)["flags"]], [("notes.feature.pin", "released")])
        for outcome in ("refused", "provider_blocked"):
            self.assertEqual(app_state_record.load(a.render_state("", dict(dark, outcome=outcome)))["flags"], [], outcome)
        regressed = app_state_record.load(a.render_state("", dict(dark, outcome="regression")))["flags"]
        self.assertEqual([f["state"].split(" ")[0] for f in regressed], ["dark"], msg="rolled back, but its code stays in main")

    def test_data_with_double_dashes_and_pipes_survives(self):
        url = "https://github.com/o/my--app/actions/runs/1"
        body = a.render_state("", report(app="my--app", url=url, outcome="a|b"))
        self.assertEqual(app_state_record.load(body)["runs"][0]["run_url"], url)
        self.assertIn("a\\|b", body)
        self.assertEqual(body.count("<!--"), 1)
        self.assertEqual(app_state_record.load("not a state issue"), {})
        self.assertEqual(app_state_record.load("<!-- factory-data:{broken -->"), {})

    def test_the_registry_has_one_row_per_app_with_a_running_count(self):
        body = a.render_registry("", report(app="notes"), "https://github.com/o/notes/issues/3")
        body = a.render_registry(body, report(app="todo", outcome="round_limit", url="https://x/9"), "https://github.com/o/todo/issues/1")
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


class Stories(unittest.TestCase):
    def test_a_flag_links_to_the_story_it_came_from(self):
        self.assertEqual(a.story_link({"issue": 94, "run_url": "https://github.com/o/ai-factory/actions/runs/5"}), "[#94](https://github.com/o/ai-factory/issues/94)")
        self.assertEqual(a.story_link({"run_url": "https://github.com/o/ai-factory/actions/runs/5"}), "-")
        self.assertEqual(a.story_link({"issue": 94, "run_url": "garbage"}), "-")
        body = a.render_state("", {**report(url="https://github.com/o/ai-factory/actions/runs/9"), "issue_number": 12})
        self.assertIn("| Flag | Date | State | Story |", body)
        self.assertIn("[#12](https://github.com/o/ai-factory/issues/12)", body)


if __name__ == "__main__":
    unittest.main()
