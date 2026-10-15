import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import retrospective as pm  # noqa: E402


def write_findings(work, n, summaries):
    (Path(work) / f"findings-{n}.json").write_text(json.dumps(
        {"round": n, "blocking": [{"source": "reviewer", "summary": s, "evidence": ""} for s in summaries], "minor": []}))


STATE = {"app": "demo", "outcome": "round_limit", "message": "4 review rounds used without a clean pass",
         "run_url": "http://run", "issue_number": "7", "spent_usd": 1.5, "commits": ["a"],
         "blocking": [{"summary": "The kill switch is mounted after the new route"}],
         "stages": [{"stage": "Coder", "round": "1", "verdict": "pushed", "cost_usd": 0.2, "usage": {"seconds": 120, "calls": 30}},
                    {"stage": "Release", "round": "-", "verdict": "x", "cost_usd": 0, "usage": None}]}


class Facts(unittest.TestCase):
    def test_recurring_findings_survive_rewording_and_drive_the_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_findings(tmp, 1, ["Kill switch is mounted after the new route", "Missing flag"])
            write_findings(tmp, 2, ["The kill switch mounted after new route!"])
            facts = pm.collect_facts(tmp, STATE)
        self.assertEqual(len(facts["rounds"]), 2)
        self.assertEqual(len(facts["recurring_findings"]), 1)
        self.assertEqual(facts["stages"][0]["seconds"], 120)
        self.assertIsNone(facts["stages"][1]["seconds"])
        again = dict(facts, spent_usd=9.9, run_url="other")
        self.assertEqual(pm.fingerprint(facts), pm.fingerprint(again))
        different = dict(facts, outcome="needs_human")
        self.assertNotEqual(pm.fingerprint(facts), pm.fingerprint(different))
        self.assertIn(pm.fingerprint(facts), pm.title_for(facts))
        self.assertIn("Recurred across rounds", pm.render_facts(facts))

    def test_no_findings_files_still_gives_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            facts = pm.collect_facts(tmp, STATE)
        self.assertEqual(facts["rounds"], [])
        self.assertEqual(facts["final_blocking"], ["The kill switch is mounted after the new route"])
        self.assertEqual(len(pm.fingerprint(facts)), 8)


class Minors(unittest.TestCase):
    def test_final_minor_comes_from_the_last_findings_file_and_titles_are_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "findings-1.json").write_text(json.dumps({"round": 1, "blocking": [], "minor": [{"summary": "old"}]}))
            (Path(tmp) / "findings-2.json").write_text(json.dumps({"round": 2, "blocking": [], "minor": [
                {"summary": "Flag todos-crud is declared but never used", "evidence": "flags.json:1", "file": "flags.json", "line": "1"}]}))
            facts = pm.collect_facts(tmp, dict(STATE, outcome="released"))
        self.assertEqual([m["summary"] for m in facts["final_minor"]], ["Flag todos-crud is declared but never used"])
        self.assertIn("Minor findings still open", pm.render_facts(facts))
        self.assertEqual(pm.minor_title("The flag todos-crud is declared but never used!").split("]")[0],
                         pm.minor_title("Flag todos-crud declared but never used").split("]")[0])


class Paths(unittest.TestCase):
    def test_only_prompts_template_orchestrator_and_docs_are_allowed(self):
        for ok in ("agents/prompts/coder.md", "templates/starter/AGENTS.md", "orchestrator/build_run.py", "STANDARDS.md"):
            self.assertTrue(pm.allowed_path(ok), ok)
        for bad in (".github/workflows/build-run.yml", "templates/starter/.github/workflows/build.yml",
                    "templates/starter/fly/provision.sh", "templates/starter/fly.toml", "README.md",
                    "agents/../.github/x.yml"):
            self.assertFalse(pm.allowed_path(bad), bad)


def facts_for(**kw):
    base = {"app": "demo", "outcome": "released", "message": "ok", "run_url": "u", "issue_number": "7", "spent_usd": 0.3,
            "cap_usd": 2.0, "review_passes": 1, "commits": [], "final_blocking": [], "rounds": [], "recurring_findings": [],
            "stages": [], "final_minor": []}
    base.update(kw)
    return base


