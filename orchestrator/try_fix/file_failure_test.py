import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from try_fix import event, file_failure  # noqa: E402

CFG = {"roles": {"try_fix": {"model": "m", "prompt": "prompts/try_fix.md"}}, "limits": {"fix_attempts_max": 3, "jwt_ttl_seconds": 60}}
FACTS = {"app": "demo", "outcome": "round_limit", "message": "m", "run_url": "u", "issue_number": "12", "bugs": []}


def verdict(target=None, source="build_run", severity="failure", fp="f", cause=None, story=12):
    ev = event.make(source, severity, "demo", "boom", fp, story=story)
    return {"key": ev["key"], "verdict": "fix", "target": target, "cause": cause, "reason": "r", "event": ev}


class TargetFor(unittest.TestCase):
    def test_the_retrospectives_own_target_wins(self):
        self.assertEqual(file_failure.target_for(verdict("factory"), FACTS, {"category": "spec_ambiguity"}), "factory")

    def test_a_runs_failure_with_no_target_is_routed_by_its_cause(self):
        for category, want in (("prompt_gap", "factory"), ("spec_ambiguity", "managed_app"), ("infra", "info"), (None, "info")):
            self.assertEqual(file_failure.target_for(verdict(), FACTS, {"category": category}), want, category)
        self.assertEqual(file_failure.target_for(verdict(), dict(FACTS, outcome="budget_exhausted"), {"category": "prompt_gap"}), "managed_app")
        self.assertEqual(file_failure.target_for(verdict(source="watchdog"), dict(FACTS, outcome="watchdog_disabled"), None), "managed_app")

    def test_any_other_event_with_no_target_is_the_apps(self):
        self.assertEqual(file_failure.target_for(verdict(source="tester", severity="warning"), FACTS, {"category": "prompt_gap"}), "managed_app")
        self.assertEqual(file_failure.target_for(verdict(source="production_feedback"), None, None), "managed_app")

    def test_a_failed_staging_check_with_no_target_is_the_factorys(self):
        self.assertEqual(file_failure.target_for(verdict(source="staging"), None, None), "factory")
        self.assertEqual(file_failure.target_for(verdict("managed_app", source="staging"), None, None), "managed_app")


class FileFailures(unittest.TestCase):
    def go(self, fixes, result=None, key="parent", file_error=None, written=None):
        wrote, filed, spent = [], [], []

        def write(v, facts, rollback, cfg, cred):
            wrote.append((v["target"], v["cause"], cred))
            return written or {"how_found": "x", "root_cause": "y", "what_it_takes": ["z"], "requirements": ["a b c d e f g h i j"], "source": "agent"}

        def file(repo, token, pat, v, doc, facts, max_attempts):
            if file_error:
                raise file_error
            filed.append((v["key"], max_attempts))
            return {"target": v["target"], "action": "bug_intake", "number": 40 + len(filed), "url": f"u{len(filed)}"}
        with mock.patch.object(file_failure.write_bug, "mint", return_value=("cred", "budget")), mock.patch.object(file_failure.write_bug, "write", write), \
                mock.patch.object(file_failure.file_bug, "file_bug", file), mock.patch.object(file_failure.needs_human, "hold") as hold:
            out = file_failure.file_failures("o/f", "tok", "pat", fixes, FACTS, result, None, CFG, key, lambda b, c: spent.append((b, c)))
        return out, wrote, filed, spent, hold

    def test_each_fix_gets_the_agents_text_then_is_filed_with_the_attempt_bound_and_the_spend_is_recorded_once(self):
        out, wrote, filed, spent, _ = self.go([verdict(fp="a"), verdict(fp="b", source="tester", severity="warning", story=13)], {"category": "spec_ambiguity"})
        self.assertEqual([w[0] for w in wrote], ["managed_app", "managed_app"])
        self.assertEqual([w[1] for w in wrote], ["spec_ambiguity", "spec_ambiguity"], msg="the cause of the run, when the verdict has none")
        self.assertEqual({w[2] for w in wrote}, {"cred"}, msg="one credential for the batch")
        self.assertEqual([f[1] for f in filed], [3, 3])
        self.assertEqual(spent, [("budget", "cred")])
        self.assertEqual([(o["severity"], o["action"]) for o in out], [("failure", "bug_intake"), ("warning", "bug_intake")])

    def test_events_on_one_story_are_one_ticket_and_one_bug_with_a_result_per_event(self):
        a, b = verdict(fp="a"), verdict(fp="b", source="tester", severity="warning")
        out, wrote, filed, _, _ = self.go([a, b], {"category": "spec_ambiguity"})
        self.assertEqual((len(wrote), [f[0] for f in filed]), (1, [a["key"]]))
        self.assertEqual([(o["key"], o["number"]) for o in out], [(a["key"], 41), (b["key"], 41)])

    def test_the_primary_verdict_carries_every_event_of_its_group(self):
        a, b = verdict("managed_app", fp="a"), verdict(fp="b", source="tester", severity="warning")
        seen = []
        with mock.patch.object(file_failure.write_bug, "mint", return_value=("cred", "budget")), \
                mock.patch.object(file_failure.write_bug, "write", lambda v, *rest: seen.append(v["events"]) or {}), \
                mock.patch.object(file_failure.file_bug, "file_bug", return_value={"target": "managed_app", "action": "bug_intake", "number": 1, "url": "u"}):
            file_failure.file_failures("o/f", "tok", "pat", [a, b], FACTS, None, None, CFG, "parent")
        self.assertEqual([[e["key"] for e in seen[0]]], [[a["key"], b["key"]]])

    def test_without_a_key_nothing_is_minted_and_the_ticket_is_still_written_and_filed(self):
        with mock.patch.object(file_failure.write_bug, "mint") as mint:
            out, wrote, *_ = self.go([verdict()], key=None)
        mint.assert_not_called()
        self.assertEqual(len(out), 1)
        self.assertEqual(wrote[0][2], None)

    def test_a_failure_that_cannot_be_filed_holds_its_child_and_never_raises(self):
        out, _, _, _, hold = self.go([verdict()], file_error=RuntimeError("boom"))
        self.assertEqual(out[0]["action"], "needs_human")
        hold.assert_called_once()
        self.assertEqual(hold.call_args.args[2], 12)

    def test_a_hold_that_also_fails_is_logged_not_swallowed(self):
        with mock.patch.object(file_failure, "log") as shown, mock.patch.object(file_failure.needs_human, "hold", side_effect=RuntimeError("down")):
            file_failure.hold_story("o/f", "tok", 12, RuntimeError("boom"))
        self.assertIn("#12", shown.call_args.args[0])

    def test_a_warning_that_cannot_be_filed_holds_nothing(self):
        out, _, _, _, hold = self.go([verdict(source="tester", severity="warning")], file_error=RuntimeError("boom"))
        self.assertEqual(out[0]["action"], "needs_human")
        hold.assert_not_called()


if __name__ == "__main__":
    unittest.main()
