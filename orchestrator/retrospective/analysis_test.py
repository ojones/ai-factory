import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrospective import agent_run, analysis, tracker  # noqa: E402


class Analyse(unittest.TestCase):
    def analyse(self, written=None, ran=True, key="k"):
        result = Path(tempfile.mkdtemp()) / "r.json"

        def run_agent(*args):
            if written is not None:
                result.write_text(json.dumps(written))
            return ran
        with mock.patch.object(agent_run, "mint_agent", return_value=(key, object())), mock.patch.object(agent_run, "run_agent", run_agent), \
                mock.patch.object(agent_run, "record_agent_spend"), mock.patch.object(tracker, "gh") as gh:
            got = analysis.analyse(Path(), {"limits": {}}, "o/f", "tok", "parent", Path("f"), result, [4, 5], "9")
        return got, gh

    def test_the_cause_is_commented_on_every_target_and_returned(self):
        got, gh = self.analyse({"category": "prompt_gap", "root_cause": "The prompt never says it."})
        self.assertEqual(got["category"], "prompt_gap")
        self.assertEqual([c.args[0][2] for c in gh.call_args_list], ["4", "5"])
        self.assertIn("prompt_gap", gh.call_args_list[0].args[0][-1])

    def test_an_unusable_answer_is_said_so_and_returns_nothing(self):
        got, gh = self.analyse({"category": "nonsense"})
        self.assertIsNone(got)
        self.assertIn("no usable analysis", gh.call_args_list[0].args[0][-1])

    def test_no_agent_run_means_no_comment(self):
        got, gh = self.analyse(ran=False)
        self.assertIsNone(got)
        gh.assert_not_called()

    def test_no_credential_means_no_agent_run(self):
        got, gh = self.analyse(key=None)
        self.assertIsNone(got)
        gh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
