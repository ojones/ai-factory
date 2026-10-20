import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import child_tickets, run_stops  # noqa: E402
from shared.fake_issues import FakeIssues  # noqa: E402

from planning import plan_run, secrets_check  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
FORM = "### App name\n\nnotes\n\n### What should change?\n\nAdd tags\n\n### Cost cap override (USD)\n\n{cap}\n"
LIMITS = {"cost_cap_usd_default": 2.0, "cost_cap_usd_ceiling": 10.0}


def issue(labels=("update-app-intake",), body=None, title="notes: add tags"):
    return {"title": title, "body": body if body is not None else FORM.format(cap="_No response_"), "labels": [{"name": n} for n in labels], "comments": []}


def info(description="Intake: o/f#3", rc=0):
    return lambda app: mock.Mock(returncode=rc, stdout=json.dumps({"description": description}))


def cs(i, deps=(), **kw):
    return {"id": f"CS-{i}", "title": f"Part {i}", "requirements": ["REQ-1"], "depends_on": list(deps), "criteria": ["AC-1: it works"], "verification": ["curl it"],
            "size": "S", "flag": True, "internal_only": False, "out_of_scope": [], **kw}


def plan(n=1, **over):
    return {"feasibility": {"status": "ok"}, "requirements": [{"id": "REQ-1", "text": "tags"}], "assumptions": ["a"], "open_questions": [],
            "secrets": [], "change_sets": [cs(i, [f"CS-{i - 1}"] if i > 1 else []) for i in range(1, n + 1)], **over}


class ReadingTheIntake(unittest.TestCase):
    def test_an_update_intake_names_its_app_task_and_cap(self):
        got = plan_run.read_intake(issue(body=FORM.format(cap="$3")), "o/f", info(), LIMITS)
        self.assertEqual((got["kind"], got["app"], got["task"], got["cap"], got["cap_override"]), ("update", "notes", "Add tags", 3.0, "3"))

    def test_a_new_app_intake_is_titled_with_its_app(self):
        body = "### What should be built?\n\nA notes app\n"
        got = plan_run.read_intake(issue(("new-app-intake",), body, "notes"), "o/f", info(), LIMITS)
        self.assertEqual((got["kind"], got["app"]), ("new", "notes"))

    def test_a_bug_intake_carries_its_fix_for_marker_and_an_ordinary_one_does_not(self):
        marker = child_tickets.render_fix_for(12, 12, 5, True, 1)
        got = plan_run.read_intake(issue(("update-app-intake", "bug"), marker + "\n\n" + FORM.format(cap="_No response_")), "o/f", info(), LIMITS)
        self.assertEqual(got["fix_for"], {"fix_for": 12, "flag_story": 12, "origin_parent": 5, "flag": True, "attempt": 1})
        self.assertIsNone(plan_run.read_intake(issue(), "o/f", info(), LIMITS)["fix_for"])

    def test_a_child_ticket_or_another_issue_is_skipped(self):
        child = child_tickets.render_marker({"parent": 7, "cs": "CS-1"}) + "\n\n" + FORM.format(cap="")
        for bad in (issue(body=child), issue(labels=("bug",))):
            with self.assertRaises(plan_run.Stop) as cm:
                plan_run.read_intake(bad, "o/f", info(), LIMITS)
            self.assertEqual(cm.exception.ending, "skipped")

    def test_a_real_secret_in_the_request_is_refused_without_repeating_it(self):
        body = FORM.format(cap="").replace("Add tags", "use key sk-" + "x1y2z3w4v5u6t7s8r9q0p1o2")
        with self.assertRaises(plan_run.Stop) as cm:
            plan_run.read_intake(issue(body=body), "o/f", info(), LIMITS)
        self.assertEqual(cm.exception.ending, "refused")
        self.assertNotIn("x1y2z3w4", str(cm.exception))

    def test_a_missing_foreign_or_unreadable_target_needs_a_person(self):
        for reader, issue_body in ((info(rc=1), None), (info("someone else's"), None), (info(), FORM.format(cap="$99")), (info(), "### App name\n\nBad Name\n")):
            with self.assertRaises(plan_run.Stop) as cm:
                plan_run.read_intake(issue(body=issue_body), "o/f", reader, LIMITS)
            self.assertEqual(cm.exception.ending, "needs_human")