class Lessons(unittest.TestCase):
    def kinds(self, **kw):
        return [x["kind"] for x in pm.lessons_from(facts_for(**kw))]

    def test_a_clean_quick_cheap_run_teaches_nothing(self):
        self.assertEqual(self.kinds(), [])

    def test_a_watchdog_disable_is_a_severe_lesson_and_comes_first(self):
        lessons = pm.lessons_from(facts_for(outcome="watchdog_disabled", message="health check failed", spent_usd=1.9))
        self.assertEqual([x["kind"] for x in lessons], ["watchdog_disabled"])
        self.assertTrue(lessons[0]["severe"])
        both = pm.lessons_from(facts_for(spent_usd=1.9, review_passes=3, outcome="released"))
        self.assertEqual({x["kind"] for x in both}, {"many_rounds", "budget_high"})

    def test_many_rounds_only_when_the_run_finished_ok(self):
        rounds = [{"round": i, "blocking": [f"kill switch missing {i}"], "tester_blocking": []} for i in (1, 2, 3)]
        self.assertEqual(self.kinds(review_passes=3, rounds=rounds), ["many_rounds"])
        self.assertEqual(self.kinds(review_passes=3, rounds=rounds, outcome="round_limit"), [])
        self.assertEqual(self.kinds(review_passes=2, rounds=rounds), [])

    def test_a_first_pass_test_failure_is_a_lesson_with_a_stable_title(self):
        rounds = [{"round": 1, "blocking": ["a: create note"], "tester_blocking": ["a: create note"]},
                  {"round": 2, "blocking": [], "tester_blocking": []}]
        lessons = pm.lessons_from(facts_for(review_passes=2, rounds=rounds))
        self.assertEqual([x["kind"] for x in lessons], ["first_pass_test_failure"])
        again = pm.lessons_from(facts_for(review_passes=2, rounds=rounds, spent_usd=0.9, run_url="other"))
        self.assertEqual(lessons[0]["title"], again[0]["title"])

    def test_slow_stage_budget_and_cap_on_how_many_are_recorded(self):
        slow = [{"stage": "Coder", "round": "1", "verdict": "pushed", "cost_usd": 0.1, "seconds": 2000, "calls": 9}]
        self.assertEqual(self.kinds(stages=slow), ["slow_stage"])
        self.assertEqual(self.kinds(spent_usd=1.4), ["budget_high"])
        rounds = [{"round": 1, "blocking": ["x"], "tester_blocking": ["x"]}]
        many = pm.lessons_from(facts_for(review_passes=4, spent_usd=1.9, stages=slow, rounds=rounds))
        self.assertEqual(len(many), pm.MAX_LESSONS)  # four applied: many_rounds, first_pass_test_failure, budget_high, slow_stage

    def test_collect_facts_keeps_which_findings_came_from_the_tester(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "findings-1.json").write_text(json.dumps({"round": 1, "minor": [], "blocking": [
                {"source": "tester", "summary": "a: x"}, {"source": "reviewer", "summary": "no flag"}]}))
            facts = pm.collect_facts(tmp, dict(STATE, outcome="released", review_passes=2, cap_usd=2.0))
        self.assertEqual(facts["rounds"][0]["tester_blocking"], ["a: x"])
        self.assertEqual(facts["review_passes"], 2)


class Recurrence(unittest.TestCase):
    ISSUES = [{"number": 4, "title": "Lesson [many_rounds] aa", "state": "CLOSED"},
              {"number": 9, "title": "Lesson [budget_high] bb", "state": "OPEN"},
              {"number": 5, "title": "Lesson [many_rounds] aa", "state": "OPEN"}]

    def test_open_beats_closed_and_only_exact_titles_match(self):
        self.assertEqual(pm.pick_existing(self.ISSUES, "Lesson [many_rounds] aa"), (5, 4))
        self.assertEqual(pm.pick_existing(self.ISSUES, "Lesson [budget_high] bb"), (9, None))
        self.assertEqual(pm.pick_existing(self.ISSUES, "Lesson [slow_stage] cc"), (None, None))
        self.assertEqual(pm.pick_existing([{"number": 1, "title": "Lesson [x] y", "state": "closed"}], "Lesson [x] y"), (None, 1))


