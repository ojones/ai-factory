import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flag_lifecycle.fake_growthbook import FakeGrowthBook  # noqa: E402
from shared import http_client, run_stops  # noqa: E402

from build_run import track_progress  # noqa: E402
from build_run.run import BuildRun  # noqa: E402


class ArchiveRetired(unittest.TestCase):
    def archive(self, shown):
        run = object.__new__(BuildRun)
        run.state, run.app, run.gb = track_progress.State("/tmp/unused-state.json", "x", "1", "u"), "notes", mock.Mock(return_value=(200, {}))
        run.state.d["outcome"] = "released"
        run.git = lambda *a, **k: shown.pop(0)
        run.gh = mock.Mock()
        run.archive_retired_flags("b", "h")
        return run

    def test_a_flags_file_that_cannot_be_read_archives_nothing(self):
        both = [mock.Mock(returncode=0, stdout='[{"slug": "a"}]'), mock.Mock(returncode=1, stdout="")]
        self.archive(both).gb.assert_not_called()

    def test_a_removed_flag_is_archived_when_both_files_read(self):
        both = [mock.Mock(returncode=0, stdout='[{"slug": "a"}]'), mock.Mock(returncode=0, stdout="[]")]
        self.archive(both).gb.assert_called_once()


class Watchdog(unittest.TestCase):
    ok, bad = {"healthy": True, "errors": 0}, {"healthy": False, "errors": 0}


    def make(self, minutes, released):
        run = object.__new__(BuildRun)
        run.lim = {"watchdog_minutes": minutes, "watchdog_interval_seconds": 0, "watchdog_max_failures": 2, "watchdog_max_errors": 5}
        run.app, run.deadline = "x", float("inf")
        run.state = track_progress.State("/tmp/unused-state.json", "x", "1", "u")
        run.state.save = lambda: None
        run.state.d["release"] = {"released": released, "kept": ["x.feature.old"]}
        run.app_error_count = lambda: 0
        return run

    def test_a_tripped_watchdog_switches_off_only_what_this_run_released(self):
        run = self.make(0.05, ["x.feature.new"])
        run.disable_flags = mock.Mock(return_value=[])
        with mock.patch.object(http_client, "request", return_value=(500, {})), mock.patch.object(time, "sleep"):
            run.watch_release()
        run.disable_flags.assert_called_once_with(["x.feature.new"])
        self.assertEqual(run.state.d["outcome"], "watchdog_disabled")
        self.assertIn("health check failed", run.state.d["message"])

    def test_a_flag_that_will_not_turn_off_is_called_out(self):
        run = self.make(0.05, ["x.feature.new"])
        run.disable_flags = mock.Mock(return_value=["x.feature.new"])
        with mock.patch.object(http_client, "request", return_value=(500, {})), mock.patch.object(time, "sleep"):
            run.watch_release()
        self.assertIn("turn them off in GrowthBook now", run.state.d["message"])

    def test_a_healthy_app_is_left_alone(self):
        run = self.make(0.0005, ["x.feature.new"])
        run.disable_flags = mock.Mock()
        with mock.patch.object(http_client, "request", return_value=(200, {})), mock.patch.object(time, "sleep"):
            run.watch_release()
        run.disable_flags.assert_not_called()
        self.assertNotEqual(run.state.d["outcome"], "watchdog_disabled")

    def test_the_outcome_is_saved_before_the_watch_starts_so_a_cancel_cannot_look_like_a_crash(self):
        run = self.make(5, ["x.feature.new"])
        saves = []
        run.state.save = lambda: saves.append(run.state.d["outcome"])
        run.state.d["outcome"] = "released"
        run.disable_flags = mock.Mock()
        with mock.patch.object(http_client, "request", side_effect=KeyboardInterrupt), mock.patch.object(time, "sleep"):
            with self.assertRaises(KeyboardInterrupt):
                run.watch_release()
        self.assertEqual(saves[:1], ["released"])

    def test_zero_minutes_or_nothing_released_skips_the_watch(self):
        for minutes, released in ((0, ["x.feature.new"]), (5, [])):
            run = self.make(minutes, released)
            run.disable_flags = mock.Mock()
            with mock.patch.object(http_client, "request") as http:
                run.watch_release()
            http.assert_not_called()


