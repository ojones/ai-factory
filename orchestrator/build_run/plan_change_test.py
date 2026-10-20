import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from planning import file_children as fc  # noqa: E402
from shared import run_stops  # noqa: E402

from build_run import track_progress  # noqa: E402
from build_run.run import BuildRun  # noqa: E402


def _passes(check, doc):
    try:
        check(doc)
        return True
    except ValueError:
        return False


class Planning(unittest.TestCase):
    def make(self, doc, kind="update"):
        run = object.__new__(BuildRun)
        run.work, run.art = Path("/tmp/unused-work"), Path("/tmp/unused-art")
        run.art.mkdir(exist_ok=True)
        run.lim, run.build_kind, run.app, run.issue = {}, kind, "notes", "9"
        run.factory_repo, run.pat = "o/f", "pat"
        run.task = run.spec = "Record sightings and filter them"
        run.cap_override = "1.00"
        run.state = track_progress.State("/tmp/unused-state.json", "notes", "9", "u")
        run.state.save = lambda: None
        run.agent_json = mock.Mock(side_effect=lambda role, label, values, path, check=None, **kw: (check(doc) if check else None, doc, 0.1, None)[1:])
        return run

    def plan(self, n=1, questions=()):
        sets = [{"id": f"CS-{i}", "title": f"Part {i}", "requirements": ["REQ-1"], "depends_on": [f"CS-{i - 1}"] if i > 1 else [],
                 "criteria": [f"AC-1: part {i} works"], "verification": ["curl it"], "flag": f"part-{i}", "size": "S", "internal_only": False, "out_of_scope": []}
                for i in range(1, n + 1)]
        return {"requirements": [{"id": "REQ-1", "text": "do it"}], "assumptions": ["a"], "change_sets": sets,
                "open_questions": [{"id": "Q-1", "text": q, "blocking": True} for q in questions]}

    def test_the_plan_is_posted_on_the_intake_issue(self):
        run = self.make(self.plan(1))
        run.factory_token = "t"
        run.gh = mock.Mock()
        run.plan_change()
        args = run.gh.call_args[0][0]
        self.assertEqual(args[:3], ["issue", "comment", "9"])
        self.assertIn("Assumptions I made for you", args[args.index("--body") + 1])

    def test_one_change_set_becomes_this_runs_task_and_spec(self):
        run = self.make(self.plan(1))
        self.assertFalse(run.plan_change())
        self.assertIn("Change set CS-1: Part 1", run.task)
        self.assertIn("Record sightings and filter them", run.task)
        self.assertIn("slug `part-1`", run.task)
        self.assertEqual(run.spec, run.task)
        self.assertEqual(run.state.d["stages"][0]["stage"], "Plan")

    def test_several_change_sets_are_filed_as_children_and_the_run_ends_planned(self):
        run = self.make(self.plan(3))
        with mock.patch.object(fc, "file_children", return_value=[("CS-1", 11), ("CS-2", 12), ("CS-3", 13)]) as filed:
            self.assertTrue(run.plan_change())
        args = filed.call_args[0]
        self.assertEqual((args[0], args[2], args[3], args[5]), ("o/f", "notes", 9, ["CS-1", "CS-2", "CS-3"]))
        self.assertEqual(filed.call_args[1]["cap"], "1.00")
        self.assertEqual(run.state.d["outcome"], "planned")
        self.assertIn("CS-2 (#12)", run.state.d["message"])
        self.assertEqual(len(run.state.d["plan"]["change_sets"]), 3)

    def test_a_blocking_question_stops_the_run_for_a_person(self):
        run = self.make(self.plan(1, questions=["Should photos be public?"]))
        with self.assertRaises(run_stops.NeedsHuman) as cm:
            run.plan_change()
        self.assertIn("Should photos be public?", str(cm.exception))
        self.assertIn("proceed-with-change", str(cm.exception))

    def test_an_automatic_retry_does_not_stop_to_ask_it_takes_the_conservative_reading(self):
        run = self.make(self.plan(1, questions=["Should photos be public?"]))
        run.fix_meta = {"origin": 66, "attempt": 1}
        run.factory_token = "t"
        run.gh = mock.Mock()
        self.assertFalse(run.plan_change())  # no NeedsHuman
        self.assertIn("Decided without asking", run.state.d["plan"]["assumptions"][-1])
        self.assertIn("Should photos be public?", run.state.d["plan"]["assumptions"][-1])
        self.assertIn("most conservative reading", run.state.d["plan"]["assumptions"][-1])
        posted = run.gh.call_args[0][0]
        self.assertIn("Decided without asking", posted[posted.index("--body") + 1])  # visible on the issue

    def test_a_person_filed_request_still_stops_for_a_blocking_question(self):
        run = self.make(self.plan(1, questions=["Should photos be public?"]))
        run.fix_meta = {}
        with self.assertRaises(run_stops.NeedsHuman):
            run.plan_change()

    def test_a_plan_that_fails_the_check_is_rejected_with_the_reasons(self):
        bad = self.plan(2)
        bad["change_sets"][1]["depends_on"] = ["CS-9"]
        run = self.make(bad)
        run.agent_json = mock.Mock(side_effect=lambda role, label, values, path, check=None, **kw: (_ for _ in ()).throw(
            run_stops.NeedsHuman("other", "no valid output twice")) if check and not _passes(check, bad) else (bad, 0.1, None))
        with self.assertRaises(run_stops.NeedsHuman) as cm:
            run.plan_change()
        self.assertIn("rejected", str(cm.exception))
        self.assertIn("CS-9", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