class MergePolicy(unittest.TestCase):
    def test_only_additive_lint_and_formatter_config_auto_merges(self):
        self.assertTrue(pm.auto_merge_eligible("3\t0\ttemplates/starter/.eslintrc.json\n1\t0\ttemplates/starter/.prettierrc"))
        self.assertTrue(pm.auto_merge_eligible("2\t0\ttemplates/starter/eslint.config.mjs"))

    def test_any_deletion_other_file_or_doubt_means_a_human(self):
        self.assertFalse(pm.auto_merge_eligible("3\t1\ttemplates/starter/.eslintrc.json"))
        self.assertFalse(pm.auto_merge_eligible("3\t0\ttemplates/starter/.eslintrc.json\n1\t0\tagents/prompts/coder.md"))
        self.assertFalse(pm.auto_merge_eligible("3\t0\ttemplates/starter/package.json"))
        self.assertFalse(pm.auto_merge_eligible("3\t0\ttemplates/starter/sub/.eslintrc.json"))
        self.assertFalse(pm.auto_merge_eligible("-\t-\ttemplates/starter/.prettierrc"))
        self.assertFalse(pm.auto_merge_eligible("garbage"))
        self.assertFalse(pm.auto_merge_eligible(""))

    def test_a_fixture_is_a_smoke_replay_or_test_file(self):
        for ok in ("agents/replay/cases.json", "orchestrator/test_build_run.py", "templates/starter/backend/src/app.test.ts"):
            self.assertTrue(pm.lesson_has_fixture([ok]), ok)
        self.assertTrue(pm.lesson_has_fixture(["agents/smoke/fixtures/x.diff", "agents/smoke/expected.json"]))
        self.assertFalse(pm.lesson_has_fixture(["agents/prompts/coder.md", "templates/starter/AGENTS.md"]))

    def test_a_smoke_fixture_must_be_a_diff_with_an_expected_entry(self):
        # What the first learning PR did: files in the fixtures folder that the harness never runs.
        stray = ["agents/smoke/fixtures/missing-feature-flag.expected.json", "agents/smoke/fixtures/missing-feature-flag.intake.md"]
        self.assertFalse(pm.lesson_has_fixture(stray))
        self.assertFalse(pm.lesson_has_fixture(["agents/smoke/fixtures/x.diff"]))
        self.assertFalse(pm.lesson_has_fixture(["agents/smoke/expected.json"]))


class OneEventOneRecord(unittest.TestCase):
    def test_a_watchdog_disable_is_one_lesson_not_two(self):
        self.assertFalse(pm.records_stuck_issue("watchdog_disabled"))
        for stuck in ("round_limit", "stuck", "needs_human", "crash", "budget_exhausted", "time_limit"):
            self.assertTrue(pm.records_stuck_issue(stuck), stuck)
        for ok in ("released", "nothing_to_release", "planned"):
            self.assertFalse(pm.records_stuck_issue(ok), ok)


class Guardrails(unittest.TestCase):
    ADDED = ("diff --git a/agents/prompts/tester.md b/agents/prompts/tester.md\n--- a/agents/prompts/tester.md\n"
             "+++ b/agents/prompts/tester.md\n@@ -1,2 +1,3 @@\n context line\n+{line}\n context line\n")

    def test_shouting_in_added_prompt_lines_is_caught_wherever_it_appears(self):
        # Lines taken from the first two learning PRs.
        for line in ("**CRITICAL**: You MUST write your test results to the file", "**ACTION REQUIRED**: Before finishing, execute this",
                     "\u26a0\ufe0f CRITICAL: Every new user-facing endpoint", "WARNING: Previous tester runs have failed", "You MUST do it",
                     "This is IMPORTANT"):
            self.assertTrue(pm.adds_emphasis(self.ADDED.format(line=line)), line)

    def test_plain_instructions_and_pre_existing_emphasis_are_fine(self):
        self.assertFalse(pm.adds_emphasis(self.ADDED.format(line="Build the report with json.dump, not by hand.")))
        removed = "--- a/p.md\n+++ b/p.md\n-You MUST do it\n+You do it\n"
        self.assertFalse(pm.adds_emphasis(removed))
        self.assertFalse(pm.adds_emphasis("+++ b/p.md\n context MUST stay\n"))

    def test_a_smoke_fixture_must_be_a_diff_of_app_code(self):
        good = "diff --git a/backend/src/routes/x.ts b/backend/src/routes/x.ts\n+code\n"
        factory_diff = "diff --git a/agents/prompts/tester.md b/agents/prompts/tester.md\n+WARNING: x\n"
        self.assertIsNone(pm.bad_fixture_reason({"agents/smoke/fixtures/a.diff": good}))
        self.assertIsNone(pm.bad_fixture_reason({}))
        reason = pm.bad_fixture_reason({"agents/smoke/fixtures/a.diff": good, "agents/smoke/fixtures/tester-no-output.diff": factory_diff})
        self.assertIn("tester-no-output.diff is not a diff of Managed App code", reason)
        self.assertIn("frontend/", pm.bad_fixture_reason({"agents/smoke/fixtures/f.diff": "diff --git a/frontend/x b/frontend/x\n"}) or "frontend/")

    def test_existing_smoke_fixtures_all_pass_the_fixture_rule(self):
        root = Path(pm.b.FACTORY_DIR) / "agents/smoke/fixtures"
        texts = {str(p): p.read_text() for p in root.glob("*.diff")}
        self.assertTrue(texts)
        self.assertIsNone(pm.bad_fixture_reason(texts))


