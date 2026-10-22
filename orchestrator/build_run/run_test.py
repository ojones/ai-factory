import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import rollback, run_stops  # noqa: E402

from build_run import endings, review_code, track_progress, verify_deployed_app  # noqa: E402
from build_run.run import BuildRun  # noqa: E402


def finding(**over):
    return {"severity": "blocking", "category": "correctness", "evidence_kind": "cited", "summary": "x", "evidence": "e",
            "file": "backend/src/a.ts", "line": "3", "requirement": "", "suggested_fix": "", "repro": "", **over}


class RoundLoop(unittest.TestCase):

    def bare_run(self):
        run = object.__new__(BuildRun)
        run.app, run.build_kind, run.plan_meta = "demo", "update", None
        run.task, run.retiring, run.fix_for = "do it", (), None
        run.lim = {"review_rounds": 3, "stuck_rounds": 0}
        run.work = Path(__import__("tempfile").mkdtemp(prefix="loop-test-"))
        run.art = run.work
        run.state = track_progress.State(run.work / "state.json", "demo", "1", "url")
        run.state.d["base_sha"] = "base"
        run.calls, run.heads = [], iter(["c1", "c2", "c3", "c4"])
        run.setup = lambda: None
        run.coder = lambda label, task, path: (run.calls.append(f"coder{label}"), next(run.heads))[1]
        return run

    def stub_review_and_push(self, run, reviews):
        def review(base, head, rnd):
            run.calls.append(f"review {head}")
            return next(reviews)
        run.review_before_push = review
        run.run_flags = lambda base, head: ["f"]
        run.push = lambda head: (run.calls.append(f"push {head}"), run.state.d["commits"].append(head))

    def stub_pipeline_and_tests(self, run, tests, pipeline_fix):
        fixes = iter([pipeline_fix])

        def pipeline(sha):
            run.calls.append(f"pipeline {sha}")
            if next(fixes, False):
                run.last = "fix1"
                raise endings.PipelineFix("fix1")
            return sha
        run.pipeline = pipeline

        def test(base, head, rnd, flags):
            run.calls.append(f"test {head}")
            return next(tests)
        run.test_deployed = test

    def stub_release(self, run):
        run.head = lambda: run.last
        run.record_round = lambda *a: None
        run.release = lambda flags, head: run.calls.append("release")
        run.ungated_flags = lambda head, flags: run.ungated
        run.ungated = []
        run.link_flags_to_issue = lambda flags: None
        run.watch_release = lambda: None
        run.archive_retired_flags = lambda base, head: None
        run.check_limits = lambda: None
        run.cap = 1.0

    def make(self, reviews, tests, pipeline_fix=False):
        run = self.bare_run()
        self.stub_review_and_push(run, iter(reviews))
        self.stub_pipeline_and_tests(run, iter(tests), pipeline_fix)
        self.stub_release(run)
        return run

    def go(self, run):
        orig = run.coder
        run.coder = lambda *a: setattr(run, "last", orig(*a)) or run.last
        run.last = None
        run.run()

    CLEAN, BLOCKED = (True, [], []), (False, [{"summary": "bad", "evidence": "e"}], [])
    PASSED, FAILED_NEW = (True, [], "ok"), (False, [{"flag": "f", "check": "new", "status": "failed", "scope": "new"}], "dark_only")

    def test_a_second_failed_deployed_test_stops_the_run_before_a_third_round(self):
        run = self.make([self.CLEAN, self.CLEAN, self.CLEAN], [self.FAILED_NEW, self.FAILED_NEW, self.PASSED])
        run.lim["test_rounds"] = 2
        self.go(run)
        self.assertEqual(run.state.d["outcome"], "round_limit")
        self.assertEqual(run.calls.count("coder2"), 1)
        self.assertNotIn("coder3", run.calls)

    def test_blocked_reviews_do_not_use_up_the_test_rounds(self):
        run = self.make([self.BLOCKED, self.BLOCKED, self.CLEAN], [self.PASSED])
        run.lim["test_rounds"] = 1
        self.go(run)
        self.assertEqual(run.state.d["outcome"], "released")

    def test_a_clean_review_pushes_then_the_tester_runs_then_it_releases(self):
        run = self.make([self.CLEAN], [self.PASSED])
        self.go(run)
        self.assertEqual(run.calls, ["coder1", "review c1", "push c1", "pipeline c1", "test c1", "release"])
        self.assertEqual(run.state.d["outcome"], "released")

    def test_a_blocked_review_sends_the_code_back_to_the_coder_and_nothing_is_pushed(self):
        run = self.make([self.BLOCKED, self.CLEAN], [self.PASSED])
        self.go(run)
        self.assertEqual(run.calls[:4], ["coder1", "review c1", "coder2", "review c2"])
        self.assertNotIn("push c1", run.calls, msg="the blocked commit never reached main")
        self.assertEqual(run.state.d["commits"], ["c2"])
        self.assertEqual(run.state.d["outcome"], "released")

    def test_a_failure_in_a_change_that_went_live_without_a_gate_is_a_regression_and_is_rolled_back(self):
        run = self.make([(True, [], [])], [(False, [{"flag": "f", "check": "c", "status": "failed", "scope": "new"}], "dark_only")])
        run.ungated = ["f"]
        self.go(run)
        self.assertEqual(run.state.d["outcome"], "regression")
        self.assertIn("rolled back", run.state.d["message"])
        self.assertEqual(run.state.d["flag_notes"][0]["kind"], "live_and_failing")
        self.assertNotIn("release", run.calls)

    def test_a_failure_in_a_change_with_no_flag_at_all_is_a_regression_and_is_rolled_back(self):
        run = self.make([(True, [], [])], [(False, [{"check": "c", "status": "failed", "scope": "new"}], "dark_only")])
        run.run_flags = lambda base, head: []
        self.go(run)
        self.assertEqual(run.state.d["outcome"], "regression")
        self.assertIn("rolled back", run.state.d["message"])
        self.assertNotIn("release", run.calls)

    def test_a_clean_change_whose_flag_is_missing_and_unread_ends_without_a_release_and_with_a_note(self):
        run = self.make([(True, [], [])], [(True, [], "ok")])
        run.release = lambda flags, head: run.state.d.update(release={"released": [], "kept": []}, flag_message="went live on deploy without a gate")
        self.go(run)
        self.assertEqual((run.state.d["outcome"], run.state.d["message"]), ("nothing_to_release", "went live on deploy without a gate"))

    def test_a_dark_flag_that_does_not_exist_is_a_failure_and_nothing_is_rolled_back(self):
        run = self.make([(True, [], [])], [(True, [], "ok")])

        def release(flags, head):
            raise run_stops.FlagMissing("Not released: `f` is declared and read but does not exist")
        run.release = release
        self.go(run)
        self.assertEqual(run.state.d["outcome"], "flag_missing")
        self.assertFalse(rollback.rollback_decision(run.state.d)[0])

    def test_a_dark_failure_is_fixed_forward_in_the_next_round(self):
        run = self.make([self.CLEAN, self.CLEAN], [self.FAILED_NEW, self.PASSED])
        self.go(run)
        self.assertEqual(run.calls, ["coder1", "review c1", "push c1", "pipeline c1", "test c1", "coder2",
                                     "review c2", "push c2", "pipeline c2", "test c2", "release"])
        self.assertEqual(run.state.d["outcome"], "released")

    UNVERIFIED_BLOCKED = (False, [{"flag": "f", "check": "send mail", "status": "blocked", "scope": "new", "evidence": "app unreachable"}], "dark_only")
    UNVERIFIED_NOT_RUN = (False, [{"flag": "f", "check": "coverage", "status": "not_run", "scope": "new", "evidence": "no result"}], "dark_only")

    def test_checks_that_could_not_be_run_are_retested_not_sent_to_the_coder(self):
        run = self.make([self.CLEAN], [self.UNVERIFIED_BLOCKED, self.PASSED])
        self.go(run)
        self.assertEqual(run.calls, ["coder1", "review c1", "push c1", "pipeline c1", "test c1", "test c1", "release"])
        self.assertEqual(run.state.d["outcome"], "released")

    def test_checks_that_still_cannot_be_verified_stop_the_run_for_a_person_with_no_coder_round(self):
        run = self.make([self.CLEAN], [self.UNVERIFIED_BLOCKED, self.UNVERIFIED_NOT_RUN])
        self.go(run)
        self.assertEqual(run.state.d["outcome"], "needs_human")
        self.assertIn("could not be verified", run.state.d["message"])
        self.assertIn("coverage", run.state.d["message"])
        self.assertEqual(run.calls.count("coder2"), 0)
        self.assertNotIn("release", run.calls)

    def test_with_retests_switched_off_the_first_unverified_pass_stops_the_run(self):
        run = self.make([self.CLEAN], [self.UNVERIFIED_BLOCKED])
        run.lim["test_retries"] = 0
        self.go(run)
        self.assertEqual(run.state.d["outcome"], "needs_human")
        self.assertEqual(run.calls.count("test c1"), 1)

    def test_only_the_failed_checks_reach_the_coder_when_some_failed_and_some_were_blocked(self):
        failed = {"flag": "f", "check": "new route answers 201", "status": "failed", "scope": "new", "evidence": "got 500"}
        run = self.make([self.CLEAN, self.CLEAN], [(False, [failed, self.UNVERIFIED_BLOCKED[1][0]], "dark_only"), self.PASSED])
        tasks = []
        orig = run.coder
        run.coder = lambda label, task, path: (tasks.append(task), orig(label, task, path))[1]
        self.go(run)
        fix_list = next(t for t in tasks if "fix list" in t)
        self.assertIn("new route answers 201", fix_list)
        self.assertNotIn("send mail", fix_list)

    def test_a_regression_ends_the_run_at_once_so_finalize_can_roll_the_deploy_back(self):
        broken = {"flag": "", "check": "GET /api/notes", "status": "failed", "scope": "existing", "api": ["a"]}
        run = self.make([self.CLEAN], [(False, [broken], "regression")])
        self.go(run)
        self.assertEqual(run.state.d["outcome"], "regression")
        self.assertNotIn("release", run.calls)
        self.assertEqual(run.calls.count("coder2"), 0, msg="no more rounds on top of a regression")

    def test_a_fix_the_pipeline_needed_is_reviewed_before_it_is_pushed(self):
        run = self.make([self.CLEAN, self.CLEAN], [self.PASSED], pipeline_fix=True)
        self.go(run)
        self.assertEqual(run.calls[:7], ["coder1", "review c1", "push c1", "pipeline c1", "review fix1", "push fix1", "pipeline fix1"])
        self.assertEqual(run.state.d["outcome"], "released")

    def test_rounds_that_never_pass_review_end_at_the_round_limit_with_nothing_pushed(self):
        run = self.make([self.BLOCKED] * 3, [])
        self.go(run)
        self.assertEqual(run.state.d["outcome"], "round_limit")
        self.assertEqual(run.state.d["commits"], [])


