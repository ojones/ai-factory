"""Reverting a failed Build Run, tested against real git repositories (a local bare repo stands in for GitHub)."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_run as b  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class Repo:
    """An origin, a working clone at a base commit, and a run that pushed three changes on top (edit, add, delete)."""

    def __init__(self, new_flag=False):
        self.tmp = Path(tempfile.mkdtemp())
        self.origin = self.tmp / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        self.work = self.tmp / "work"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.work)], check=True, capture_output=True)
        git(self.work, "checkout", "-q", "-B", "main")
        (self.work / "a.txt").write_text("base a\n")
        (self.work / "flags.json").write_text("[]\n")
        (self.work / "dir").mkdir()
        (self.work / "dir/b.txt").write_text("base b\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "base")
        git(self.work, "push", "-q", "origin", "main")
        self.base = git(self.work, "rev-parse", "HEAD")
        (self.work / "a.txt").write_text("run edit\n")
        (self.work / "new.txt").write_text("run added\n")
        (self.work / "dir/b.txt").unlink()
        if new_flag:
            (self.work / "flags.json").write_text('[{"slug": "thing", "description": "x"}]\n')
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "run change")
        git(self.work, "push", "-q", "origin", "main")
        self.head = git(self.work, "rev-parse", "HEAD")
        self.d = {"app": "demo", "outcome": "round_limit", "message": "4 rounds without a clean pass", "base_sha": self.base,
                  "head_sha": self.head, "commits": [self.head], "release": None}

    def origin_main(self):
        return git(self.origin, "rev-parse", "main")

    def other_pushes(self, text):
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(other)], check=True, capture_output=True)
        (other / "c.txt").write_text(text)
        git(other, "add", "-A")
        git(other, "commit", "-q", "-m", "someone else")
        git(other, "push", "-q", "origin", "main")


class Decision(unittest.TestCase):
    d = {"outcome": "round_limit", "commits": ["h"], "base_sha": "b", "head_sha": "h", "release": None}

    def test_a_bad_ending_that_pushed_something_is_reverted(self):
        for outcome in ("round_limit", "needs_human", "stuck", "budget_exhausted", "time_limit", "crash", "running"):
            self.assertEqual(b.revert_decision(dict(self.d, outcome=outcome), "all"), (True, ""), outcome)

    def test_good_endings_and_contained_ones_are_left_alone(self):
        for outcome in ("released", "nothing_to_release", "planned", "watchdog_disabled"):
            self.assertFalse(b.revert_decision(dict(self.d, outcome=outcome), "all")[0], outcome)
        self.assertFalse(b.revert_decision(dict(self.d, release={"released": ["x.feature.a"]}), "all")[0])

    def test_nothing_pushed_or_nothing_to_return_to_is_a_skip(self):
        for d in (dict(self.d, commits=[]), dict(self.d, base_sha=None), dict(self.d, head_sha=None), dict(self.d, base_sha="h")):
            self.assertFalse(b.revert_decision(d, "all")[0])

    def test_the_mode_decides_about_flagged_runs_and_off_means_off(self):
        self.assertTrue(b.revert_decision(self.d, "all", ["thing"])[0])
        self.assertFalse(b.revert_decision(self.d, "unflagged", ["thing"])[0])
        self.assertTrue(b.revert_decision(self.d, "unflagged", [])[0])
        self.assertFalse(b.revert_decision(self.d, "off")[0])


class RealRevert(unittest.TestCase):
    def test_main_returns_to_the_starting_tree_with_history_kept(self):
        r = Repo()
        result = b.revert_main_to_base(r.d, r.work, run_id="9")
        self.assertEqual(result["status"], "reverted")
        self.assertEqual(result["restored"], r.base)
        self.assertEqual(r.origin_main(), result["sha"])
        self.assertEqual(git(r.origin, "diff", "--stat", r.base, "main"), "")  # same tree as the base
        self.assertEqual(git(r.origin, "show", "main:a.txt"), "base a")
        self.assertEqual(git(r.origin, "show", "main:dir/b.txt"), "base b")  # the deleted file is back
        self.assertNotIn("new.txt", git(r.origin, "ls-tree", "-r", "--name-only", "main"))  # the added file is gone
        self.assertEqual(git(r.origin, "rev-list", "--count", "main"), "3")  # base, the run's commit, the revert: nothing rewritten
        self.assertIn("Revert Build Run 9 (round_limit)", git(r.origin, "log", "-1", "--format=%B", "main"))

    def test_it_will_not_revert_over_someone_elses_commit(self):
        r = Repo()
        r.other_pushes("not ours\n")
        moved = r.origin_main()
        result = b.revert_main_to_base(r.d, r.work)
        self.assertEqual(result["status"], "skipped")
        self.assertIn("not reverting over it", result["reason"])
        self.assertEqual(r.origin_main(), moved)

    def test_a_dirty_checkout_does_not_get_in_the_way(self):
        r = Repo()
        (r.work / "a.txt").write_text("half-finished edit by a killed coder\n")
        (r.work / "junk.tmp").write_text("x\n")
        self.assertEqual(b.revert_main_to_base(r.d, r.work)["status"], "reverted")
        self.assertEqual(git(r.origin, "show", "main:a.txt"), "base a")

    def test_when_main_already_has_the_starting_tree_nothing_is_pushed(self):
        r = Repo()
        self.assertEqual(b.revert_main_to_base(r.d, r.work)["status"], "reverted")
        d2 = dict(r.d, head_sha=r.origin_main())
        before = r.origin_main()
        self.assertEqual(b.revert_main_to_base(d2, r.work)["status"], "skipped")
        self.assertEqual(r.origin_main(), before)

    def test_a_failure_is_reported_and_not_raised(self):
        r = Repo()
        git(r.work, "remote", "set-url", "origin", str(r.tmp / "nowhere.git"))
        result = b.revert_main_to_base(r.d, r.work)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["reason"])


class WholeStep(unittest.TestCase):
    def run_step(self, repo, mode):
        d = dict(repo.d)
        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "o/f", "GITHUB_RUN_ID": "5"}), \
                mock.patch.object(b, "wait_for_revert_deploy", return_value="healthy") as wait:
            b.revert_failed_run(d, repo.work, "pat", {"revert_failed_runs": mode})
        return d, wait

    def test_a_failed_unflagged_run_is_reverted_and_the_deploy_awaited(self):
        r = Repo()
        d, wait = self.run_step(r, "all")
        self.assertEqual((d["revert"]["status"], d["revert"]["deploy"], d["revert"]["mode"]), ("reverted", "healthy", "all"))
        self.assertEqual(wait.call_args[0][:3], ("demo", "o/demo", d["revert"]["sha"]))

    def test_a_flagged_run_is_kept_in_unflagged_mode_and_reverted_in_all_mode(self):
        r = Repo(new_flag=True)
        d, wait = self.run_step(r, "unflagged")
        self.assertEqual(d["revert"]["status"], "skipped")
        self.assertIn("flagged", d["revert"]["reason"])
        wait.assert_not_called()
        self.assertEqual(r.origin_main(), r.head)
        d, _ = self.run_step(r, "all")
        self.assertEqual(d["revert"]["status"], "reverted")

    def test_off_and_a_missing_checkout_are_recorded_not_raised(self):
        r = Repo()
        self.assertEqual(self.run_step(r, "off")[0]["revert"]["status"], "skipped")
        d = dict(r.d)
        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "o/f"}):
            b.revert_failed_run(d, "/nonexistent/app", "pat", {})
        self.assertEqual(d["revert"]["status"], "failed")


class Waiting(unittest.TestCase):
    def test_it_waits_for_the_deploy_of_that_commit_then_for_health(self):
        runs = [[], [{"headSha": "other", "status": "completed", "conclusion": "success"}],
                [{"headSha": "abc", "status": "completed", "conclusion": "success"}]]
        calls = iter(runs)
        with mock.patch.object(b, "sh", side_effect=lambda *a, **k: mock.Mock(stdout=__import__("json").dumps(next(calls)))), \
                mock.patch.object(b, "http", return_value=(200, {})), mock.patch.object(b.time, "sleep"):
            self.assertEqual(b.wait_for_revert_deploy("demo", "o/demo", "abc", "pat", 5), "healthy")

    def test_a_failed_deploy_and_a_timeout_are_reported(self):
        failed = [{"headSha": "abc", "status": "completed", "conclusion": "failure"}]
        with mock.patch.object(b, "sh", return_value=mock.Mock(stdout=__import__("json").dumps(failed))), mock.patch.object(b.time, "sleep"):
            self.assertEqual(b.wait_for_revert_deploy("demo", "o/demo", "abc", "pat", 5), "deploy_failed")
        with mock.patch.object(b, "sh", return_value=mock.Mock(stdout="[]")), mock.patch.object(b.time, "sleep"), \
                mock.patch.object(b.time, "time", side_effect=[0, 1, 10**6]):
            self.assertEqual(b.wait_for_revert_deploy("demo", "o/demo", "abc", "pat", 5), "timeout")


if __name__ == "__main__":
    unittest.main()
