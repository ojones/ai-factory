import json
import unittest

import yaml
from shared import api_check, config  # noqa: E402

from monitoring import benchmark as bm

ROOT = config.FACTORY_DIR


def report(outcome="released", cost=0.2, rounds=1, start="2026-10-14T10:00:00", end="2026-10-14T10:20:00"):
    return {"outcome": outcome, "spent_usd": cost, "review_passes": rounds, "started_at": start, "finished_at": end}


def task(tid="t", tags=(), outcomes=("released",), **expected):
    return {"id": tid, "tags": list(tags), "expected": {"outcomes": list(outcomes), **expected}, "oracle": {"checks": []}}


class Candidate(unittest.TestCase):
    def test_pairs_are_parsed_and_bad_ones_refused(self):
        self.assertEqual(bm.parse_candidate("coder=deepseek-ai/New-1, tester=nvidia/X:2"), {"coder": "deepseek-ai/New-1", "tester": "nvidia/X:2"})
        self.assertEqual(bm.parse_candidate(""), {})
        for bad in ("coder", "king=a/b", "coder=a b", "coder="):
            with self.assertRaises(ValueError):
                bm.parse_candidate(bad)

    def test_the_candidate_profile_switches_the_model_and_pins_the_limits_that_keep_passes_comparable(self):
        text = (ROOT / "agents" / "profiles.yml").read_text()
        doc = yaml.safe_load(bm.candidate_profile(text, {"coder": "deepseek-ai/New-1"}))
        self.assertEqual(doc["roles"]["coder"]["model"], "deepseek-ai/New-1")
        self.assertEqual(doc["roles"]["tester"]["model"], yaml.safe_load(text)["roles"]["tester"]["model"], msg="untouched")
        self.assertEqual(doc["limits"]["flag_retirement"]["piggyback_max"], 0, msg="a ride-along retirement would make passes incomparable")
        self.assertEqual(doc["limits"]["daily_cost_cap_usd"], 0)
        with self.assertRaises(ValueError):
            bm.candidate_profile(text, {"nonrole": "a/b"})


class Suite(unittest.TestCase):
    def test_the_shipped_suite_is_valid_and_its_oracles_are_real_api_checks(self):
        suite = json.loads((ROOT / "agents" / "benchmark" / "suite.json").read_text())
        self.assertEqual(bm.validate_suite(suite), [])
        for t in suite["tasks"]:
            checks = t.get("setup", []) + t["oracle"]["checks"]
            if checks:
                self.assertIsNone(api_check.validate(checks)[1], t["id"])
        self.assertTrue({"refusal"} & {tag for t in suite["tasks"] for tag in t["tags"]}, msg="refusals are part of the suite")
        json.loads((ROOT / "agents" / "benchmark" / "rules.json").read_text())

    def test_problems_are_found(self):
        self.assertTrue(bm.validate_suite({"tasks": []}))
        bad = {"tasks": [{"id": "a", "request": "x", "expected": {"outcomes": []}, "oracle": {"checks": []}}, {"id": "a", "request": ""}]}
        self.assertGreaterEqual(len(bm.validate_suite(bad)), 2)

    def test_a_frozen_suite_whose_task_names_the_seed_flag_must_have_one(self):
        suite = {"app": "b", "base_sha": "abc", "tasks": [{"id": "r", "request": "retire-flag: {seed_flag}", "expected": {"outcomes": ["released"]}, "oracle": {"checks": []}}]}
        self.assertTrue(any("seed_flag" in x for x in bm.validate_suite(suite)))
        self.assertEqual(bm.validate_suite(dict(suite, seed_flag="issue-142")), [])
        self.assertEqual(bm.validate_suite(dict(suite, base_sha="")), [], msg="before the bench app is frozen there is nothing to check")

    def test_pass_ids_make_flag_names_unique_and_task_selection_checks_names(self):
        self.assertEqual(bm.fill_request("flag `v-{pass}`", "10141200"), "flag `v-10141200`")
        suite = {"tasks": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}
        self.assertEqual([t["id"] for t in bm.select_tasks(suite, "c,a")], ["a", "c"])
        with self.assertRaises(ValueError):
            bm.select_tasks(suite, "zzz")


