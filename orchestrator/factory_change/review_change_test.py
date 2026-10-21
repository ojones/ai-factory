import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_run import review_code  # noqa: E402
from shared.shell import sh  # noqa: E402

from factory_change import review_change, vet_change  # noqa: E402

CFG = {"provider": {"base_url": "https://x"}, "limits": {}, "roles": {"factory_reviewer": {"model": "m", "prompt": "prompts/factory-reviewer.md"}}}


class Budget:
    def __init__(self):
        self.refreshed = []

    def mint(self, model):
        return "jwt"

    def refresh(self, jwt):
        self.refreshed.append(jwt)


def repo_with_change():
    root = Path(tempfile.mkdtemp())
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "config", "user.email", "a@b"], ["git", "config", "user.name", "a"]):
        sh(cmd, cwd=root)
    (root / "a.py").write_text("X = 1\n", encoding="utf-8")
    sh(["git", "add", "-A"], cwd=root)
    sh(["git", "commit", "-qm", "base"], cwd=root)
    (root / "a.py").write_text("X = 2\n", encoding="utf-8")
    (root / "new_test.py").write_text("Y = 1\n", encoding="utf-8")
    vet_change.stage_all(root)
    return root


class Reviewing(unittest.TestCase):
    def test_the_context_holds_the_ticket_the_diff_and_the_numbered_new_files(self):
        text = review_change.build_context(repo_with_change(), "Requirement one", 10000)
        self.assertIn("Requirement one", text)
        self.assertIn("+X = 2", text)
        self.assertIn("1: Y = 1", text)

    def test_a_change_too_big_for_one_call_is_an_error_not_a_partial_review(self):
        with self.assertRaises(review_code.ContextTooLarge):
            review_change.build_context(repo_with_change(), "t", 10)

    def test_the_verdict_comes_from_the_findings_and_the_spend_is_read(self):
        doc = {"analysis": "a", "improvements": [], "verdict": "clean", "findings": [
            {"severity": "blocking", "category": "correctness", "evidence_kind": "cited", "summary": "bug", "evidence": "e", "file": "a.py", "line": "1",
             "requirement": "", "suggested_fix": "", "repro": ""}]}
        budget = Budget()
        with mock.patch.object(review_code, "single_call_review", return_value=(doc, {})):
            clean, blocking, minor = review_change.review(CFG, budget, repo_with_change(), "t")
        self.assertFalse(clean, "the model said clean but a blocking finding stands")
        self.assertEqual(len(blocking), 1)
        self.assertEqual(budget.refreshed, ["jwt"])


if __name__ == "__main__":
    unittest.main()