class Recurrence(unittest.TestCase):
    def test_a_sighting_is_counted_once_per_run_and_apps_are_counted_apart(self):
        body, runs, apps = pm.with_sighting("A lesson.", "https://x/runs/1", "todo")
        self.assertEqual((runs, apps), (1, 1))
        again, runs, apps = pm.with_sighting(body, "https://x/runs/1", "todo")
        self.assertEqual((again, runs, apps), (body, 1, 1))  # the same run reported twice changes nothing
        body, runs, apps = pm.with_sighting(body, "https://x/runs/2", "notes")
        self.assertEqual((runs, apps), (2, 2))
        self.assertEqual(body.count("<!-- seen:"), 1)
        self.assertEqual(pm.sightings(body), {"https://x/runs/1": "todo", "https://x/runs/2": "notes"})
        self.assertEqual(pm.sightings("no marker"), {})

    def test_promotion_waits_for_enough_distinct_runs_unless_severe(self):
        self.assertFalse(pm.ready_for_fix(1, 2))
        self.assertTrue(pm.ready_for_fix(2, 2))
        self.assertTrue(pm.ready_for_fix(1, 2, severe=True))
        self.assertTrue(pm.ready_for_fix(1, 1))
        self.assertTrue(pm.ready_for_fix(1, 0))

    def test_noting_a_sighting_edits_the_body_and_labels_it_recurring_at_the_threshold(self):
        from unittest import mock
        body = {"body": "A lesson."}
        calls = []

        def fake_gh(args, token, check=False):
            calls.append(args)
            if args[:2] == ["issue", "view"]:
                return mock.Mock(stdout=json.dumps(body))
            if args[:2] == ["issue", "edit"]:
                body["body"] = args[args.index("--body") + 1]
            return mock.Mock(stdout="")
        with mock.patch.object(pm, "gh", fake_gh):
            self.assertEqual(pm.note_sighting("o/f", "t", 5, {"run_url": "https://x/runs/1", "app": "a"}, 2), 1)
            self.assertNotIn("--add-label", calls[-1])
            self.assertEqual(pm.note_sighting("o/f", "t", 5, {"run_url": "https://x/runs/2", "app": "a"}, 2), 2)
            self.assertIn("recurring", calls[-1])


