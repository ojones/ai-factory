import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import planner as p  # noqa: E402


def good():
    return {"requirements": [{"id": "REQ-1", "text": "record sightings"}, {"id": "REQ-2", "text": "filter by species"}],
            "assumptions": ["in-memory storage is fine"], "open_questions": [],
            "change_sets": [
                {"id": "CS-1", "title": "Save a sighting", "requirements": ["REQ-1"], "depends_on": [], "criteria": ["AC-1: POST saves it"],
                 "verification": ["curl POST then GET"], "flag": "sightings", "internal_only": False, "out_of_scope": []},
                {"id": "CS-2", "title": "Filter by species", "requirements": ["REQ-2"], "depends_on": ["CS-1"], "criteria": ["AC-1: ?species= filters"],
                 "verification": ["curl with and without the filter"], "flag": "species-filter", "internal_only": False, "out_of_scope": []}]}


def check(plan, kind="update"):
    return p.validate_plan(plan, kind)


class Plan(unittest.TestCase):
    def test_a_good_plan_is_ready_and_ordered_by_dependency(self):
        self.assertEqual(check(good()), ([], []))
        reordered = good()
        reordered["change_sets"].reverse()
        self.assertEqual(p.topological_order(reordered["change_sets"]), ["CS-1", "CS-2"])

    def test_an_uncovered_requirement_is_a_problem(self):
        plan = good()
        plan["requirements"].append({"id": "REQ-3", "text": "export"})
        self.assertTrue(any("REQ-3 is not covered" in x for x in check(plan)[0]))

    def test_unknown_references_and_cycles_are_problems(self):
        plan = good()
        plan["change_sets"][0]["requirements"] = ["REQ-9"]
        plan["change_sets"][1]["depends_on"] = ["CS-7"]
        problems = check(plan)[0]
        self.assertTrue(any("unknown requirement REQ-9" in x for x in problems))
        self.assertTrue(any("unknown change set CS-7" in x for x in problems))
        cyc = good()
        cyc["change_sets"][0]["depends_on"] = ["CS-2"]
        self.assertTrue(any("cycle" in x for x in check(cyc)[0]))
        self.assertIsNone(p.topological_order(cyc["change_sets"]))
        selfdep = good()
        selfdep["change_sets"][0]["depends_on"] = ["CS-1"]
        self.assertTrue(any("depends on itself" in x for x in check(selfdep)[0]))

    def test_every_change_set_needs_criteria_verification_a_title_and_a_requirement(self):
        for key, needle in (("criteria", "acceptance criteria"), ("verification", "verified"), ("title", "no title"), ("requirements", "not linked")):
            plan = good()
            plan["change_sets"][0][key] = [] if key != "title" else " "
            self.assertTrue(any(needle in x for x in check(plan)[0]), key)
        plan = good()
        plan["change_sets"][0]["criteria"] = ["  "]
        self.assertTrue(any("acceptance criteria" in x for x in check(plan)[0]))

    def test_an_update_change_set_needs_its_own_flag_unless_users_cannot_see_it(self):
        plan = good()
        plan["change_sets"][0]["flag"] = None
        self.assertTrue(any("no flag" in x for x in check(plan)[0]))
        plan["change_sets"][0]["internal_only"] = True
        self.assertEqual(check(plan)[0], [])
        first = good()
        first["change_sets"][0]["flag"] = None
        self.assertEqual(check(first, "first build")[0], [])

    def test_flags_must_be_valid_slugs_and_not_shared(self):
        plan = good()
        plan["change_sets"][1]["flag"] = "sightings"
        self.assertTrue(any("share a flag" in x for x in check(plan)[0]))
        plan["change_sets"][1]["flag"] = "Bad Slug!"
        self.assertTrue(any("invalid flag slug" in x for x in check(plan)[0]))

    def test_too_many_change_sets_is_a_problem(self):
        plan = good()
        base = plan["change_sets"][0]
        plan["change_sets"] = [dict(copy.deepcopy(base), id=f"CS-{i}", flag=f"f{i}", depends_on=[]) for i in range(p.MAX_CHANGE_SETS + 1)]
        self.assertTrue(any("more than the limit" in x for x in check(plan)[0]))

    def test_blocking_questions_are_for_a_person_and_do_not_make_the_plan_invalid(self):
        plan = good()
        plan["open_questions"] = [{"id": "Q-1", "text": "Should photos be public?", "blocking": True},
                                  {"id": "Q-2", "text": "colour?", "blocking": False}]
        problems, questions = check(plan)
        self.assertEqual(problems, [])
        self.assertEqual(questions, ["Q-1: Should photos be public?"])

    def test_garbage_is_reported_not_raised(self):
        self.assertEqual(check([])[0], ["the plan is not a JSON object"])
        problems = check({})[0]
        self.assertIn("no requirements listed", problems)
        self.assertIn("no change sets listed", problems)
        self.assertTrue(check({"requirements": [{"id": "R"}], "change_sets": ["x", {"id": 3}]})[0])

    def test_the_command_line_exit_codes(self):
        def run(plan, *extra):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "plan.json"
                path.write_text(json.dumps(plan))
                return subprocess.run([sys.executable, str(Path(p.__file__)), "validate", str(path), *extra], capture_output=True, text=True)
        ok = run(good())
        self.assertEqual(ok.returncode, 0)
        self.assertIn("CS-1 -> CS-2", ok.stdout)
        asking = good()
        asking["open_questions"] = [{"id": "Q-1", "text": "?", "blocking": True}]
        self.assertEqual(run(asking).returncode, 2)
        bad = good()
        bad["change_sets"] = []
        self.assertEqual(run(bad).returncode, 1)


if __name__ == "__main__":
    unittest.main()
