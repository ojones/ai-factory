import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from try_fix import event  # noqa: E402

from retrospective import judge_events  # noqa: E402

CFG = {"roles": {"retrospective": {"model": "m"}}, "provider": {"base_url": "https://p"}, "limits": {"fix_events_per_app_per_day": 3}}
FAIL = event.make("staging", "failure", "demo", "smoke failed", "smoke")
WARN = event.make("production_feedback", "warning", "demo", "slow endpoint", "slow")


def asker(answer, seen=None):
    def ask(base_url, key, model, system, user):
        if seen is not None:
            seen.append((base_url, key, model, user))
        if isinstance(answer, Exception):
            raise answer
        return answer
    return ask


class Judge(unittest.TestCase):
    def test_the_model_decides_the_warning_and_the_batch_is_one_call(self):
        seen = []
        reply = json.dumps({"events": [{"key": WARN["key"], "verdict": "fix", "target": "managed_app", "cause": "slow query", "reason": "users wait 9s"}]})
        got = judge_events.judge([FAIL, WARN], CFG, "k", asker(reply, seen))
        self.assertEqual(len(seen), 1)
        self.assertEqual([(v["verdict"], v["reason"]) for v in got], [("fix", "a failure is always fixed"), ("fix", "users wait 9s")])

    def test_an_unreachable_model_or_a_bad_answer_leaves_the_defaults(self):
        for answer in (RuntimeError("down"), "not json", json.dumps({"events": "x"})):
            got = judge_events.judge([FAIL, WARN], CFG, "k", asker(answer))
            self.assertEqual([v["verdict"] for v in got], ["fix", "record"])

    def test_a_batch_of_failures_alone_is_not_sent_to_the_model_and_every_failure_is_still_fixed(self):
        seen = []
        got = judge_events.judge([FAIL], CFG, "k", asker("{}", seen))
        self.assertEqual(seen, [])
        self.assertEqual([v["verdict"] for v in got], ["fix"])

    def test_no_key_or_no_retrospective_role_asks_nothing(self):
        seen = []
        judge_events.judge([WARN], CFG, None, asker("{}", seen))
        judge_events.judge([WARN], {**CFG, "roles": {}}, "k", asker("{}", seen))
        self.assertEqual(seen, [])

    def test_the_model_is_never_asked_about_nothing(self):
        seen = []
        self.assertEqual(judge_events.judge([], CFG, "k", asker("{}", seen)), [])
        self.assertEqual(seen, [])

    def test_the_daily_limit_applies_to_a_scan_too(self):
        reply = json.dumps({"events": [{"key": WARN["key"], "verdict": "fix", "reason": "r"}]})
        got = judge_events.judge([WARN], CFG, "k", asker(reply), fixed_today=3)
        self.assertEqual(got[0]["verdict"], "record")

    def test_main_reads_events_and_writes_verdicts_without_a_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "e.json", Path(tmp) / "v.json"
            event.dump([FAIL, WARN], src)
            from unittest import mock

            from shared import config
            with mock.patch.object(config, "load", return_value=CFG), mock.patch.dict("os.environ", {}, clear=True):
                self.assertEqual(judge_events.main(["x", str(src), str(out)]), 0)
            self.assertEqual([v["verdict"] for v in json.loads(out.read_text())], ["fix", "record"])


if __name__ == "__main__":
    unittest.main()
