# Tests for the benchmark's pure logic. Run: python3 -m unittest discover -p "*_test.py" orchestrator
import json
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import api_check  # noqa: E402
import benchmark as bm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


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
        self.assertEqual(doc["roles"]["tester"]["model"], yaml.safe_load(text)["roles"]["tester"]["model"])  # untouched
        self.assertEqual(doc["limits"]["flag_retirement"]["piggyback_max"], 0)  # a ride-along retirement would make passes incomparable
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
                self.assertIsNone(api_check.validate(checks)[1], t["id"])  # the same file format the tester's helper reads
        self.assertTrue({"refusal"} & {tag for t in suite["tasks"] for tag in t["tags"]})  # refusals are part of the suite
        json.loads((ROOT / "agents" / "benchmark" / "rules.json").read_text())

    def test_problems_are_found(self):
        self.assertTrue(bm.validate_suite({"tasks": []}))
        bad = {"tasks": [{"id": "a", "request": "x", "expected": {"outcomes": []}, "oracle": {"checks": []}}, {"id": "a", "request": ""}]}
        self.assertGreaterEqual(len(bm.validate_suite(bad)), 2)

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
        self.assertFalse(bm.score_task(t, None, [])["passed"])  # no report at all

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
        self.assertTrue(bm.compare(agg(5, 2.0, 120, 1.5), self.base)["accept"])  # one task fewer is allowed, and not an improvement
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


class DryRun(unittest.TestCase):
    def test_plan_spends_nothing_and_a_bad_candidate_is_an_error(self):
        self.assertEqual(bm.main(["benchmark.py", "plan"]), 0)
        self.assertEqual(bm.main(["benchmark.py", "plan", "--candidate", "bogus"]), 2)
        self.assertEqual(bm.main(["benchmark.py", "run", "--tasks", "nope"]), 2)  # without --execute it is still only a plan


if __name__ == "__main__":
    unittest.main()
