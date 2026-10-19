# Tests for flag retirement (it rides along in an update run). Run: python3 -m unittest discover -p "*_test.py" orchestrator
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import build_run as b  # noqa: E402
import flag_retirement as fr  # noqa: E402
from shared import github  # noqa: E402


def entry(slug, run, date="2026-10-10", state="released"):
    return {"key": f"app.feature.{slug}", "date": date, "run_url": f"https://github.com/o/r/actions/runs/{run}", "state": state}


class Candidates(unittest.TestCase):
    manifest = {"a", "b", "c"}

    def test_a_flag_is_retired_only_after_a_later_release_and_a_day(self):
        flags = [entry("a", 100), entry("b", 200)]
        self.assertEqual(fr.candidates(flags, self.manifest, "2026-10-12", 1), [("a", 100)])  # b is the newest release: keeps its flag
        self.assertEqual(fr.candidates([entry("a", 100)], self.manifest, "2026-10-12", 1), [])  # nothing came after it
        self.assertEqual(fr.candidates(flags, self.manifest, "2026-10-10", 1), [])  # released today: not a day yet
        self.assertEqual(fr.candidates(flags, self.manifest, "2026-10-10", 0), [("a", 100)])

    def test_a_flag_the_watchdog_switched_off_or_missing_from_the_manifest_is_never_retired(self):
        flags = [entry("a", 100, state="switched off by the watchdog"), entry("b", 200), entry("c", 300)]
        self.assertEqual(fr.candidates(flags, {"b", "c"}, "2026-10-12", 1), [("b", 200)])
        self.assertEqual(fr.candidates(flags, {"c"}, "2026-10-12", 1), [])

    def test_oldest_first_and_a_backlog_may_retire_several_up_to_the_limit(self):
        flags = [entry("c", 300), entry("a", 100), entry("b", 200), entry("d", 400)]
        manifest = {"a", "b", "c", "d"}
        self.assertEqual(fr.piggyback_slugs(flags, manifest, "2026-10-12", 1, 5), ["a", "b", "c"])  # d is the newest release
        self.assertEqual(fr.piggyback_slugs(flags, manifest, "2026-10-12", 1, 2), ["a", "b"])
        self.assertEqual(fr.piggyback_slugs(flags, manifest, "2026-10-12", 1, 0), [])


class Stories(unittest.TestCase):
    def test_issue_of_reads_the_story_each_flag_came_from(self):
        flags = [{**entry("a", 1), "issue": 94}, entry("b", 2), {**entry("c", 3), "issue": "x"}]
        self.assertEqual(fr.issue_of(flags), {"a": 94})


class Texts(unittest.TestCase):
    def test_the_task_block_and_the_spec_note_carry_one_retire_line_per_flag(self):
        self.assertEqual(fr.retirement_block([]), "")
        self.assertEqual(fr.retirement_note([]), "")
        block, note = fr.retirement_block(["a", "b"]), fr.retirement_note(["a", "b"])
        for text in (block, note):
            self.assertEqual(b.retire_slugs(text), ["a", "b"])
        self.assertIn("its own commit", block)
        self.assertIn("ordinary visitor", note)

    def test_retire_slugs_reads_every_line_once(self):
        self.assertEqual(b.retire_slugs("x\nretire-flag: a\nretire-flag: b-c\nretire-flag: a\n"), ["a", "b-c"])
        self.assertEqual(b.retire_slugs("Add a button"), [])


class BuildRunSide(unittest.TestCase):
    def test_removed_slugs_are_the_flags_a_run_retired(self):
        base = json.dumps([{"slug": "a"}, {"slug": "b"}])
        self.assertEqual(b.removed_flag_slugs(base, json.dumps([{"slug": "b"}])), ["a"])
        self.assertEqual(b.removed_flag_slugs(base, base), [])
        self.assertEqual(b.removed_flag_slugs("not json", base), [])

    def test_a_leftover_reference_in_code_fails_the_retirement_but_a_comment_does_not(self):
        lines = ["abc:backend/src/routes/todos.ts:12:  if (await isFeatureEnabled(res, \"old\")) {",
                 "abc:backend/src/routes/todos.ts:30:  // old was retired: always on",
                 "abc:backend/src/__tests__/todos.test.ts:5:  it(\"old flag off answers 404\", () => {"]
        hits = b.code_references(lines)
        self.assertEqual(hits, ["backend/src/routes/todos.ts:12", "backend/src/__tests__/todos.test.ts:5"])
        self.assertIn("still referenced", b.retirement_problem("old", hits))
        self.assertIsNone(b.retirement_problem("old", b.code_references([lines[1]])))


