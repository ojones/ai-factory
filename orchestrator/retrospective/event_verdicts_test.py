import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from try_fix import event  # noqa: E402

from retrospective import event_verdicts  # noqa: E402

FAIL = event.make("build_run", "failure", "demo", "round limit", "f1", story=66)
WARN = event.make("tester", "warning", "demo", "dark check failed", "w1", story=66)
WARN2 = event.make("reviewer", "warning", "demo", "unused import", "w2", story=66)


def entry(ev, verdict, reason="a user would hit it", target="managed_app", cause=None):
    return {"key": ev["key"], "verdict": verdict, "reason": reason, "target": target, "cause": cause}


class Decide(unittest.TestCase):
    def by_key(self, verdicts):
        return {v["key"]: v for v in verdicts}

    def test_without_an_answer_a_failure_is_fixed_and_a_warning_is_recorded(self):
        got = self.by_key(event_verdicts.decide([FAIL, WARN]))
        self.assertEqual((got[FAIL["key"]]["verdict"], got[WARN["key"]]["verdict"]), ("fix", "record"))

    def test_a_failure_cannot_be_downgraded_by_the_agent(self):
        got = self.by_key(event_verdicts.decide([FAIL], {FAIL["key"]: entry(FAIL, "record", "not worth it")}))
        self.assertEqual(got[FAIL["key"]]["verdict"], "fix")

    def test_a_warning_is_fixed_only_when_the_agent_says_fix_and_gives_a_reason(self):
        got = self.by_key(event_verdicts.decide([WARN, WARN2], {WARN["key"]: entry(WARN, "fix"), WARN2["key"]: entry(WARN2, "fix", reason="")}))
        self.assertEqual(got[WARN["key"]]["verdict"], "fix")
        self.assertEqual(got[WARN2["key"]]["verdict"], "record")
        self.assertIn("reason", got[WARN2["key"]]["reason"])

    def test_the_daily_limit_stops_warnings_from_becoming_a_stream_of_fixes_but_never_a_failure(self):
        lim = {"fix_events_per_app_per_day": 1}
        got = self.by_key(event_verdicts.decide([WARN, WARN2, FAIL], {WARN["key"]: entry(WARN, "fix"), WARN2["key"]: entry(WARN2, "fix")}, lim))
        self.assertEqual([got[WARN["key"]]["verdict"], got[WARN2["key"]]["verdict"], got[FAIL["key"]]["verdict"]], ["fix", "record", "fix"])
        used = self.by_key(event_verdicts.decide([WARN], {WARN["key"]: entry(WARN, "fix")}, lim, fixed_today=1))
        self.assertEqual(used[WARN["key"]]["verdict"], "record")
        self.assertIn("daily limit", used[WARN["key"]]["reason"])

    def test_every_event_gets_exactly_one_verdict_and_a_bad_target_falls_back_to_the_app(self):
        got = event_verdicts.decide([FAIL, WARN, WARN2], {FAIL["key"]: entry(FAIL, "fix", target="mars")})
        self.assertEqual([v["key"] for v in got], [FAIL["key"], WARN["key"], WARN2["key"]])
        self.assertIsNone(got[0]["target"])

    def test_the_agents_factory_target_and_cause_are_kept(self):
        got = event_verdicts.decide([FAIL], {FAIL["key"]: entry(FAIL, "fix", target="factory", cause="prompt_gap")})
        self.assertEqual((got[0]["target"], got[0]["cause"]), ("factory", "prompt_gap"))

    def test_parse_ignores_anything_malformed(self):
        self.assertEqual(event_verdicts.parse(None), {})
        self.assertEqual(event_verdicts.parse({"events": "no"}), {})
        self.assertEqual(list(event_verdicts.parse({"events": [{"key": "k1"}, "x", {"verdict": "fix"}]})), ["k1"])

    def test_fix_events_and_render(self):
        got = event_verdicts.decide([FAIL, WARN])
        self.assertEqual([v["key"] for v in event_verdicts.fix_events(got)], [FAIL["key"]])
        self.assertIn("**record**", event_verdicts.render(got))


class JudgeRunEvents(unittest.TestCase):
    CFG = {"roles": {"retrospective": {"model": "m"}}, "provider": {"base_url": "https://p"}, "limits": {"fix_events_per_app_per_day": 3}}

    def judge(self, events, result, key="parent", batch=None):
        import tempfile
        from unittest import mock

        from retrospective import agent_run, fix_budget, judge_events, run_retrospective
        asked = []

        def answer(evs, cfg, k):
            asked.append([e["key"] for e in evs])
            return batch or {}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(agent_run, "mint_agent", return_value=("scoped", mock.Mock())), \
                mock.patch.object(agent_run, "record_agent_spend"), mock.patch.object(judge_events, "answer", answer), \
                mock.patch.object(fix_budget, "warnings_fixed_today", return_value=0):
            got = run_retrospective.judge_run_events(events, result, self.CFG, key, "o/f", "tok", "demo", Path(tmp), "stuck")
            saved = json.loads((Path(tmp) / "artifacts" / "retrospective-verdicts.json").read_text())
        return got, asked, saved

    def test_warnings_the_agent_did_not_judge_go_to_one_batch_call_and_failures_never_do(self):
        got, asked, saved = self.judge([FAIL, WARN, WARN2], {"events": [entry(WARN, "record", "minor")]},
                                       batch={WARN2["key"]: entry(WARN2, "fix", "users hit it")})
        self.assertEqual(asked, [[WARN2["key"]]])
        self.assertEqual({v["key"]: v["verdict"] for v in got}, {FAIL["key"]: "fix", WARN["key"]: "record", WARN2["key"]: "fix"})
        self.assertEqual(len(saved), 3)

    def test_without_a_key_nothing_is_asked_and_the_defaults_apply(self):
        got, asked, _ = self.judge([FAIL, WARN], None, key=None)
        self.assertEqual(asked, [])
        self.assertEqual([v["verdict"] for v in got], ["fix", "record"])


if __name__ == "__main__":
    unittest.main()