class Scoring(unittest.TestCase):
    def test_a_task_passes_only_with_an_expected_outcome_a_cost_inside_its_limit_and_every_oracle_check(self):
        t = task(outcomes=("released",), max_cost=0.5)
        self.assertTrue(bm.score_task(t, report(), [{"id": "a", "ok": True}])["passed"])
        self.assertFalse(bm.score_task(t, report(outcome="needs_human"), [])["passed"])
        self.assertFalse(bm.score_task(t, report(cost=0.9), [])["passed"])
        failed = bm.score_task(t, report(), [{"id": "a", "ok": True}, {"id": "b", "ok": False}])
        self.assertEqual((failed["passed"], failed["oracle_failed"]), (False, ["b"]))
        self.assertFalse(bm.score_task(t, None, [])["passed"], msg="no report at all")

    def test_minutes_come_from_the_timestamps(self):
        self.assertEqual(bm.score_task(task(), report(), [])["minutes"], 20.0)
        self.assertIsNone(bm.minutes_between(None, "x"))


def agg(passed, cost, minutes, rounds, by_task=None, tasks=7):
    return {"tasks": tasks, "passed": passed, "cost_usd": cost, "minutes": minutes, "rounds_mean": rounds, "failed": [], "by_task": by_task or {}}


class Comparison(unittest.TestCase):
    base = agg(6, 2.0, 120, 1.5, {"refuse-secret": {"passed": True, "tags": ["refusal"], "outcome": "refused"}, "flagged-route": {"passed": True, "tags": ["core"], "outcome": "released"}})

    def test_a_cheaper_faster_model_with_the_same_quality_is_accepted_as_an_improvement(self):
        v = bm.compare(agg(6, 1.2, 70, 1.4), self.base)
        self.assertTrue(v["accept"] and v["improvement"])
        self.assertEqual(v["deltas"]["cost_ratio"], 0.6)

    def test_losing_more_than_one_task_or_costing_much_more_or_needing_more_rounds_is_rejected(self):
        self.assertFalse(bm.compare(agg(4, 1.0, 60, 1.5), self.base)["accept"])
        self.assertFalse(bm.compare(agg(6, 3.0, 100, 1.5), self.base)["accept"])
        self.assertFalse(bm.compare(agg(6, 2.0, 100, 2.5), self.base)["accept"])
        self.assertTrue(bm.compare(agg(5, 2.0, 120, 1.5), self.base)["accept"], msg="one task fewer is allowed, and not an improvement")
        self.assertFalse(bm.compare(agg(5, 2.0, 120, 1.5), self.base)["improvement"])

    def test_a_safety_task_that_regresses_rejects_the_candidate_whatever_else_it_saves(self):
        now = agg(6, 0.5, 30, 1.0, {"refuse-secret": {"passed": False, "tags": ["refusal"], "outcome": "released"}, "flagged-route": {"passed": True, "tags": ["core"]}})
        v = bm.compare(now, self.base)
        self.assertFalse(v["accept"])
        self.assertTrue(any("refuse-secret" in r for r in v["reasons"]))

    def test_the_report_names_the_verdict_and_every_task(self):
        scores = [bm.score_task(task("a"), report(), []), bm.score_task(task("b", outcomes=("refused",)), report(), [])]
        a = bm.aggregate(scores)
        text = bm.render_report("new-coder", {"coder": "x/y"}, a, bm.compare(a, a))
        for needle in ("coder=x/y", "ACCEPT", "| a |", "| b |", "NO"):
            self.assertIn(needle, text)
        self.assertEqual(a["failed"], ["b"])

    def test_the_estimate_prices_refusals_as_nearly_free(self):
        est = bm.estimate([task("a"), task("r", tags=["refusal"])])
        self.assertEqual((est["runs"], est["refusals"]), (1, 1))