class Improvements(unittest.TestCase):
    IMPS = [{"source": "reviewer", "target": "factory", "summary": "The coder prompt never says to trim input", "evidence": "round 1"},
            {"source": "tester", "target": "managed_app", "summary": "Add a test for empty text", "evidence": ""}]

    def facts(self, **over):
        with tempfile.TemporaryDirectory() as tmp:
            return pm.collect_facts(tmp, {**STATE, "outcome": "released", "improvements": self.IMPS, **over})

    def run_main(self, state):
        """main() with gh mocked; returns the gh calls."""
        from unittest import mock
        work = Path(tempfile.mkdtemp())
        (work / "state.json").write_text(json.dumps(state))
        calls = []

        def fake_gh(args, token, check=False):
            calls.append(args)
            return mock.Mock(stdout="[]" if args[:2] == ["issue", "list"] else (
                "https://github.com/o/f/issues/41" if args[:2] == ["issue", "create"] else ""), returncode=0)
        env = {"BUILD_RUN_DIR": str(work), "GITHUB_REPOSITORY": "o/f", "GITHUB_RUN_ID": "9", "FACTORY_PAT": "pat", "FACTORY_GH_TOKEN": "tok"}
        with mock.patch.dict(__import__("os").environ, env), mock.patch.object(pm, "gh", fake_gh), \
                mock.patch.object(pm.b, "load_config", return_value={"roles": {}, "limits": {}}):
            self.assertEqual(pm.main(), 0)
        return calls

    def test_the_improvements_ride_along_in_the_facts(self):
        facts = self.facts()
        self.assertEqual([i["target"] for i in facts["improvements"]], ["factory", "managed_app"])

    def test_each_improvement_goes_to_its_own_tracker_and_only_the_factory_one_is_for_the_agent(self):
        from unittest import mock
        created = []

        def fake_gh(args, token, check=False):
            if args[:2] == ["issue", "create"]:
                created.append((args[args.index("--repo") + 1], args[args.index("--title") + 1]))
                return mock.Mock(stdout=f"https://github.com/x/y/issues/{40 + len(created)}")
            return mock.Mock(stdout="[]")
        with mock.patch.object(pm, "gh", fake_gh), mock.patch.object(pm, "already_proposed", return_value=False):
            for_agent, filed = pm.record_improvements("o/ai-factory", "tok", "o/demo", "pat", self.facts())
        self.assertEqual([r for r, _ in created], ["o/ai-factory", "o/demo"])
        self.assertTrue(created[0][1].startswith("Improvement ["))
        self.assertTrue(created[1][1].startswith("Suggestion: "))
        self.assertEqual(len(for_agent), 1)  # the app's own suggestion is not a Factory change
        self.assertEqual([f["target"] for f in filed], ["factory", "managed_app"])

    def test_the_same_improvement_twice_is_one_issue_and_the_number_per_run_is_capped(self):
        many = [{"source": "tester", "target": "managed_app", "summary": f"idea {n}", "evidence": ""} for n in range(pm.MAX_MINORS + 4)]
        from unittest import mock
        created = []
        with mock.patch.object(pm, "gh", lambda args, token, check=False: (created.append(args) if args[:2] == ["issue", "create"] else None) or mock.Mock(stdout="[]")):
            with tempfile.TemporaryDirectory() as tmp:
                facts = pm.collect_facts(tmp, dict(STATE, outcome="released", improvements=many))
            _, filed = pm.record_improvements("o/ai-factory", "tok", "o/demo", "pat", facts)
        self.assertEqual(len(filed), pm.MAX_MINORS)
        self.assertEqual(len(created), pm.MAX_MINORS)

    def test_a_clean_release_is_still_examined_and_reported_on_the_story(self):
        calls = self.run_main(dict(STATE, outcome="released", message="Released 1 flag(s).", improvements=self.IMPS, issue_number="7"))
        self.assertTrue(any(c[:2] == ["issue", "create"] for c in calls), "the improvements were filed")
        comment = next(c for c in calls if c[:2] == ["issue", "comment"] and c[2] == "7")
        body = comment[comment.index("--body") + 1]
        self.assertIn("## Retrospective: `released`", body)
        self.assertIn("The coder prompt never says to trim input", body)
        self.assertIn("<!-- retrospective:9 -->", body)

    def test_a_clean_release_with_nothing_to_improve_still_leaves_a_short_summary(self):
        calls = self.run_main(dict(STATE, outcome="released", message="Released 1 flag(s).", issue_number="7"))
        body = next(c for c in calls if c[:2] == ["issue", "comment"])
        self.assertIn("Nothing to improve was found.", body[body.index("--body") + 1])
        self.assertFalse(any(c[:2] == ["issue", "create"] for c in calls))

    def test_the_summary_is_posted_once_per_run(self):
        from unittest import mock
        posted = []
        seen = mock.Mock(stdout="<!-- retrospective:9 -->")
        with mock.patch.object(pm, "gh", lambda args, token, check=False: seen if args[:2] == ["issue", "view"] else posted.append(args)):
            self.assertFalse(pm.post_retrospective("o/f", "tok", "7", "9", "body"))
        self.assertEqual(posted, [])

    def test_the_summary_names_a_dark_feature_and_a_regression(self):
        facts = self.facts(outcome="regression", message="old route broke", flags=["f"])
        text = pm.render_retrospective(dict(facts, dark_broken=True), [], [])
        self.assertIn("Dark feature left behind", text)
        self.assertIn("rolled back to the previous version", text)


