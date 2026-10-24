import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import config  # noqa: E402

from retrospective import improvement_issues, minor_findings, run_facts, run_retrospective, story_report, tracker  # noqa: E402

STATE = {"app": "demo", "outcome": "round_limit", "message": "4 review rounds used without a clean pass",
         "run_url": "http://run", "issue_number": "7", "spent_usd": 1.5, "commits": ["a"],
         "blocking": [{"summary": "The new route is mounted before the health route"}],
         "stages": [{"stage": "Coder", "round": "1", "verdict": "pushed", "cost_usd": 0.2, "usage": {"seconds": 120, "calls": 30}},
                    {"stage": "Release", "round": "-", "verdict": "x", "cost_usd": 0, "usage": None}]}


class Improvements(unittest.TestCase):
    IMPS = [{"source": "reviewer", "target": "factory", "summary": "The coder prompt never says to trim input", "evidence": "round 1"},
            {"source": "tester", "target": "managed_app", "summary": "Add a test for empty text", "evidence": ""}]

    def facts(self, **over):
        with tempfile.TemporaryDirectory() as tmp:
            return run_facts.collect_facts(tmp, {**STATE, "outcome": "released", "improvements": self.IMPS, **over})

    def run_main(self, state):
        work = Path(tempfile.mkdtemp())
        (work / "state.json").write_text(json.dumps(state))
        calls = []

        def fake_gh(args, token, check=False):
            calls.append(args)
            return mock.Mock(stdout="[]" if args[:2] == ["issue", "list"] else (
                "https://github.com/o/f/issues/41" if args[:2] == ["issue", "create"] else ""), returncode=0)
        env = {"BUILD_RUN_DIR": str(work), "GITHUB_REPOSITORY": "o/f", "GITHUB_RUN_ID": "9", "FACTORY_PAT": "pat", "FACTORY_GH_TOKEN": "tok"}
        with mock.patch.dict(__import__("os").environ, env), mock.patch.object(tracker, "gh", fake_gh), \
                mock.patch.object(config, "load", return_value={"roles": {}, "limits": {}}):
            self.assertEqual(run_retrospective.main(), 0)
        return calls

    def test_the_improvements_ride_along_in_the_facts(self):
        facts = self.facts()
        self.assertEqual([i["target"] for i in facts["improvements"]], ["factory", "managed_app"])

    def test_each_improvement_goes_to_its_own_tracker(self):
        created = []

        def fake_gh(args, token, check=False):
            if args[:2] == ["issue", "create"]:
                created.append((args[args.index("--repo") + 1], args[args.index("--title") + 1]))
                return mock.Mock(stdout=f"https://github.com/x/y/issues/{40 + len(created)}")
            return mock.Mock(stdout="[]")
        with mock.patch.object(tracker, "gh", fake_gh):
            filed = improvement_issues.record_improvements("o/ai-factory", "tok", self.facts())
        self.assertEqual([r for r, _ in created], ["o/ai-factory"])
        self.assertTrue(created[0][1].startswith("Improvement ["))
        self.assertEqual([f["target"] for f in filed], ["factory", "managed_app"])

    def test_the_same_improvement_twice_is_one_issue_and_the_number_per_run_is_capped(self):
        many = [{"source": "tester", "target": "managed_app", "summary": f"idea {n}", "evidence": ""} for n in range(minor_findings.MAX_MINORS + 4)]
        created = []
        with mock.patch.object(tracker, "gh", lambda args, token, check=False: (created.append(args) if args[:2] == ["issue", "create"] else None) or mock.Mock(stdout="[]")):
            with tempfile.TemporaryDirectory() as tmp:
                facts = run_facts.collect_facts(tmp, dict(STATE, outcome="released", improvements=many))
            filed = improvement_issues.record_improvements("o/ai-factory", "tok", facts)
        self.assertEqual(len(filed), minor_findings.MAX_MINORS)
        self.assertEqual(len(created), 0, msg="app improvements file nothing here")

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
        posted = []
        seen = mock.Mock(stdout="<!-- retrospective:9 -->")
        with mock.patch.object(tracker, "gh", lambda args, token, check=False: seen if args[:2] == ["issue", "view"] else posted.append(args)):
            self.assertFalse(story_report.post_retrospective("o/f", "tok", "7", "9", "body"))
        self.assertEqual(posted, [])

    def test_the_summary_names_a_dark_feature_and_a_regression(self):
        facts = self.facts(outcome="regression", message="old route broke", flags=["f"])
        text = story_report.render_retrospective(dict(facts, dark_broken=True), [], [])
        self.assertIn("Dark feature left behind", text)
        self.assertIn("rolled back to the previous version", text)


class Duplicates(unittest.TestCase):
    def issues(self, *titles):
        return mock.patch.object(tracker, "gh", lambda args, token, check=False: mock.Mock(
            stdout=json.dumps([{"number": 10 + n, "title": t} for n, t in enumerate(titles)])))

    def test_a_reworded_repeat_matches_the_open_issue_and_a_different_problem_does_not(self):
        with self.issues("Improvement [ab12cd34] The coder prompt never says to trim input", "Suggestion: Add a test for empty text"):
            self.assertEqual(tracker.similar_open_issue("o/f", "t", "Coder prompt does not say to trim the input"), 10)
            self.assertEqual(tracker.similar_open_issue("o/f", "t", "add a test for empty text values"), 11)
            self.assertIsNone(tracker.similar_open_issue("o/f", "t", "The Starter Template lacks a health route"))
            self.assertIsNone(tracker.similar_open_issue("o/f", "t", "the of and"))

    def test_a_factory_improvement_that_matches_an_open_issue_adds_context_and_opens_nothing(self):
        calls = []

        def gh(args, token, check=False):
            calls.append(args)
            if args[:2] == ["issue", "list"]:
                return mock.Mock(stdout=json.dumps([{"number": 31, "title": "Improvement [ab12cd34] The coder prompt never says to trim input"},
                                                   {"number": 32, "title": "Suggestion: Add a test for empty text"}]))
            return mock.Mock(stdout="")
        with tempfile.TemporaryDirectory() as tmp:
            facts = run_facts.collect_facts(tmp, {**STATE, "outcome": "released", "improvements": Improvements.IMPS})
        facts["improvements"] = [dict(facts["improvements"][0], summary="Coder prompt does not say to trim the input"),
                                 dict(facts["improvements"][1], summary="Add a test for empty text values")]
        with mock.patch.object(tracker, "gh", gh):
            filed = improvement_issues.record_improvements("o/f", "tok", facts)
        self.assertFalse([c for c in calls if c[:2] == ["issue", "create"]], "it was already open")
        self.assertEqual({c[2] for c in calls if c[:2] == ["issue", "comment"]}, {"31"})
        self.assertTrue(filed[0]["url"].endswith("/issues/31"))
        self.assertEqual(filed[1], {"target": "managed_app", "summary": "Add a test for empty text values", "url": ""})


if __name__ == "__main__":
    unittest.main()
