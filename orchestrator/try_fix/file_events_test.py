import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from try_fix import event, file_events  # noqa: E402

FAIL = event.make("production_feedback", "failure", "demo", "TypeError", "fp")
WARN = event.make("tester", "warning", "demo", "slow", "w")


def verdict(ev, kind):
    return {"key": ev["key"], "verdict": kind, "target": None, "cause": None, "reason": "r", "event": ev}


class FileEvents(unittest.TestCase):
    def run_main(self, verdicts, limits=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v.json"
            path.write_text(verdicts if isinstance(verdicts, str) else json.dumps(verdicts))
            env = {"GITHUB_REPOSITORY": "o/f", "FACTORY_PAT": "pat", "FACTORY_GH_TOKEN": "tok", "DEEPINFRA_API_KEY": "k"}
            with mock.patch.dict("os.environ", env), mock.patch.object(file_events.config, "load", return_value={"limits": limits or {}}), \
                    mock.patch.object(file_events.file_failure, "file_failures", return_value=[]) as filing:
                self.assertEqual(file_events.main(["x", str(path)]), 0)
        return filing

    def test_only_fix_verdicts_are_filed_with_no_run_facts(self):
        filing = self.run_main([verdict(FAIL, "fix"), verdict(WARN, "record")])
        fixes = filing.call_args.args[3]
        self.assertEqual([v["key"] for v in fixes], [FAIL["key"]])
        self.assertEqual(filing.call_args.args[4:7], (None, None, None))  # no facts, result or rollback: a scan has no Build Run

    def test_nothing_to_fix_or_unreadable_verdicts_files_nothing_and_does_not_fail(self):
        for verdicts in ([verdict(WARN, "record")], "not json", "{}", [{"verdict": "fix", "event": {"x": 1}}]):
            self.run_main(verdicts).assert_not_called()

    def test_the_switch_for_fix_requests_turns_filing_off(self):
        self.run_main([verdict(FAIL, "fix")], {"fix_requests": False}).assert_not_called()


if __name__ == "__main__":
    unittest.main()