class Run(unittest.TestCase):
    def setUp(self):
        self.gh = FakeIssues()
        self.gh.add(7)
        self.tickets = child_tickets.ChildTickets("o/f", 7, "pat", self.gh)
        self.comments, self.asked, self.filed = [], [], []

    def go(self, doc=None, ask_error=None, have=(), declared=(), limits=None, kind="update", fix=None):
        def ask(task):
            self.asked.append(task)
            if ask_error:
                raise ask_error
            return doc, 0.07, None

        def file(parent, sets, order, secrets, fix=None):
            self.filed.append((parent, order, secrets, fix))
            return [(c["id"], 100 + i) for i, c in enumerate(sets)]

        intake = {"kind": kind, "app": "notes", "task": "Add tags", "cap": 2.0, "cap_override": None, "declared": list(declared), "label": "update-app-intake",
                  "fix_for": fix}
        return plan_run.PlanRun(7, intake, limits or {}, ask, self.comments.append, lambda: set(have), self.tickets, file).run()

    def test_a_valid_plan_files_a_child_per_change_set_and_comments_the_plan(self):
        got = self.go(plan(2))
        self.assertEqual((got["ending"], len(got["children"]), got["cost"]), ("planned", 2, 0.07))
        self.assertEqual(self.filed[0][:2], (7, ["CS-1", "CS-2"]))
        self.assertIsNone(self.filed[0][3])
        self.assertIn("Plan: 2 change sets", self.comments[-1])
        self.assertIn("CS-2 (#101)", self.comments[-1])

    FIX = {"fix_for": 12, "flag_story": 12, "origin_parent": 5, "flag": True, "attempt": 1}

    def test_a_bug_intake_that_fixes_a_child_is_told_to_plan_one_change_set_and_files_it_with_the_fix(self):
        got = self.go(plan(1), fix=self.FIX)
        self.assertEqual(got["ending"], "planned")
        self.assertIn("Plan exactly ONE change set", self.asked[0])
        self.assertTrue(self.asked[0].endswith("Add tags"))
        self.assertEqual(self.filed[0][3], self.FIX)

    def test_a_fix_of_more_than_one_change_set_is_refused_and_nothing_is_filed(self):
        got = self.go(plan(2), fix=self.FIX)
        self.assertEqual(got["ending"], "needs_human")
        self.assertEqual(self.filed, [])
        self.assertIn("rejected", got["message"])

    def test_the_same_plan_for_an_ordinary_intake_may_have_several(self):
        self.assertEqual(self.go(plan(2))["ending"], "planned")

    def test_a_single_change_set_is_still_a_child(self):
        got = self.go(plan(1))
        self.assertEqual((got["ending"], len(got["children"])), ("planned", 1))

    def test_an_intake_that_already_has_children_is_not_planned_again_or_paid_for(self):
        child = self.gh.add(30)
        self.gh.subs[7] = [child]
        got = self.go(plan(1))
        self.assertEqual(got["ending"], "skipped")
        self.assertEqual((self.asked, self.filed, self.comments), ([], [], []))

    def test_a_request_the_factory_cannot_build_is_refused_with_what_could_be_built(self):
        refusal = {"feasibility": {"status": "blocked", "category": "payments", "reasons": ["takes card payments"], "possible_if": "a free tier"}}
        got = self.go(refusal)
        self.assertEqual(got["ending"], "refused")
        self.assertIn("payments", self.comments[-1].lower())
        self.assertIn("remove the `update-app-intake` label and add it again", self.comments[-1])
        self.assertEqual(self.filed, [])

    def test_a_blocking_question_stops_for_a_person_and_shows_the_plan(self):
        got = self.go(plan(1, open_questions=[{"id": "Q-1", "text": "Public photos?", "blocking": True}]))
        self.assertEqual(got["ending"], "needs_human")
        self.assertIn("Public photos?", self.comments[-1])
        self.assertEqual(self.filed, [])

    def test_a_plan_that_fails_the_check_is_rejected_with_the_reasons(self):
        bad = plan(1)
        bad["change_sets"][0]["size"] = "L"
        got = self.go(bad)
        self.assertEqual(got["ending"], "needs_human")
        self.assertIn("size L", self.comments[-1])
        self.assertEqual(self.filed, [])

    def test_no_valid_plan_from_the_agent_is_a_stop_that_costs_what_it_cost(self):
        got = self.go(ask_error=run_stops.NeedsHuman("other", "the planner produced no valid output file twice"))
        self.assertEqual(got["ending"], "needs_human")
        self.assertIn("no valid output file", self.comments[-1])

    def test_missing_secrets_wait_for_the_owner_before_anything_is_filed(self):
        doc = plan(1, secrets=[{"name": "WEATHER_API_KEY", "purpose": "forecasts", "read_by": "backend"}])
        got = self.go(doc)
        self.assertEqual(got["ending"], "awaiting_secret")
        self.assertIn("WEATHER_API_KEY", self.comments[-1])
        self.assertIn("factory-secrets", self.comments[-1])  # the hidden marker every later start checks
        self.assertEqual(self.filed, [])
        done = self.go(doc, have=["WEATHER_API_KEY"])
        self.assertEqual(done["ending"], "planned")
        self.assertEqual(self.filed[-1][2][0]["name"], "WEATHER_API_KEY")

    def test_secrets_the_intake_already_declared_are_checked_before_the_planner_is_paid(self):
        got = self.go(plan(1), declared=[{"name": "A_KEY", "purpose": "x"}])
        self.assertEqual(got["ending"], "awaiting_secret")
        self.assertEqual(self.asked, [])

    def test_every_stop_tells_the_owner_how_to_plan_again(self):
        self.go(ask_error=run_stops.NeedsHuman("other", "x"))
        self.assertIn("remove the `update-app-intake` label and add it again", self.comments[-1])

    def test_a_new_app_is_planned_as_a_first_build_so_its_first_set_must_be_staging(self):
        got = self.go(plan(1), kind="new")
        self.assertEqual(got["ending"], "needs_human")
        self.assertIn("staging", self.comments[-1])


