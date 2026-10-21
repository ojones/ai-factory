import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import github  # noqa: E402
from shared.fake_issues import FakeIssues  # noqa: E402
from try_fix import factory_fix_request, render_bug  # noqa: E402

from factory_change import file_change, promote  # noqa: E402

DOC = {"how_found": "A child stopped in review.", "root_cause": "The loop never stops.", "what_it_takes": ["Stop the loop"],
       "requirements": ["The review loop stops after the configured number of rounds", "A stopped loop ends the run with a named outcome"], "source": "agent"}


def verdict(cause="orchestrator_gap"):
    ev = {"source": "child", "severity": "failure", "app": "notes", "story": 12, "summary": "The review loop never stops", "evidence": "run 1"}
    return {"key": "abc123def4", "target": "factory", "cause": cause, "event": ev}


class Promoting(unittest.TestCase):
    def setUp(self):
        self.gh = FakeIssues()
        patcher = mock.patch.multiple(github, run=self.gh, ensure_label=mock.Mock())
        patcher.start()
        self.addCleanup(patcher.stop)

    def request(self, cause="orchestrator_gap", again=0):
        body = render_bug.factory_body(DOC, verdict(cause)) + "\n" + factory_fix_request.failed_child_marker(12)
        number = self.gh.add(body=body, labels=("fix-request", "factory-fix-request"))
        self.gh.issues[number]["title"] = "Fix request [ab12cd34] [abc123def4]: The review loop never stops"
        self.gh.comments[number] = ["**Failed again** (child): x"] * again
        return number

    def listing(self, args):
        need = [args[i + 1] for i, a in enumerate(args) if a == "--label"]
        found = [i for i in self.gh.issues.values() if i["state"] == "open" and set(need) <= {x["name"] for x in i["labels"]}]
        return self.gh.ok([dict(i, comments=[{"body": b} for b in self.gh.comments.get(i["number"], [])]) for i in found])

    def sweep(self):
        self.gh.cli_list = self.listing
        return promote.sweep("o/f", "pat", {"promote_after_runs": 2})

    def test_an_orchestrator_gap_seen_twice_becomes_a_factory_change_intake(self):
        number = self.request(again=1)
        got = self.sweep()
        self.assertEqual(got, {number: "filed"})
        made = [i for n, i in self.gh.issues.items() if "factory-change" in [x["name"] for x in i["labels"]]][0]
        self.assertEqual(file_change.requirements_of(made["body"]), DOC["requirements"])
        self.assertEqual(factory_fix_request.read_failed_child(made["body"]), 12)
        self.assertIn("moved-to-factory-change", [x["name"] for x in self.gh.issues[number]["labels"]])

    def test_a_first_sighting_or_another_cause_stays_a_fix_request(self):
        self.request(again=0)
        self.request("prompt_gap", again=3)
        self.assertEqual(self.sweep(), {})

    def test_a_request_already_handed_over_is_not_handed_over_again(self):
        self.request(again=1)
        self.sweep()
        self.assertEqual(self.sweep(), {})
        self.assertEqual(json.dumps(sorted(self.gh.issues)).count(","), 1)

    def handed_over(self):
        number = self.request(again=1)
        self.sweep()
        return number, [n for n, i in self.gh.issues.items() if "factory-change" in [x["name"] for x in i["labels"]]][0]

    def test_a_failure_that_returns_after_the_handover_is_seen_again_on_the_intake(self):
        number, intake = self.handed_over()
        self.gh.comments[number].append("**Failed again** (child): y")
        self.assertEqual(self.sweep(), {number: "seen_again"})
        self.assertTrue(any(b.startswith("**Seen again") for b in self.gh.comments[intake]))

    def test_a_returning_failure_is_relayed_once(self):
        number, intake = self.handed_over()
        self.gh.comments[number].append("**Failed again** (child): y")
        self.sweep()
        self.assertEqual(self.sweep(), {})
        self.assertEqual(sum(b.startswith("**Seen again") for b in self.gh.comments[intake]), 1)

    def test_a_failure_before_the_handover_is_not_relayed(self):
        self.handed_over()
        self.assertEqual(self.sweep(), {})


if __name__ == "__main__":
    unittest.main()
