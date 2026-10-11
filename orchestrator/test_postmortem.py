import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import postmortem as pm  # noqa: E402


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


class AgentCredential(unittest.TestCase):
    def test_the_agent_gets_a_capped_single_model_credential_never_the_parent_key(self):
        from unittest import mock
        cfg = {"limits": {"postmortem_cost_cap_usd": 0.25, "jwt_ttl_seconds": 100},
               "roles": {"postmortem": {"model": "m/x"}}}
        with mock.patch.object(pm.b, "http", return_value=(200, {"token": "jwt-1"})) as http:
            self.assertEqual(pm.mint_agent_key(cfg, "parent-key"), "jwt-1")
        _, url, key, body = http.call_args[0]
        self.assertEqual(key, "parent-key")
        self.assertEqual((body["models"], body["spending_limit"]), (["m/x"], 0.25))

    def test_no_credential_means_no_agent_run(self):
        from unittest import mock
        cfg = {"limits": {"jwt_ttl_seconds": 100}, "roles": {"postmortem": {"model": "m/x"}}}
        with mock.patch.object(pm.b, "http", return_value=(500, {})):
            self.assertIsNone(pm.mint_agent_key(cfg, "parent-key"))


if __name__ == "__main__":
    unittest.main()
