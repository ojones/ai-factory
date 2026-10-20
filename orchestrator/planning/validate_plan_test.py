import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from planning import validate_plan as p  # noqa: E402


def good():
    return {"requirements": [{"id": "REQ-1", "text": "record sightings"}, {"id": "REQ-2", "text": "filter by species"}],
            "assumptions": ["in-memory storage is fine"], "open_questions": [],
            "change_sets": [
                {"id": "CS-1", "title": "Save a sighting", "requirements": ["REQ-1"], "depends_on": [], "criteria": ["AC-1: POST saves it"],
                 "verification": ["curl POST then GET"], "flag": "sightings", "size": "S", "internal_only": False, "out_of_scope": []},
                {"id": "CS-2", "title": "Filter by species", "requirements": ["REQ-2"], "depends_on": ["CS-1"], "criteria": ["AC-1: ?species= filters"],
                 "verification": ["curl with and without the filter"], "flag": "species-filter", "size": "S", "internal_only": False, "out_of_scope": []}]}


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
        first["change_sets"][0]["kind"] = "staging"
        first["change_sets"][0]["internal_only"] = True
        self.assertEqual(check(first, "first build")[0], [])

    def test_flags_must_be_valid_slugs_and_not_shared(self):
        plan = good()
        plan["change_sets"][1]["flag"] = "sightings"
        self.assertTrue(any("share a flag" in x for x in check(plan)[0]))
        plan["change_sets"][1]["flag"] = "Bad Slug!"
        self.assertTrue(any("invalid flag slug" in x for x in check(plan)[0]))

    def test_a_flagged_change_set_may_just_say_true_and_the_orchestrator_names_the_flag(self):
        plan = good()
        for cs in plan["change_sets"]:
            cs["flag"] = True  # two flagged sets do not "share" a flag: each is named after its own issue
        self.assertEqual(check(plan), ([], []))
        plan["change_sets"][1]["flag"] = None  # no flag and not internal is still a problem
        self.assertTrue(any("no flag" in x for x in check(plan)[0]))
        plan["change_sets"][1]["flag"] = True

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

    def test_a_change_set_that_is_only_tests_is_a_problem(self):
        for title in ("Add comprehensive tests for PATCH endpoint", "Write unit tests for the store", "Add test coverage", "Create integration tests"):
            plan = good()
            plan["change_sets"][1]["title"] = title
            self.assertTrue(any("only tests" in x for x in check(plan)[0]), title)
        for title in ("Add a test-mode banner", "Filter sightings by species", "Show test results on the dashboard", "Save a sighting and validate it"):
            plan = good()
            plan["change_sets"][1]["title"] = title
            self.assertFalse(any("only tests" in x for x in check(plan)[0]), title)

    def test_retiring_a_flag_is_internal_and_must_not_be_given_a_new_flag(self):
        # From the first real retirement runs: the planner invented a flag to retire a flag.
        for title in ("Remove update-todo-store feature flag and make PUT endpoint always available",
                      "Retire the delete-todo-endpoint flag", "Remove filter-todos-by-done flag", "Clean up the old search flag"):
            plan = good()
            plan["change_sets"][1]["title"] = title
            plan["change_sets"][1]["flag"] = "retire-it"
            self.assertTrue(any("retires or removes a flag" in x for x in check(plan)[0]), title)
            plan["change_sets"][1]["flag"] = None
            plan["change_sets"][1]["internal_only"] = True
            self.assertEqual(check(plan)[0], [], title)
        for title in ("Add a flag-style toggle to the settings page", "Filter sightings by species", "Remove the old species column"):
            plan = good()
            plan["change_sets"][1]["title"] = title
            self.assertFalse(any("retires or removes a flag" in x for x in check(plan)[0]), title)

    def test_the_recorded_planner_mistakes_are_caught_and_their_good_versions_pass(self):
        # agents/planner-fixtures/cases.json: plans shaped like the real mistakes in the factory-learning issues.
        cases = json.loads((Path(__file__).resolve().parent.parent.parent / "agents" / "planner-fixtures" / "cases.json").read_text())
        for case in cases:
            plan = good()
            plan["change_sets"] = [{**plan["change_sets"][0], **case["change_set"], "id": "CS-1", "requirements": ["REQ-1"], "depends_on": []}]
            plan["requirements"] = plan["requirements"][:1]
            problems = check(plan, case.get("build_kind", "update"))[0]
            if case["expect"] == "ok":
                self.assertEqual(problems, [], case["name"])
            else:
                self.assertTrue(any(case["expect"] in x for x in problems), (case["name"], problems))

    def test_declared_secrets_are_checked_for_name_purpose_and_uniqueness(self):
        plan = good()
        plan["secrets"] = [{"name": "WEATHER_API_KEY", "purpose": "forecast lookups", "read_by": "backend"}]
        self.assertEqual(check(plan)[0], [])
        for bad, fragment in (([{"name": "weather key", "purpose": "x"}], "not a valid secret name"),
                              ([{"name": "FLY_API_TOKEN", "purpose": "x"}], "Factory's own"),
                              ([{"name": "WEATHER_API_KEY", "purpose": ""}], "no purpose"),
                              ([{"name": "A_KEY", "purpose": "x"}, {"name": "A_KEY", "purpose": "y"}], "not unique"),
                              ("WEATHER_API_KEY", "must be a list")):
            plan["secrets"] = bad
            self.assertTrue(any(fragment in x for x in check(plan)[0]), (bad, check(plan)[0]))

    def test_garbage_is_reported_not_raised(self):
        self.assertEqual(check([])[0], ["the plan is not a JSON object"])
        problems = check({})[0]
        self.assertIn("no requirements listed", problems)
        self.assertIn("no change sets listed", problems)
        self.assertTrue(check({"requirements": [{"id": "R"}], "change_sets": ["x", {"id": 3}]})[0])


