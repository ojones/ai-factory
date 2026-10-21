import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retrospective import learning_pr  # noqa: E402
from shared import github  # noqa: E402
from shared.shell import sh  # noqa: E402

from factory_change import markers, open_pr  # noqa: E402


class FakeGh:
    def __init__(self, open_branches=()):
        self.calls, self.open_branches = [], open_branches

    def __call__(self, args, token, check=False):
        self.calls.append(args)
        if args[:2] == ["pr", "list"]:
            return SimpleNamespace(stdout=json.dumps([{"headRefName": b} for b in self.open_branches]), returncode=0)
        return SimpleNamespace(stdout="https://github.com/o/f/pull/9\n", returncode=0)


def repo_with_change():
    root = Path(tempfile.mkdtemp())
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "config", "user.email", "a@b"], ["git", "config", "user.name", "a"]):
        sh(cmd, cwd=root)
    (root / "a.py").write_text("X = 1\n", encoding="utf-8")
    sh(["git", "add", "-A"], cwd=root)
    sh(["git", "commit", "-qm", "base"], cwd=root)
    (root / "a.py").write_text("X = 2\n", encoding="utf-8")
    return root


class Opening(unittest.TestCase):
    def open(self, paths, gh, factory=None):
        with mock.patch.object(github, "run", gh), mock.patch.object(github, "ensure_label"), mock.patch.object(learning_pr, "push_branch") as push:
            url = open_pr.open_pr(factory or repo_with_change(), "o/f", "pat", 5, "Keep the child", "planning.x_test.A.test_b", paths, 3)
        return url, push

    def test_a_tier_one_change_is_a_pr_on_its_branch_marked_to_merge_itself(self):
        gh = FakeGh()
        url, push = self.open(["orchestrator/bugs/a.py"], gh)
        self.assertEqual(url, "https://github.com/o/f/pull/9")
        self.assertEqual(push.call_args.args[1], "factory-change/5")
        create = next(c for c in gh.calls if c[:2] == ["pr", "create"])
        self.assertEqual(create[create.index("--base") + 1], "main")
        self.assertIn("factory-change-auto", create)
        self.assertEqual(markers.read(create[create.index("--body") + 1], "reproduction"), "planning.x_test.A.test_b")

    def test_a_tier_two_change_waits_for_a_person(self):
        gh = FakeGh()
        self.open(["orchestrator/try_fix/route.py"], gh)
        create = next(c for c in gh.calls if c[:2] == ["pr", "create"])
        self.assertIn("awaiting-human", create)
        self.assertNotIn("factory-change-auto", create)

    def test_no_pr_is_opened_past_the_limit(self):
        gh = FakeGh(["factory-change/1", "factory-change/2", "factory-change/3", "learning/run-1"])
        url, push = self.open(["orchestrator/bugs/a.py"], gh)
        self.assertIsNone(url)
        push.assert_not_called()


if __name__ == "__main__":
    unittest.main()