class SecretsCheck(unittest.TestCase):
    def test_names_come_from_the_secret_list_and_never_a_value(self):
        run = lambda args: mock.Mock(returncode=0, stdout=json.dumps([{"name": "A"}, {"name": "B"}]))
        self.assertEqual(secrets_check.present_names(run, "o/app"), {"A", "B"})
        with self.assertRaises(secrets_check.SecretsUnreadable):
            secrets_check.present_names(lambda args: mock.Mock(returncode=1, stdout=""), "o/app")


class Trigger(unittest.TestCase):
    def test_plan_yml_starts_on_the_two_intake_labels_only_and_serializes_per_issue(self):
        wf = yaml.safe_load((ROOT / ".github/workflows/plan.yml").read_text())
        self.assertEqual(wf[True]["issues"]["types"], ["labeled"])
        job = next(iter(wf["jobs"].values()))
        cond = " ".join(job["if"].split())
        for label in ("new-app-intake", "update-app-intake"):
            self.assertIn(f"github.event.label.name == '{label}'", cond)
        self.assertIn("factory-plan", cond)  # a child ticket (it carries the update-app-intake label) is never planned
        self.assertIn("benchmark", cond)
        self.assertIn("plan-${{ github.event.issue.number }}", wf["concurrency"]["group"])
        self.assertIs(wf["concurrency"]["cancel-in-progress"], False)
        text = (ROOT / ".github/workflows/plan.yml").read_text()
        for absent in ("setup-node", "flyctl", "playwright"):
            self.assertNotIn(absent, text)


class SeedWorkdir(unittest.TestCase):
    def test_a_new_apps_planner_gets_a_copy_of_the_starter_without_its_dependencies(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            starter, work = Path(tmp) / "starter", Path(tmp) / "work" / "app"
            (starter / "backend" / "src").mkdir(parents=True)
            (starter / "node_modules" / "x").mkdir(parents=True)
            (starter / "AGENTS.md").write_text("rules")
            (starter / "backend" / "src" / "app.ts").write_text("code")
            plan_run.seed_workdir(work, starter)
            self.assertEqual((work / "AGENTS.md").read_text(), "rules")
            self.assertTrue((work / "backend" / "src" / "app.ts").exists())
            self.assertFalse((work / "node_modules").exists())
            (work / "AGENTS.md").write_text("changed")
            self.assertEqual((starter / "AGENTS.md").read_text(), "rules")  # a copy: reading or editing it never touches the Starter

    def test_the_real_starter_has_what_the_planner_is_told_to_read(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            plan_run.seed_workdir(Path(tmp) / "app")
            self.assertTrue((Path(tmp) / "app" / "AGENTS.md").exists())
            self.assertTrue((Path(tmp) / "app" / "backend" / "src" / "app.ts").exists())


if __name__ == "__main__":
    unittest.main()
