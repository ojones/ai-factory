import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_run as b  # noqa: E402
import update_intake as u  # noqa: E402

FORM = "### App name\n\n{app}\n\n### What should change?\n\n{task}\n\n### Cost cap override (USD)\n\n{cap}\n"


def proc(stdout="", returncode=0):
    return mock.Mock(stdout=stdout, returncode=returncode, stderr="")


class Form(unittest.TestCase):
    def test_the_app_name_is_read_and_checked(self):
        self.assertEqual(u.app_name(FORM.format(app="recipe-box", task="x", cap="")), "recipe-box")
        for bad in ("", "_No response_", "Recipe Box", "-x", "a" * 31, "my_app", "x/../y"):
            with self.assertRaises(ValueError, msg=bad):
                u.app_name(FORM.format(app=bad, task="x", cap=""))

    def test_only_a_repo_this_factory_created_is_ours(self):
        self.assertTrue(u.is_factory_repo("Intake: o/ai-factory#12", "o/ai-factory"))
        for bad in ("Intake: o/other#12", "Intake: o/ai-factory#12 and more", "", None, "A personal project", "Intake: o/ai-factory#x"):
            self.assertFalse(u.is_factory_repo(bad, "o/ai-factory"), bad)

    def test_a_task_both_parsers_agree_on(self):
        body = FORM.format(app="a", task="Add search\nby title", cap="$3")
        self.assertEqual(b.parse_intake(body, 2.0, 10.0), ("Add search\nby title", 3.0))
        self.assertEqual(b.parse_intake("### What should be built?\n\nA thing\n", 2.0, 10.0), ("A thing", 2.0))
        with self.assertRaises(b.NeedsHuman):
            b.parse_intake(FORM.format(app="a", task="_No response_", cap=""), 2.0, 10.0)


class ChangeSets(unittest.TestCase):
    CS = {"id": "CS-2", "title": "Filter by species", "criteria": ["AC-1: ?species= filters"], "verification": ["curl with the filter"],
          "out_of_scope": ["sorting"], "flag": "species-filter"}

    def test_the_task_carries_criteria_checks_scope_and_the_flag(self):
        text = u.render_change_set_task(self.CS, request="Record sightings and filter them", parent=7)
        for needle in ("Change set CS-2: Filter by species", "planned in #7", "Record sightings and filter them", "- AC-1: ?species= filters",
                       "- curl with the filter", "- sorting", "slug `species-filter`"):
            self.assertIn(needle, text)

    def test_an_internal_change_says_it_needs_no_flag(self):
        text = u.render_change_set_task(dict(self.CS, flag=None, out_of_scope=[]))
        self.assertIn("needs no flag", text)
        self.assertNotIn("Out of scope", text)
        self.assertNotIn("original request", text)

    def test_child_metadata_round_trips_and_other_issues_have_none(self):
        body = u.child_body("notes", "do it", 7, "CS-2", [41, 42])
        self.assertEqual(u.plan_meta(body), {"parent": 7, "cs": "CS-2", "depends_on": [41, 42]})
        self.assertEqual(u.app_name(body), "notes")
        self.assertEqual(b.parse_intake(body, 2.0, 10.0)[0], "do it")
        for none in ("", None, "no marker", "<!-- factory-plan:{broken -->", "<!-- factory-plan:[1] -->"):
            self.assertEqual(u.plan_meta(none), {})

    def test_children_keep_the_parents_cost_cap(self):
        self.assertEqual(b.parse_intake(u.child_body("notes", "t", 7, "CS-1", [], "1.00"), 2.0, 10.0)[1], 1.0)
        self.assertEqual(b.parse_intake(u.child_body("notes", "t", 7, "CS-1", []), 2.0, 10.0)[1], 2.0)

    def test_the_plan_comment_shows_change_sets_assumptions_and_questions(self):
        plan = {"change_sets": [{"id": "CS-1", "title": "Soft-delete a todo", "flag": "delete-todo"},
                                {"id": "CS-2", "title": "Cleanup", "flag": None}],
                "assumptions": ["Deleting is a soft delete, so records are kept"]}
        text = u.render_plan_comment(plan, ["Should deleted todos be recoverable?"])
        for needle in ("Plan: 2 change sets", "**CS-1** Soft-delete a todo (flag `delete-todo`)", "no flag (internal)",
                       "Assumptions I made for you", "soft delete, so records are kept", "I need an answer", "recoverable?"):
            self.assertIn(needle, text)
        one = u.render_plan_comment({"change_sets": [{"id": "CS-1", "title": "x", "flag": "f"}]})
        self.assertIn("Plan: 1 change set.", one)
        self.assertNotIn("Assumptions", one)
        self.assertNotIn("answer", one)

    def test_titles_are_one_short_line(self):
        self.assertEqual(u.one_line("a\n  b\tc"), "a b c")
        self.assertEqual(len(u.one_line("x" * 500)), 80)