class ReviewBeforePushThenTest(unittest.TestCase):

    def make(self, head_flags, agent):
        run = object.__new__(BuildRun)
        run.app, run.preview = "demo", "tok"
        run.cfg = {"roles": {"reviewer": {"mode": "agent"}}}
        run.lim = {}
        run.work = Path(__import__("tempfile").mkdtemp(prefix="work-test-"))
        run.state = track_progress.State(run.work / "state.json", "demo", "1", "url")
        run.state.save = lambda: None
        shown = {"base": "[]", "head": head_flags}

        class R:
            def __init__(self, out): self.stdout, self.returncode = out, 0

        def git(*args, check=True, cwd=None):
            if args[0] == "show":
                return R(shown["base" if args[1].startswith("base") else "head"])
            return R("")
        run.git, run.restore_tree, run.agent_json = git, lambda cwd=None: None, agent
        return run

    CLEAN = {"analysis": "x", "findings": [], "improvements": [], "verdict": "clean"}
    PASS = {"passed": True, "results": [{"flag": "f", "check": "c", "passed": True, "evidence": "e"}]}
    FLAGS = '[{"slug": "f", "description": "d"}]'

    def test_the_reviewer_runs_alone_and_before_anything_is_pushed(self):
        roles = []

        def agent(role, label, values, path, *a, **k):
            roles.append(role)
            return self.CLEAN, 0.1, None

        run = self.make(self.FLAGS, agent)
        clean, blocking, minor = run.review_before_push("base1", "head1", 1)
        self.assertEqual((clean, blocking), (True, []))
        self.assertEqual({m["source"] for m in minor}, {"orchestrator"}, msg="the flag in this change has no use and no issue reference")
        self.assertEqual(roles, ["reviewer"], msg="no tester, no deploy: nothing is live yet")
        self.assertEqual(run.run_flags("base1", "head1"), ["f"])
        self.assertEqual([x["stage"] for x in run.state.d["stages"]], ["Review"])

    def test_a_blocking_finding_is_returned_so_the_coder_can_fix_it_before_the_push(self):
        doc = dict(self.CLEAN, verdict="clean", findings=[finding(summary="injection", category="security")])
        run = self.make(self.FLAGS, lambda *a, **k: (doc, 0.1, None))
        clean, blocking, _ = run.review_before_push("base1", "head1", 1)
        self.assertFalse(clean)
        self.assertEqual(len(blocking), 1)

    def test_mechanical_flag_findings_come_from_the_orchestrator_and_are_always_minor(self):
        shown = {"flags.json": json.dumps([{"slug": "used", "description": "o/r#4: used"}, {"slug": "idle", "description": "o/r#5: never read"},
                                           {"slug": "bare", "description": "no reference"}, {"slug": "old", "description": "x"}])}

        def git(*args):
            if args[0] == "show":
                return shown[args[1].split(":", 1)[1]]
            hits = {'"used"': "head:backend/src/routes/n.ts:9:  if (isFeatureEnabled(res, 'used'))", '"bare"': "head:backend/src/n.ts:2:x('bare')\nhead:backend/src/n.test.ts:4:'bare'"}
            return "\n".join(v for k, v in hits.items() if k in args)
        found = review_code.flag_findings(git, "head", ["used", "idle", "bare", "gone"])
        self.assertEqual([(f["summary"].split("`")[1], "no code outside the tests" in f["summary"]) for f in found],
                         [("idle", True), ("bare", False)])
        self.assertTrue(all(f["severity"] == "minor" and f["category"] == "flag_misuse" and f["source"] == "orchestrator" for f in found))
        self.assertEqual(review_code.flag_findings(lambda *a: "not json", "head", ["used"]), [], msg="an unreadable manifest is not a finding")

    def test_a_flag_read_only_by_a_test_counts_as_unused(self):
        git = lambda *a: json.dumps([{"slug": "t", "description": "o/r#1: x"}]) if a[0] == "show" else "head:backend/src/x.test.ts:3:'t'"
        self.assertIn("no code outside the tests", review_code.flag_findings(git, "head", ["t"])[0]["summary"])

    def test_the_tester_runs_after_the_push_and_says_what_a_failure_means(self):
        run = self.make(self.FLAGS, lambda role, *a, **k: (self.PASS, 0.1, None))
        self.assertEqual(run.test_deployed("base1", "head1", 1, ["f"])[::2], (True, "ok"))
        self.assertEqual([x["stage"] for x in run.state.d["stages"]], ["Test"])

    def test_with_no_flags_the_tester_still_runs_against_the_intake(self):
        seen = []

        def agent(role, label, values, path, *a, **k):
            seen.append(role)
            return {"passed": True, "results": [{"flag": "", "check": "requirement 1", "passed": True, "evidence": "e"}]}, 0.1, None

        run = self.make("[]", agent)
        passed, failures, impact = run.test_deployed("base1", "head1", 1, run.run_flags("base1", "head1"))
        self.assertEqual((seen, passed, failures, impact), (["tester"], True, [], "ok"))

    def test_a_failure_of_the_new_change_is_dark_only_and_one_of_released_behaviour_is_a_regression(self):
        broken_new = {"flag": "f", "check": "new route", "status": "failed", "evidence": "e", "scope": "new", "api": ["a1"]}
        broken_old = {"flag": "", "check": "GET /api/notes", "status": "failed", "evidence": "e", "scope": "existing", "api": ["a2"]}
        self.assertEqual(verify_deployed_app.test_impact([]), "ok")
        self.assertEqual(verify_deployed_app.test_impact([broken_new]), "dark_only")
        self.assertEqual(verify_deployed_app.test_impact([broken_new, broken_old]), "regression")
        self.assertEqual(verify_deployed_app.test_impact([dict(broken_old, api=[])]), "dark_only")
        self.assertEqual(verify_deployed_app.test_impact([dict(broken_old, status="blocked")]), "dark_only")
        self.assertEqual(verify_deployed_app.test_impact([dict(broken_old, status="not_run")]), "dark_only")

    def test_a_failing_tester_with_nothing_seen_to_fail_raises_for_a_person(self):
        def agent(role, *a, **k):
            raise run_stops.NeedsHuman("other", "the tester produced no valid output file twice")

        run = self.make(self.FLAGS, agent)
        with self.assertRaises(run_stops.NeedsHuman):
            run.test_deployed("base1", "head1", 1, ["f"])

    def test_improvements_are_kept_deduplicated_and_only_the_known_kinds(self):
        doc = dict(self.CLEAN, improvements=[
            {"target": "factory", "summary": "The prompt never says  to trim input", "evidence": "e"},
            {"target": "factory", "summary": "the prompt never says to trim input", "evidence": "again"},
            {"target": "managed_app", "summary": "Add a test for empty text", "evidence": ""},
            {"target": "nobody", "summary": "ignored"}, {"target": "factory", "summary": "  "}, "junk"])
        run = self.make(self.FLAGS, lambda *a, **k: (doc, 0.1, None))
        run.review_before_push("base1", "head1", 1)
        run.note_improvements(doc, "reviewer")
        kept = run.state.d["improvements"]
        self.assertEqual([(i["source"], i["target"]) for i in kept], [("reviewer", "factory"), ("reviewer", "managed_app")])


if __name__ == "__main__":
    unittest.main()