class Planned(unittest.TestCase):
    def test_planning_ends_planned_when_it_filed_children_else_as_the_ending_it_commented(self):
        self.assertEqual(bm.planning_ending([], [{"number": 5}]), "planned")
        self.assertEqual(bm.planning_ending(["**Planning stopped (refused):** payments", "other"], []), "refused")
        self.assertEqual(bm.planning_ending(["**Planning stopped (needs human):** a question"], []), "needs_human")
        self.assertEqual(bm.planning_ending(["**Planning stopped (awaiting secret):** x"], []), "awaiting_secret")
        self.assertIsNone(bm.planning_ending(["unrelated"], []))
        self.assertEqual(bm.planning_ending(["**Planning stopped (needs human):** old", "**Planning stopped (refused):** new"], []), "refused", msg="the last word")

    def test_children_run_after_what_blocks_them_and_otherwise_by_number(self):
        self.assertEqual(bm.child_order([{"number": 12, "blockers": [11]}, {"number": 11, "blockers": []}, {"number": 13, "blockers": [12]}]), [11, 12, 13])
        self.assertEqual(bm.child_order([{"number": 9, "blockers": [99]}, {"number": 8}]), [8, 9], msg="a blocker outside the plan is ignored")
        with self.assertRaises(ValueError):
            bm.child_order([{"number": 1, "blockers": [2]}, {"number": 2, "blockers": [1]}])

    def test_the_planners_cost_is_read_from_the_ledger_by_its_run_id(self):
        lines = ["ledger 2026-10-20 factory-bench 0.0482 run:111-plan", "ledger 2026-10-20 factory-bench 0.1306 run:222", "ledger 2026-10-20 factory-bench 0.0900 run:333-plan"]
        self.assertEqual(bm.ledger_cost(lines, 111), 0.0482)
        self.assertEqual(bm.ledger_cost(lines, 222), 0.0)
        self.assertEqual(bm.ledger_cost(lines, 1), 0.0)

    def test_a_task_that_ends_at_planning_scores_on_the_planning_ending_and_its_cost(self):
        refusal = task("refuse-payments", outcomes=("refused",), tags=("refusal",), max_cost=0.25)
        ok = bm.score_task(refusal, bm.planning_report("refused", 0.06), [])
        self.assertTrue(ok["passed"])
        self.assertFalse(bm.score_task(refusal, bm.planning_report("refused", 0.5), [])["passed"], msg="over its cost limit")
        self.assertFalse(bm.score_task(refusal, bm.planning_report("needs_human", 0.06), [])["passed"], msg="the wrong ending")

    def test_a_plan_with_several_children_is_one_report_with_everything_added_up(self):
        a = {"outcome": "released", "spent_usd": 0.1, "review_passes": 1, "started_at": "2026-10-20T10:00:00", "finished_at": "2026-10-20T10:20:00"}
        b = {"outcome": "released", "spent_usd": 0.2, "review_passes": 2, "started_at": "2026-10-20T10:21:00", "finished_at": "2026-10-20T10:50:00"}
        got = bm.merge_reports(0.05, [a, b])
        self.assertEqual((got["outcome"], got["spent_usd"], got["review_passes"], got["started_at"], got["finished_at"]),
                         ("released", 0.35, 3, "2026-10-20T10:00:00", "2026-10-20T10:50:00"))
        stuck = bm.merge_reports(0.05, [a, dict(b, outcome="round_limit")])
        self.assertEqual(stuck["outcome"], "round_limit", msg="the first ending that is not good")
        self.assertIsNone(bm.merge_reports(0.05, [None]), msg="nothing ran")

    def test_the_run_started_by_the_dispatch_is_the_first_one_newer_than_what_was_there_before(self):
        runs = [{"databaseId": 30}, {"databaseId": 20}, {"databaseId": 10}]
        self.assertEqual(bm.newest_run_after(runs, 20), 30)
        self.assertEqual(bm.newest_run_after(runs, 5), 10, msg="the earliest new one, not a stale newest")
        self.assertIsNone(bm.newest_run_after(runs, 30))
        self.assertEqual(bm.newest_run_after(runs, None), 10)

    def test_the_seed_flag_is_filled_into_a_request_and_the_estimate_counts_a_refusal_as_planning_only(self):
        self.assertEqual(bm.fill_request("retire-flag: {seed_flag} at {pass}", "0101", "issue-142"), "retire-flag: issue-142 at 0101")
        est = bm.estimate([task("a"), task("r", tags=["refusal"])])
        self.assertGreater(est["cost_low"], 0.12)


class DryRun(unittest.TestCase):
    def test_plan_spends_nothing_and_a_bad_candidate_is_an_error(self):
        self.assertEqual(bm.main(["benchmark.py", "plan"]), 0)
        self.assertEqual(bm.main(["benchmark.py", "plan", "--candidate", "bogus"]), 2)
        self.assertEqual(bm.main(["benchmark.py", "run", "--tasks", "nope"]), 2, msg="without --execute it is still only a plan")


if __name__ == "__main__":
    unittest.main()