class Ordering(unittest.TestCase):
    def kids(self, spec):
        return [{"number": n, "state": st, "labels": set(lb), "depends_on": deps} for n, st, lb, deps in spec]

    def test_a_child_starts_when_everything_it_waits_on_is_closed(self):
        kids = self.kids([(1, "CLOSED", [], []), (2, "OPEN", [u.WAIT], [1]), (3, "OPEN", [u.WAIT], [1, 2])])
        self.assertEqual(u.ready_to_start(kids), [2])
        kids[1]["state"] = "CLOSED"
        self.assertEqual(u.ready_to_start(kids), [3])

    def test_only_one_child_starts_at_a_time_the_lowest_number_first(self):
        kids = self.kids([(1, "CLOSED", [], []), (3, "OPEN", [u.WAIT], [1]), (2, "OPEN", [u.WAIT], [1])])
        self.assertEqual(u.ready_to_start(kids), [2])

    def test_nothing_starts_while_another_child_is_in_flight(self):
        kids = self.kids([(1, "OPEN", [u.GO], []), (2, "OPEN", [u.WAIT], []), (3, "OPEN", [u.WAIT], [])])
        self.assertEqual(u.ready_to_start(kids), [])
        kids[0]["state"] = "CLOSED"
        self.assertEqual(u.ready_to_start(kids), [2])

    def test_nothing_starts_twice_or_early_or_when_a_dependency_is_unknown(self):
        kids = self.kids([(1, "OPEN", [u.GO], []), (2, "OPEN", [u.WAIT], [1]), (3, "OPEN", [u.WAIT, u.GO], []),
                          (4, "OPEN", [u.WAIT], [99]), (5, "OPEN", [], []), (6, "CLOSED", [u.WAIT], [])])
        self.assertEqual(u.ready_to_start(kids), [])