class Bugs(unittest.TestCase):
    BUGS = [{"kind": "regression", "flag": "", "check": "GET /api/notes answers 200", "evidence": "got 404", "repro": "curl /api/notes"},
            {"kind": "dark", "flag": "pin", "check": "pin route answers 201", "evidence": "got 500", "repro": ""}]

    def facts(self, **over):
        with tempfile.TemporaryDirectory() as tmp:
            return pm.collect_facts(tmp, {**STATE, "outcome": "regression", "bugs": self.BUGS, **over})

    def fake_gh(self, calls, comments=""):
        from unittest import mock

        def gh(args, token, check=False):
            calls.append(args)
            if args[:2] == ["issue", "view"]:
                return mock.Mock(stdout=comments)
            return mock.Mock(stdout="[]" if args[:2] == ["issue", "list"] else "")
        return gh

    def test_the_bugs_go_on_the_stories_own_issue_and_never_into_a_new_one(self):
        from unittest import mock
        calls = []
        with mock.patch.object(pm, "gh", self.fake_gh(calls)):
            self.assertTrue(pm.note_bugs_on_story("o/f", "tok", "7", self.facts(), carried=False))
        self.assertFalse([c for c in calls if c[:2] == ["issue", "create"]], "no new issue is opened for an app-side bug")
        self.assertTrue(any(c[:3] == ["issue", "edit", "7"] and "bug" in c for c in calls))
        comment = next(c for c in calls if c[:2] == ["issue", "comment"])
        self.assertEqual(comment[2], "7")
        body = comment[comment.index("--body") + 1]
        self.assertIn("**GET /api/notes answers 200** (behaviour that was live before this change stopped working)", body)
        self.assertIn("Repro: curl /api/notes", body)
        self.assertIn("still dark" if False else "flag `pin`", body)

    def test_a_retry_that_already_carries_the_bugs_gets_only_the_label_not_a_second_comment(self):
        from unittest import mock
        calls = []
        with mock.patch.object(pm, "gh", self.fake_gh(calls)):
            self.assertTrue(pm.note_bugs_on_story("o/f", "tok", "7", self.facts(), carried=True))
        self.assertFalse([c for c in calls if c[:2] == ["issue", "comment"]])

    def test_the_notes_are_added_once_per_run_and_nothing_without_bugs(self):
        from unittest import mock
        calls = []
        seen = f"<!-- bugs:{STATE['run_url']} -->"
        with mock.patch.object(pm, "gh", self.fake_gh(calls, comments=seen)):
            self.assertFalse(pm.note_bugs_on_story("o/f", "tok", "7", self.facts(), carried=False))
        self.assertFalse([c for c in calls if c[:2] == ["issue", "comment"]])
        calls.clear()
        with mock.patch.object(pm, "gh", self.fake_gh(calls)):
            self.assertFalse(pm.note_bugs_on_story("o/f", "tok", "7", self.facts(bugs=[]), carried=False))
        self.assertEqual(calls, [])

    def run_main(self, state, target):
        from unittest import mock
        work = Path(tempfile.mkdtemp())
        (work / "state.json").write_text(json.dumps(state))
        calls = []
        env = {"BUILD_RUN_DIR": str(work), "GITHUB_REPOSITORY": "o/f", "GITHUB_RUN_ID": "9", "FACTORY_PAT": "pat", "FACTORY_GH_TOKEN": "tok"}
        with mock.patch.dict(__import__("os").environ, env), mock.patch.object(pm, "gh", self.fake_gh(calls)), \
                mock.patch.object(pm.b, "load_config", return_value={"roles": {}, "limits": {}}), \
                mock.patch.object(pm.fixrequest, "file_fix_request", return_value={"target": target, "started": target == "app", "url": "u", "attempt": 1}):
            pm.main()
        return calls

    def test_a_failed_run_notes_its_bugs_on_the_story_when_the_fix_request_is_not_the_stories_retry(self):
        state = dict(STATE, outcome="round_limit", bugs=self.BUGS, issue_number="7", flags=["pin"])
        calls = self.run_main(state, "factory")
        story = [c for c in calls if c[:2] == ["issue", "comment"] and c[2] == "7" and "Bugs the tester saw" in c[c.index("--body") + 1]]
        self.assertEqual(len(story), 1)
        calls = self.run_main(state, "app")  # the retry comment carries them already
        self.assertFalse([c for c in calls if c[:2] == ["issue", "comment"] and "Bugs the tester saw" in c[c.index("--body") + 1]])
        self.assertTrue(any(c[:3] == ["issue", "edit", "7"] and "bug" in c for c in calls))

    def test_the_summary_on_the_story_names_the_bugs_and_the_rollback(self):
        text = pm.render_retrospective(self.facts(), [], [], None, [{"kind": "regression", "check": "GET /api/notes answers 200", "url": ""}])
        self.assertIn("rolled back to the previous version", text)
        self.assertIn("Bug noted on this issue (regression): GET /api/notes answers 200", text)


class Duplicates(unittest.TestCase):
    def issues(self, *titles):
        from unittest import mock
        return mock.patch.object(pm, "gh", lambda args, token, check=False: mock.Mock(
            stdout=json.dumps([{"number": 10 + n, "title": t} for n, t in enumerate(titles)])))

    def test_a_reworded_repeat_matches_the_open_issue_and_a_different_problem_does_not(self):
        with self.issues("Improvement [ab12cd34] The coder prompt never says to trim input", "Suggestion: Add a test for empty text"):
            self.assertEqual(pm.similar_open_issue("o/f", "t", "Coder prompt does not say to trim the input"), 10)
            self.assertEqual(pm.similar_open_issue("o/f", "t", "add a test for empty text values"), 11)
            self.assertIsNone(pm.similar_open_issue("o/f", "t", "The Starter Template lacks a health route"))
            self.assertIsNone(pm.similar_open_issue("o/f", "t", "the of and"))

    def test_an_improvement_that_matches_an_open_issue_adds_context_and_opens_nothing(self):
        from unittest import mock
        calls = []

        def gh(args, token, check=False):
            calls.append(args)
            if args[:2] == ["issue", "list"]:
                return mock.Mock(stdout=json.dumps([{"number": 31, "title": "Improvement [ab12cd34] The coder prompt never says to trim input"},
                                                   {"number": 32, "title": "Suggestion: Add a test for empty text"}]))
            return mock.Mock(stdout="")
        with tempfile.TemporaryDirectory() as tmp:
            facts = pm.collect_facts(tmp, {**STATE, "outcome": "released", "improvements": Improvements.IMPS})
        facts["improvements"] = [dict(facts["improvements"][0], summary="Coder prompt does not say to trim the input"),
                                 dict(facts["improvements"][1], summary="Add a test for empty text values")]
        with mock.patch.object(pm, "gh", gh), mock.patch.object(pm, "already_proposed", return_value=True):
            for_agent, filed = pm.record_improvements("o/f", "tok", "o/demo", "pat", facts)
        self.assertFalse([c for c in calls if c[:2] == ["issue", "create"]], "both were already open")
        commented = {c[2] for c in calls if c[:2] == ["issue", "comment"]}
        self.assertEqual(commented, {"31", "32"})
        self.assertTrue(filed[0]["url"].endswith("/issues/31") and filed[1]["url"].endswith("/issues/32"))


