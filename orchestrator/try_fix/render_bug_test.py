import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from planning import plan_run  # noqa: E402
from request import read_form  # noqa: E402

from try_fix import event, render_bug  # noqa: E402

EV = event.make("tester", "failure", "demo", "blank text accepted", "fp", evidence="POST answered 201")
VERDICT = {"key": EV["key"], "verdict": "fix", "target": "managed_app", "cause": None, "reason": "r", "event": EV}
DOC = {"how_found": "The tester saw it.", "root_cause": "No trimming.", "what_it_takes": ["Blank text is rejected"],
       "requirements": ["POST /api/todos with blank text answers 400", "A test covers it"], "source": "agent"}
LIMITS = {"cost_cap_usd_default": 2.0, "cost_cap_usd_ceiling": 10.0}


class Bug(unittest.TestCase):
    def test_the_key_is_bracketed_hex_at_the_end_of_the_title_so_a_title_search_finds_it(self):
        self.assertRegex(EV["key"], r"^[0-9a-f]{10}$")
        self.assertTrue(render_bug.title(VERDICT, "demo").endswith(f"[{EV['key']}]"))

    def test_the_text_has_every_section_of_the_template_in_order(self):
        text = render_bug.request_text(DOC, VERDICT, "https://x/run/1")
        heads = [line[5:] for line in text.split("\n") if line.startswith("#### ")]
        self.assertEqual(heads, ["What happened", "How it was found", "Root cause", "What it would take to resolve", "Requirements", "Target",
                                 "Failure and solution log"])
        self.assertIn("1. POST /api/todos with blank text answers 400", text)
        self.assertIn("https://x/run/1", text)

    def test_an_app_bug_is_read_by_the_planner_like_any_update_app_intake(self):
        body = render_bug.intake_body("demo", DOC, VERDICT)
        issue = {"body": body, "title": render_bug.title(VERDICT, "demo"), "labels": [{"name": "update-app-intake"}, {"name": "bug"}]}
        info = mock.Mock(returncode=0, stdout='{"description": "Intake: o/f#3"}')
        got = plan_run.read_intake(issue, "o/f", lambda app: info, LIMITS)
        self.assertEqual((got["kind"], got["app"]), ("update", "demo"))
        self.assertIn("Blank text is rejected", got["task"])
        self.assertIn("A test covers it", got["task"])
        self.assertEqual(read_form.app_name(body), "demo")

    def test_the_marker_is_the_events_key_and_is_read_back(self):
        body = render_bug.intake_body("demo", DOC, VERDICT)
        self.assertEqual(render_bug.read_key(body), EV["key"])
        self.assertEqual(render_bug.read_key(render_bug.factory_body(DOC, {**VERDICT, "target": "factory"})), EV["key"])
        self.assertIsNone(render_bug.read_key("no marker"))

    def test_a_factory_bug_is_the_same_template_without_the_form(self):
        body = render_bug.factory_body(DOC, {**VERDICT, "target": "factory"})
        self.assertNotIn("### App name", body)
        self.assertIn("The Factory itself", body)

    def test_a_secret_in_the_evidence_never_reaches_the_public_ticket(self):
        leaky = {**VERDICT, "event": {**EV, "evidence": "token ghp_" + "a1" * 15}}
        for body in (render_bug.intake_body("demo", DOC, leaky), render_bug.factory_body(DOC, leaky)):
            self.assertNotIn("a1a1", body)

    def test_the_title_names_the_app_and_is_cut(self):
        long = {**VERDICT, "event": {**EV, "summary": "x" * 200}}
        self.assertLessEqual(len(render_bug.title(long, "demo")), len("demo: ") + 80 + len(f" [{long['key']}]"))


if __name__ == "__main__":
    unittest.main()
