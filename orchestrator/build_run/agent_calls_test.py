import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import agent_output, provider, run_stops  # noqa: E402

from build_run import track_progress  # noqa: E402
from build_run.run import BuildRun  # noqa: E402


class JsonOutput(unittest.TestCase):
    def write(self, text):
        f = Path(tempfile.mkdtemp()) / "out.json"
        if text is not None:
            f.write_text(text)
        return f

    def test_the_problem_is_described_for_the_agent(self):
        self.assertIn("was not written", agent_output.json_problem(self.write(None)))
        self.assertIn("is empty", agent_output.json_problem(self.write("  \n")))
        bad = agent_output.json_problem(self.write('{"evidence": "Response: {"intervalSeconds":2}"}'))
        self.assertIn("not valid JSON", bad)
        self.assertIn("line 1 column", bad)
        self.assertIn("not escaped", bad)

    def test_a_usable_file_has_no_problem_and_a_rejected_one_says_why(self):
        self.assertIsNone(agent_output.json_problem(self.write('{"a": 1}')))
        def check(doc):
            raise ValueError("no results list")
        self.assertIn("no results list", agent_output.json_problem(self.write('{"a": 1}'), check))
        self.assertIn("not accepted", agent_output.json_problem(self.write('{"a": 1}'), lambda d: False))

    def test_the_second_attempt_is_told_what_was_wrong_with_the_first(self):
        run = object.__new__(BuildRun)
        path = self.write(None)
        notes, attempts = [], []

        def invoke(role, label, values, extra_env, cwd, home, note=None):
            attempts.append(label)
            notes.append(note)
            path.write_text('{"results": [' if len(attempts) == 1 else '{"results": []}')
            return 0, 0.1, None

        run.invoke, run.restore_tree = invoke, lambda cwd=None: None
        run.art = Path(__import__("tempfile").mkdtemp())
        doc, cost, _ = run.agent_json("tester", "t1", {}, path)
        self.assertEqual(doc, {"results": []})
        self.assertEqual((attempts, notes[0]), (["t1", "t1b"], None))
        self.assertIn("not valid JSON", notes[1])
        self.assertAlmostEqual(cost, 0.2)

    def test_two_bad_attempts_end_in_needs_human_with_the_last_reason(self):
        run = object.__new__(BuildRun)
        path = self.write(None)

        def invoke(role, label, values, extra_env, cwd, home, note=None):
            path.write_text("{oops")
            return 0, 0.1, None

        run.invoke, run.restore_tree = invoke, lambda cwd=None: None
        run.art = Path(__import__("tempfile").mkdtemp())
        run.state = track_progress.State(run.art / "state.json", "demo", "1", "url")
        with self.assertRaises(run_stops.NeedsHuman) as cm:
            run.agent_json("tester", "t1", {}, path)
        self.assertIn("no valid output file twice", str(cm.exception))
        self.assertIn("last problem: it is not valid JSON", str(cm.exception))
        failed = [s for s in run.state.d["stages"] if s["stage"] == "Tester failed"]
        self.assertEqual(len(failed), 1)
        self.assertAlmostEqual(failed[0]["cost_usd"], 0.2)
        self.assertIn("2 attempt(s)", failed[0]["verdict"])

    def run_that_always_hits_the_spending_limit(self, labels):
        run = object.__new__(BuildRun)
        run.art = Path(__import__("tempfile").mkdtemp())
        run.state = track_progress.State(run.art / "state.json", "demo", "1", "url")

        def invoke(role, label, values, extra_env, cwd, home, note=None):
            labels.append(label)
            (run.art / f"openhands-{role}-{label}.jsonl").write_text(
                '{"code": "LLMBadRequestError", "detail": "litellm.BadRequestError: OpenAIException - token spending limit exceeded"}\n')
            return 0, 0.55, None

        run.invoke, run.restore_tree = invoke, lambda cwd=None: None
        return run

    def test_an_agent_that_spent_its_whole_credential_is_not_given_a_second_attempt(self):
        path, labels = self.write(None), []
        run = self.run_that_always_hits_the_spending_limit(labels)
        with self.assertRaises(run_stops.NeedsHuman) as cm:
            run.agent_json("tester", "t1", {}, path)
        self.assertEqual(labels, ["t1"])
        self.assertIn("spent its whole credential", str(cm.exception))
        self.assertIn("would only repeat it", str(cm.exception))
        stage = run.state.d["stages"][-1]
        self.assertEqual((stage["stage"], stage["cost_usd"]), ("Tester failed", 0.55))
        self.assertIn("1 attempt(s)", stage["verdict"])

    def test_the_spending_limit_message_is_found_at_the_end_of_a_stream_and_a_missing_file_is_not_a_hit(self):
        p = self.write('x' * 400000 + 'token spending limit exceeded')
        self.assertTrue(provider.spending_limit_hit(p))
        self.assertFalse(provider.spending_limit_hit(self.write("all fine")))
        self.assertFalse(provider.spending_limit_hit(Path("/nonexistent/stream.jsonl")))


class MisplacedFile(unittest.TestCase):
    def test_a_report_written_in_the_working_directory_is_adopted_but_never_overwrites(self):
        d = Path(tempfile.mkdtemp())
        cwd, run = d / "tree", d / "run"
        cwd.mkdir()
        run.mkdir()
        (cwd / "report.json").write_text('{"a": 1}')
        self.assertTrue(agent_output.adopt_misplaced_file(run / "report.json", cwd))
        self.assertEqual((run / "report.json").read_text(), '{"a": 1}')
        (cwd / "report.json").write_text('{"a": 2}')
        self.assertFalse(agent_output.adopt_misplaced_file(run / "report.json", cwd), msg="the real file is never replaced")
        self.assertEqual((run / "report.json").read_text(), '{"a": 1}')
        self.assertFalse(agent_output.adopt_misplaced_file(run / "other.json", cwd))
        self.assertFalse(agent_output.adopt_misplaced_file(run / "x.json", None))
        self.assertIn("exactly that absolute path", agent_output.json_problem(run / "missing.json"))


if __name__ == "__main__":
    unittest.main()