class ReleasingTheStorysFlag(unittest.TestCase):
    OFF = {"environments": {"production": {"enabled": False, "rules": []}}}

    def release_run(self, features=None, own=("todo-ui",), reuse=(), code=""):
        run = object.__new__(BuildRun)
        run.app, run.issue, run.run_id, run.run_url, run.app_repo = "app", "94", "7", "u", "o/app"
        run.story_flags = list(own)
        run.state = track_progress.State(Path("/tmp/x-state.json"), "app", "94", "u")
        run.state.save = lambda: None
        run.state.d["named_flag"] = "todo-ui"
        run.gh = lambda *a, **k: type("R", (), {"stdout": ""})()
        run.gb = FakeGrowthBook({k: json.loads(json.dumps(v)) for k, v in (features or {}).items()})
        run.git = lambda *a, **k: type("R", (), {"stdout": code})()
        return run

    def test_the_stories_own_flag_that_exists_off_is_switched_on_whether_or_not_this_run_created_it(self):
        run = self.release_run({"app.feature.todo-ui": self.OFF})
        run.release(["todo-ui"], "sha")
        self.assertTrue(run.gb.production_enabled("app.feature.todo-ui"))
        self.assertEqual(run.state.d["release"], {"released": ["app.feature.todo-ui"], "kept": []})

    def test_a_fix_childs_flag_is_the_failed_storys_and_the_watchdog_switched_it_off_so_it_is_released_again(self):
        run = self.release_run({"app.feature.issue-12": self.OFF}, own=("issue-12",))
        run.release(["issue-12"], "sha")
        self.assertTrue(run.gb.production_enabled("app.feature.issue-12"))

    def test_any_other_existing_flag_is_left_exactly_as_it_is(self):
        run = self.release_run({"app.feature.other": self.OFF}, own=("todo-ui",))
        run.release(["other"], "sha")
        self.assertFalse(run.gb.production_enabled("app.feature.other"))
        self.assertEqual(run.state.d["release"], {"released": [], "kept": ["app.feature.other"]})

    def test_a_flag_that_does_not_exist_is_never_created(self):
        run = self.release_run(code="abc:backend/src/a.ts:3:  isFeatureEnabled(res, 'todo-ui')\n")
        with self.assertRaises(run_stops.FlagMissing):
            run.release(["todo-ui"], "sha")
        self.assertEqual([c[0] for c in run.gb.calls], ["GET"])

    def test_missing_and_read_by_the_code_is_a_dark_failure_that_rolls_nothing_back_and_says_what_to_add(self):
        run = self.release_run(code="abc:backend/src/a.ts:3:  isFeatureEnabled(res, 'todo-ui')\n")
        with self.assertRaises(run_stops.FlagMissing) as caught:
            run.release(["todo-ui"], "sha")
        self.assertIn("A flag that can be turned on has to exist", str(caught.exception))
        self.assertEqual(run.state.d["flag_notes"][0]["kind"], "missing_dark")
        self.assertIsNone(run.state.d["release"])

    def test_missing_and_not_read_by_the_code_means_it_is_already_live_so_it_is_noted_and_left_alone(self):
        run = self.release_run(code="")
        run.release(["todo-ui"], "sha")
        self.assertEqual(run.state.d["flag_notes"][0]["kind"], "live_without_flag")
        self.assertIn("went live on deploy without a gate", run.state.d["flag_message"])
        self.assertEqual(run.state.d["release"], {"released": [], "kept": []})

    def test_one_dark_flag_among_the_others_switches_nothing_on(self):
        run = self.release_run({"app.feature.todo-ui": self.OFF}, code="abc:backend/src/a.ts:3:  'ghost'\n")
        with self.assertRaises(run_stops.FlagMissing):
            run.release(["todo-ui", "ghost"], "sha")
        self.assertFalse(run.gb.production_enabled("app.feature.todo-ui"))

    def test_the_declared_flags_no_code_reads_are_the_ungated_ones(self):
        run = self.release_run()
        run.git = lambda *args, **k: type("R", (), {"stdout": "abc:backend/src/a.ts:3:  isFeatureEnabled(res, 'todo-ui')\n" if "'todo-ui'" in args else ""})()
        self.assertEqual(run.ungated_flags("abc", ["todo-ui", "other"]), ["other"])


if __name__ == "__main__":
    unittest.main()