class RollbackSized(unittest.TestCase):
    def test_a_change_set_is_size_s_or_m_and_l_or_none_is_rejected(self):
        for size, fragment in (("L", "size L"), (None, "no size"), ("XL", "no size")):
            plan = good()
            plan["change_sets"][0]["size"] = size
            self.assertTrue(any(fragment in x for x in check(plan)[0]), size)
        plan = good()
        plan["change_sets"][0]["size"] = "M"
        self.assertEqual(check(plan), ([], []))

    def test_more_criteria_than_the_limit_means_it_is_not_one_slice(self):
        plan = good()
        plan["change_sets"][0]["criteria"] = [f"AC-{i}: x" for i in range(1, 8)]
        self.assertTrue(any("7 acceptance criteria, more than 6" in x for x in check(plan)[0]))
        plan["change_sets"][0]["criteria"] = plan["change_sets"][0]["criteria"][:6]
        self.assertEqual(check(plan)[0], [])
        self.assertEqual(len(p.validate_plan(plan, "update", 8, 5)[0]), 1)  # the limit is configurable (planner_max_criteria)

    def test_a_change_set_that_names_another_must_depend_on_it(self):
        plan = good()
        plan["change_sets"][1]["depends_on"] = []
        plan["change_sets"][1]["criteria"] = ["AC-1: the filter shows only when CS-1's flag is on"]
        self.assertTrue(any("mentions CS-1 but does not depend on it" in x for x in check(plan)[0]))
        plan["change_sets"][1]["depends_on"] = ["CS-1"]
        self.assertEqual(check(plan)[0], [])

    def new_app(self):
        plan = good()
        stage = {"id": "CS-0", "title": "Stage the app", "requirements": ["REQ-1"], "depends_on": [], "criteria": ["AC-1: deploy is healthy"],
                 "verification": ["curl /health"], "flag": None, "internal_only": True, "size": "S", "kind": "staging", "out_of_scope": []}
        for cs in plan["change_sets"]:
            cs["flag"] = None
            cs["depends_on"] = ["CS-0"] if cs["id"] == "CS-1" else ["CS-1"]
        plan["change_sets"].insert(0, stage)
        return plan

    def test_the_first_change_set_of_a_new_app_is_the_staging_one_and_everything_depends_on_it(self):
        self.assertEqual(check(self.new_app(), "first build"), ([], []))
        plan = self.new_app()
        plan["change_sets"][0]["kind"] = "update"
        self.assertTrue(any("must be the only one of kind `staging`" in x for x in check(plan, "first build")[0]))
        plan = self.new_app()
        plan["change_sets"][1]["depends_on"] = []
        self.assertTrue(any("must depend on it" in x for x in check(plan, "first build")[0]))
        plan = self.new_app()
        plan["change_sets"][2]["kind"] = "staging"
        self.assertTrue(any("only one of kind `staging`" in x for x in check(plan, "first build")[0]))

    def test_staging_has_no_flag_and_exists_only_for_a_new_app(self):
        plan = self.new_app()
        plan["change_sets"][0]["flag"] = True
        self.assertTrue(any("flag must be null" in x for x in check(plan, "first build")[0]))
        self.assertTrue(any("only for the first change set of a new app" in x for x in check(self.new_app(), "update")[0]))
        plan = self.new_app()
        plan["change_sets"][1]["kind"] = "odd"
        self.assertTrue(any("unknown kind" in x for x in check(plan, "first build")[0]))


if __name__ == "__main__":
    unittest.main()