class GitHub(unittest.TestCase):
    def test_children_are_filed_dependencies_first_and_only_the_roots_start(self):
        calls, counter = [], iter(range(101, 200))

        def fake(args, token, check=False):
            calls.append(args)
            if args[:2] == ["issue", "create"]:
                return proc(f"https://github.com/o/f/issues/{next(counter)}\n")
            return proc()

        sets = [{"id": "CS-1", "title": "Save", "criteria": ["a"], "verification": ["b"], "flag": "save", "depends_on": []},
                {"id": "CS-2", "title": "Filter", "criteria": ["a"], "verification": ["b"], "flag": "filter", "depends_on": ["CS-1"]},
                {"id": "CS-3", "title": "Export", "criteria": ["a"], "verification": ["b"], "flag": "export", "depends_on": []}]
        with mock.patch.object(u, "gh", fake):
            made = u.file_children("o/f", "pat", "notes", 7, sets, ["CS-1", "CS-2", "CS-3"], "the request")
        self.assertEqual(made, [("CS-1", 101), ("CS-2", 102), ("CS-3", 103)])
        creates = [c for c in calls if c[:2] == ["issue", "create"]]
        self.assertEqual(len(creates), 3)
        second = creates[1]
        self.assertEqual(u.plan_meta(second[second.index("--body") + 1])["depends_on"], [101])
        self.assertIn(u.WAIT, second[second.index("--label") + 1])
        self.assertIn("plan:7", second[second.index("--label") + 1])
        starts = [c for c in calls if c[:2] == ["issue", "edit"]]
        self.assertEqual([c[2] for c in starts], ["101"])  # CS-3 has nothing to wait for either, but waits its turn
        self.assertIn(u.GO, starts[0])
        last_create = max(i for i, c in enumerate(calls) if c[:2] == ["issue", "create"])
        self.assertGreater(calls.index(starts[0]), last_create)

    def test_advance_starts_the_siblings_a_finished_child_was_holding_up(self):
        body = lambda deps: u.child_body("notes", "t", 7, "CS", deps)
        listing = [{"number": 101, "state": "CLOSED", "labels": [{"name": "plan:7"}], "body": body([])},
                   {"number": 102, "state": "OPEN", "labels": [{"name": u.WAIT}], "body": body([101])},
                   {"number": 103, "state": "OPEN", "labels": [{"name": u.WAIT}], "body": body([101, 102])}]
        edits = []

        def fake(args, token, check=False):
            if args[:2] == ["issue", "view"]:
                return proc(json.dumps({"body": body([])}))
            if args[:2] == ["issue", "list"]:
                return proc(json.dumps(listing))
            edits.append(args)
            return proc()

        with mock.patch.object(u, "gh", fake):
            self.assertEqual(u.advance("o/f", "pat", 101), [102])
        self.assertEqual([e[2] for e in edits], ["102"])
        self.assertIn(u.GO, edits[0])
        self.assertIn(u.WAIT, edits[0])

    def test_advance_on_an_issue_that_is_not_part_of_a_plan_does_nothing(self):
        with mock.patch.object(u, "gh", lambda args, token, check=False: proc(json.dumps({"body": "just a request"}))):
            self.assertEqual(u.advance("o/f", "pat", 5), [])

    def run_start(self, body, repo_json=None, repo_rc=0):
        calls = []

        def fake(args, token, check=False):
            calls.append(args)
            if args[0] == "api":
                return proc(json.dumps(repo_json or {}), repo_rc)
            return proc()

        env = {"FACTORY_REPO": "o/f", "FACTORY_PAT": "pat", "GH_TOKEN": "t", "ISSUE_NUMBER": "9", "ISSUE_BODY": body, "RUN_URL": "u"}
        with mock.patch.dict(os.environ, env), mock.patch.object(u, "gh", fake):
            return u.start(), calls

    def test_a_good_update_intake_is_labelled_dispatched_and_acknowledged(self):
        code, calls = self.run_start(FORM.format(app="notes", task="Add tags", cap=""), {"description": "Intake: o/f#3"})
        self.assertEqual(code, 0)
        dispatch = next(c for c in calls if c[:2] == ["workflow", "run"])
        self.assertIn("issue_number=9", dispatch)
        self.assertIn("app_name=notes", dispatch)
        self.assertTrue(any("app:notes" in c for c in calls if c[:2] == ["issue", "edit"]))
        self.assertTrue(any(c[:2] == ["issue", "comment"] and "accepted" in c[-1] for c in calls))

    def test_every_refusal_comments_removes_the_label_and_dispatches_nothing(self):
        cases = [(FORM.format(app="Bad Name", task="x", cap=""), {}, 0),
                 (FORM.format(app="notes", task="_No response_", cap=""), {}, 0),
                 (FORM.format(app="ghost", task="x", cap=""), {}, 1),
                 (FORM.format(app="notes", task="x", cap=""), {"description": "someone else's repo"}, 0)]
        for body, repo_json, rc in cases:
            code, calls = self.run_start(body, repo_json, rc)
            self.assertEqual(code, 1, body)
            self.assertFalse([c for c in calls if c[:2] == ["workflow", "run"]], body)
            self.assertTrue(any(c[:2] == ["issue", "comment"] and "stopped" in c[-1] for c in calls), body)
            self.assertTrue(any(c[:2] == ["issue", "edit"] and "--remove-label" in c and u.GO in c for c in calls), body)


class Identity(unittest.TestCase):
    def issue(self, title="notes", labels=(), body=""):
        return {"title": title, "body": body, "labels": [{"name": n} for n in labels]}

    def test_a_new_app_intake_is_titled_with_the_app(self):
        self.assertEqual(b.identify_intake(self.issue(labels=["intake"]), "notes", 5), (False, {}))
        with self.assertRaises(b.NeedsHuman):
            b.identify_intake(self.issue(title="other"), "notes", 5)

    def test_an_update_intake_needs_the_form_the_label_and_the_matching_app(self):
        body = FORM.format(app="notes", task="x", cap="")
        ok = self.issue(title="notes: add tags", labels=["update-intake", "app:notes"], body=body)
        self.assertEqual(b.identify_intake(ok, "notes", 5), (True, {}))
        for bad in (self.issue(labels=["update-intake"], body=body),  # no app: label
                    self.issue(labels=["update-intake", "app:todo"], body=body),
                    self.issue(labels=["update-intake", "app:todo"], body=FORM.format(app="todo", task="x", cap="")),
                    self.issue(labels=["update-intake", "app:notes"], body="no form")):
            with self.assertRaises(b.NeedsHuman):
                b.identify_intake(bad, "notes", 5)

    def test_a_child_issue_reports_its_plan_metadata(self):
        body = u.child_body("notes", "t", 7, "CS-2", [101])
        _, meta = b.identify_intake(self.issue(labels=["update-intake", "app:notes"], body=body), "notes", 5)
        self.assertEqual(meta["parent"], 7)