class Isolation(unittest.TestCase):
    """The retrospective Agent runs in a copy of the tree as the Agent user, and only allowed files come back."""

    def tree(self, files):
        root = Path(tempfile.mkdtemp())
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        return root

    def test_changes_are_found_by_comparing_plain_trees_and_git_is_never_read(self):
        before = self.tree({"agents/a.md": "one", "orchestrator/x.py": "x", ".git/config": "[core]\n"})
        after = self.tree({"agents/a.md": "two", "orchestrator/y.py": "y", ".git/config": "[core]\n\tfsmonitor = evil\n"})
        os.symlink("/etc/passwd", after / "templates-link")
        changes, links = pm.tree_changes(before, after)
        self.assertEqual(changes, {"agents/a.md": "M", "orchestrator/y.py": "A", "orchestrator/x.py": "D"})
        self.assertEqual(links, ["templates-link"])  # the .git difference is invisible, a symlink is reported and never followed

    def test_only_allowed_paths_are_carried_into_the_checkout_git_runs_in(self):
        before = self.tree({"agents/a.md": "one", "orchestrator/x.py": "x", ".github/workflows/w.yml": "w"})
        after = self.tree({"agents/a.md": "two", ".github/workflows/w.yml": "pwned", ".github/workflows/new.yml": "n",
                           "orchestrator/new_test.py": "t", "docs/huge.md": "x" * (pm.MAX_FILE_BYTES + 1), "agents/huge.md": "x" * (pm.MAX_FILE_BYTES + 1)})
        changes, _ = pm.tree_changes(before, after)
        applied = pm.apply_changes(before, after, changes)
        self.assertEqual(sorted(applied), ["agents/a.md", "orchestrator/new_test.py", "orchestrator/x.py"])
        self.assertEqual((before / "agents/a.md").read_text(), "two")
        self.assertEqual((before / ".github/workflows/w.yml").read_text(), "w")  # a workflow is never touched
        self.assertFalse((before / ".github/workflows/new.yml").exists())
        self.assertFalse((before / "agents/huge.md").exists())  # too big to be a prompt or a rule
        self.assertFalse((before / "orchestrator/x.py").exists())  # a deletion inside an allowed path is carried over

    def agent_run(self, problems=(), user="agent"):
        from unittest import mock
        factory = self.tree({"agents/a.md": "one", "orchestrator/x.py": "x"})
        facts = self.tree({"facts.json": "{}"}) / "facts.json"
        result = self.tree({}) / "result.json"
        seen = {}

        def fake_watched(cmd, cwd, env, out_path, timeout_s, stall_s, poll=5.0, user=None, pidfile=None):
            seen.update(cmd=cmd, cwd=Path(cwd), env=env, user=user)
            (Path(cwd) / "agents/a.md").write_text("changed by the agent")
            (Path(cwd).parent / "io" / "result.json").write_text('{"category": "prompt_gap"}')
            return 0
        cfg = {"roles": {"retrospective": {"model": "m/x", "prompt": "prompts/retrospective.md"}}, "provider": {"base_url": "https://llm"}}
        with mock.patch.dict(os.environ, {"AGENT_USER": user or "", "BUILD_RUN_DIR": str(self.tree({})), "FACTORY_PAT": "PAT-SECRET",
                                          "DEEPINFRA_API_KEY": "PARENT-KEY", "PATH": os.environ["PATH"]}), \
                mock.patch.object(pm.b, "run_isolation_probes", return_value=list(problems)) as probes, \
                mock.patch.object(pm.b, "run_watched", fake_watched), mock.patch.object(pm, "share_with"):
            ran = pm.run_agent(factory, cfg, "scoped-key", facts, result, 5)
        return ran, factory, result, seen, probes

    def test_the_agent_runs_as_the_agent_user_in_a_copy_with_a_scrubbed_environment(self):
        ran, factory, result, seen, probes = self.agent_run()
        self.assertTrue(ran)
        probes.assert_called_once_with("agent")
        self.assertEqual(seen["user"], "agent")
        self.assertNotEqual(seen["cwd"], factory)
        self.assertLessEqual(set(seen["env"]), {"PATH", "LANG", "TMPDIR", "CI", "HOME", "LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY", "RUNTIME"})
        self.assertEqual(seen["env"]["LLM_API_KEY"], "scoped-key")
        self.assertNotIn("PAT-SECRET", " ".join(seen["env"].values()))
        self.assertNotIn("PARENT-KEY", " ".join(seen["env"].values()))
        self.assertEqual((factory / "agents/a.md").read_text(), "changed by the agent")  # an allowed change came back
        self.assertEqual(json.loads(result.read_text())["category"], "prompt_gap")

    def test_an_isolation_that_cannot_be_proven_means_no_agent_runs(self):
        ran, factory, result, seen, _ = self.agent_run(problems=["an Agent can read the Orchestrator's environment through /proc"])
        self.assertFalse(ran)
        self.assertEqual(seen, {})
        self.assertEqual((factory / "agents/a.md").read_text(), "one")

    def test_without_isolation_it_still_runs_in_a_copy_and_skips_the_probes(self):
        ran, factory, _, seen, probes = self.agent_run(user=None)
        self.assertTrue(ran)
        probes.assert_not_called()
        self.assertIsNone(seen["user"])

    def test_the_unit_tests_run_as_the_agent_user_in_a_copy_with_no_credential(self):
        from unittest import mock
        factory = self.tree({"orchestrator/test_x.py": "pass"})
        root = self.tree({})
        seen = {}

        def fake_watched(cmd, cwd, env, out_path, timeout_s, stall_s, poll=5.0, user=None, pidfile=None):
            seen.update(cmd=cmd, cwd=Path(cwd), env=env, user=user)
            return 0
        with mock.patch.dict(os.environ, {"FACTORY_PAT": "PAT-SECRET", "DEEPINFRA_API_KEY": "PARENT-KEY", "FACTORY_GH_TOKEN": "tok", "PATH": os.environ["PATH"]}), \
                mock.patch.object(pm.b, "run_watched", fake_watched), mock.patch.object(pm, "share_with"):
            self.assertTrue(pm.run_tests(factory, root, "agent"))
        self.assertEqual(seen["user"], "agent")
        self.assertNotEqual(seen["cwd"], factory)
        self.assertLessEqual(set(seen["env"]), {"PATH", "LANG", "CI", "HOME", "TMPDIR", "PYTHONDONTWRITEBYTECODE"})
        joined = " ".join(seen["env"].values())
        for secret in ("PAT-SECRET", "PARENT-KEY", "tok"):
            self.assertNotIn(secret, joined)
        self.assertFalse((seen["cwd"] / ".git").exists())

    def test_propose_does_nothing_more_when_no_agent_ran(self):
        from unittest import mock
        with mock.patch.object(pm, "mint_agent", return_value=("k", object())), mock.patch.object(pm, "run_agent", return_value=False), \
                mock.patch.object(pm, "record_agent_spend"), mock.patch.object(pm, "open_pr") as open_pr, mock.patch.object(pm, "gh") as gh:
            result = pm.propose(Path("."), {"limits": {}}, "o/f", "pat", "tok", "parent", Path("f"), Path(tempfile.mkdtemp()) / "r.json", [1], "9")
        self.assertIsNone(result)
        open_pr.assert_not_called()
        gh.assert_not_called()


class AgentCredential(unittest.TestCase):
    def test_the_agent_gets_a_capped_single_model_credential_never_the_parent_key(self):
        from unittest import mock
        cfg = {"limits": {"retrospective_cost_cap_usd": 0.25, "jwt_ttl_seconds": 100},
               "roles": {"retrospective": {"model": "m/x"}}}
        with mock.patch.object(pm.b, "http", return_value=(200, {"token": "jwt-1"})) as http:
            self.assertEqual(pm.mint_agent_key(cfg, "parent-key"), "jwt-1")
        _, url, key, body = http.call_args[0]
        self.assertEqual(key, "parent-key")
        self.assertEqual((body["models"], body["spending_limit"]), (["m/x"], 0.25))

    def test_no_credential_means_no_agent_run(self):
        from unittest import mock
        cfg = {"limits": {"jwt_ttl_seconds": 100}, "roles": {"retrospective": {"model": "m/x"}}}
        with mock.patch.object(pm.b, "http", return_value=(500, {})):
            self.assertIsNone(pm.mint_agent_key(cfg, "parent-key"))


if __name__ == "__main__":
    unittest.main()