class Choosing(unittest.TestCase):
    # BuildRun.choose_flags_to_retire with the State issue and manifest mocked.

    def run_for(self, flags, *, update=True, fix=None, kind="update", task="Add a button", manifest="a,b,c,d", boom=False):
        run = object.__new__(b.BuildRun)
        run.update_intake, run.fix_meta, run.build_kind, run.task = update, fix or {}, kind, task
        run.app, run.app_repo, run.pat, run.lim = "app", "o/app", "pat", {"flag_retirement": {"min_age_days": 1, "piggyback_max": 5}}
        run.git = lambda *a, check=True: type("R", (), {"stdout": json.dumps([{"slug": s} for s in manifest.split(",")])})()
        patched = mock.patch.object(fr, "app_flags", side_effect=RuntimeError("down") if boom else None, return_value=(flags, set(manifest.split(","))))
        with patched, mock.patch.object(b.time, "strftime", return_value="2026-10-12"):
            return run.choose_flags_to_retire()

    flags = [entry("a", 100), entry("b", 200), entry("c", 300), entry("d", 400)]

    def test_an_update_retires_the_whole_backlog_but_the_newest_release(self):
        self.assertEqual(self.run_for(self.flags), ["a", "b", "c"])

    def test_a_first_build_and_an_automatic_retry_retire_nothing(self):
        self.assertEqual(self.run_for(self.flags, kind="first build"), [])
        self.assertEqual(self.run_for(self.flags, fix={"origin": 1, "attempt": 1}), [])
        self.assertEqual(self.run_for(self.flags, update=False), [])

    def test_a_slug_gone_from_the_manifest_is_dropped_and_a_failed_lookup_does_not_stop_the_run(self):
        self.assertEqual(self.run_for(self.flags, manifest="b,c,d"), ["b", "c"])
        self.assertEqual(self.run_for(self.flags, boom=True), [])

    def test_flags_the_owner_names_in_the_task_are_retired_too(self):
        self.assertEqual(self.run_for(self.flags, task="Do it\nretire-flag: d\n", kind="update"), ["d", "a", "b", "c"])


class DarkFeatureRetirement(unittest.TestCase):
    LABELS = ["update-app-intake", "app:notes", "flag:pin-notes", "dark-broken", "needs-human"]

    def test_a_person_can_approve_only_a_story_whose_retries_are_used_up(self):
        self.assertEqual(fr.dark_removal_target(self.LABELS), ("notes", "pin-notes", None))
        for missing, why in (("dark-broken", "no broken dark feature"), ("needs-human", "retries are not used up"),
                             ("flag:pin-notes", "exactly one flag"), ("app:notes", "exactly one flag"), ("update-app-intake", "not an Update App Intake")):
            app, slug, reason = fr.dark_removal_target([l for l in self.LABELS if l != missing])
            self.assertIsNone(app)
            self.assertIn(why, reason, missing)

    def test_more_than_one_flag_or_app_is_refused_rather_than_guessed(self):
        self.assertIsNotNone(fr.dark_removal_target(self.LABELS + ["flag:other"])[2])
        self.assertIsNotNone(fr.dark_removal_target(self.LABELS + ["app:other"])[2])

    def test_the_removal_task_deletes_the_feature_and_adds_nothing(self):
        task = fr.dark_removal_task("pin-notes", 12)
        self.assertIn("#12", task)
        self.assertIn("`flags.json`", task)
        self.assertIn("never released", task)
        self.assertEqual(b.retire_slugs(task), [])  # not the keep-it-on retirement of a released flag

    def test_approving_files_and_starts_the_removal_and_closes_the_story(self):
        calls = []

        def fake_sh(cmd, cwd=None, env=None, check=True, timeout=None):
            calls.append(cmd)
            if cmd[:3] == ["gh", "issue", "view"]:
                return mock.Mock(stdout=json.dumps({"title": "t", "labels": [{"name": l} for l in self.LABELS + ["approve-retire"]]}))
            if cmd[:3] == ["gh", "issue", "create"]:
                return mock.Mock(stdout="https://github.com/o/f/issues/90")
            return mock.Mock(stdout="")
        with mock.patch.object(fr.b, "sh", fake_sh), mock.patch.object(github, "ensure_label"):
            self.assertEqual(fr.approve("o/f", "pat", 12), 0)
        create = next(c for c in calls if c[:3] == ["gh", "issue", "create"])
        self.assertIn("### App name\n\nnotes", create[create.index("--body") + 1])
        self.assertTrue(any(c[:3] == ["gh", "issue", "edit"] and c[3] == "90" and "proceed-with-change" in c for c in calls))
        self.assertTrue(any(c[:3] == ["gh", "issue", "close"] and c[3] == "12" for c in calls))

    def test_a_refused_approval_says_why_and_starts_nothing(self):
        calls = []

        def fake_sh(cmd, cwd=None, env=None, check=True, timeout=None):
            calls.append(cmd)
            if cmd[:3] == ["gh", "issue", "view"]:
                return mock.Mock(stdout=json.dumps({"title": "t", "labels": [{"name": "update-app-intake"}, {"name": "approve-retire"}]}))
            return mock.Mock(stdout="")
        with mock.patch.object(fr.b, "sh", fake_sh):
            fr.approve("o/f", "pat", 12)
        self.assertFalse(any(c[:3] == ["gh", "issue", "create"] for c in calls))
        comment = next(c for c in calls if c[:3] == ["gh", "issue", "comment"])
        self.assertIn("Retirement not started", comment[comment.index("--body") + 1])


if __name__ == "__main__":
    unittest.main()