class Planning(unittest.TestCase):
    def make(self, doc, kind="update"):
        run = object.__new__(b.BuildRun)
        run.work, run.art = Path("/tmp/unused-work"), Path("/tmp/unused-art")
        run.art.mkdir(exist_ok=True)
        run.lim, run.build_kind, run.app, run.issue = {}, kind, "notes", "9"
        run.factory_repo, run.pat = "o/f", "pat"
        run.task = run.spec = "Record sightings and filter them"
        run.cap_override = "1.00"
        run.state = b.State("/tmp/unused-state.json", "notes", "9", "u")
        run.state.save = lambda: None
        run.agent_json = mock.Mock(side_effect=lambda role, label, values, path, check=None, **kw: (check(doc) if check else None, doc, 0.1, None)[1:])
        return run

    def plan(self, n=1, questions=()):
        sets = [{"id": f"CS-{i}", "title": f"Part {i}", "requirements": ["REQ-1"], "depends_on": [f"CS-{i - 1}"] if i > 1 else [],
                 "criteria": [f"AC-1: part {i} works"], "verification": ["curl it"], "flag": f"part-{i}", "internal_only": False, "out_of_scope": []}
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
        with mock.patch.object(u, "file_children", return_value=[("CS-1", 11), ("CS-2", 12), ("CS-3", 13)]) as filed:
            self.assertTrue(run.plan_change())
        args = filed.call_args[0]
        self.assertEqual((args[0], args[2], args[3], args[5]), ("o/f", "notes", 9, ["CS-1", "CS-2", "CS-3"]))
        self.assertEqual(filed.call_args[1]["cap"], "1.00")
        self.assertEqual(run.state.d["outcome"], "planned")
        self.assertIn("CS-2 (#12)", run.state.d["message"])
        self.assertEqual(len(run.state.d["plan"]["change_sets"]), 3)

    def test_a_blocking_question_stops_the_run_for_a_person(self):
        run = self.make(self.plan(1, questions=["Should photos be public?"]))
        with self.assertRaises(b.NeedsHuman) as cm:
            run.plan_change()
        self.assertIn("Should photos be public?", str(cm.exception))
        self.assertIn("proceed-with-change", str(cm.exception))

    def test_a_plan_that_fails_the_check_is_rejected_with_the_reasons(self):
        bad = self.plan(2)
        bad["change_sets"][1]["depends_on"] = ["CS-9"]
        run = self.make(bad)
        run.agent_json = mock.Mock(side_effect=lambda role, label, values, path, check=None, **kw: (_ for _ in ()).throw(
            b.NeedsHuman("other", "no valid output twice")) if check and not _passes(check, bad) else (bad, 0.1, None))
        with self.assertRaises(b.NeedsHuman) as cm:
            run.plan_change()
        self.assertIn("rejected", str(cm.exception))
        self.assertIn("CS-9", str(cm.exception))


def _passes(check, doc):
    try:
        check(doc)
        return True
    except ValueError:
        return False


class Finishing(unittest.TestCase):
    def test_a_finished_update_intake_is_closed_and_releases_its_dependents(self):
        with mock.patch.object(b, "sh") as sh, mock.patch.object(u, "advance") as advance:
            b.finish_update_intake(True, "o/f", "9", "pat")
        self.assertEqual(sh.call_args[0][0][:3], ["gh", "issue", "close"])
        advance.assert_called_once_with("o/f", "pat", "9")

    def test_a_stopped_one_loses_the_go_label_so_it_can_be_retried(self):
        with mock.patch.object(b, "sh") as sh, mock.patch.object(u, "advance") as advance:
            b.finish_update_intake(False, "o/f", "9", "pat")
        cmd = sh.call_args[0][0]
        self.assertEqual(cmd[:3], ["gh", "issue", "edit"])
        self.assertIn("--remove-label", cmd)
        self.assertIn(u.GO, cmd)
        advance.assert_not_called()

    def test_a_failure_while_finishing_never_raises(self):
        with mock.patch.object(b, "sh", side_effect=OSError("no gh")):
            b.finish_update_intake(True, "o/f", "9", "pat")


class Spec(unittest.TestCase):
    def test_an_update_is_reviewed_against_its_change_request_not_the_original_intake(self):
        git = lambda *a: {"diff": "D", "show": "X"}.get(a[0], "") if "--name-only" not in a else ""
        text = b.build_review_context(git, "base", "head", 10**6, spec="Add tags to notes")
        self.assertIn("# Change request (the spec for this change)\nAdd tags to notes", text)
        self.assertNotIn("# INTAKE.md", text)
        self.assertIn("# INTAKE.md", b.build_review_context(git, "base", "head", 10**6))

    def test_every_module_agrees_on_what_a_good_ending_is(self):
        import appstate, audit, dashboard
        self.assertEqual(set(b.OK_OUTCOMES), set(audit.OK_OUTCOMES))
        self.assertEqual(set(b.OK_OUTCOMES), set(appstate.OK))
        self.assertEqual(set(b.OK_OUTCOMES), set(dashboard.OK))


if __name__ == "__main__":
    unittest.main()
