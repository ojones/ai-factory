"""Tests for flag retirement. Run: python3 -m unittest discover orchestrator"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_run as b  # noqa: E402
import flag_retirement as fr  # noqa: E402


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

    def test_oldest_first(self):
        flags = [entry("b", 200), entry("a", 100), entry("c", 300)]
        self.assertEqual([s for s, _ in fr.candidates(flags, self.manifest, "2026-10-12", 1)], ["a", "b"])


class Filing(unittest.TestCase):
    def test_one_at_a_time_once_per_flag_and_a_daily_limit(self):
        cands = [("a", 100), ("b", 200)]
        self.assertEqual(fr.should_file(cands, [], [], 0, 2), ("a", 100))
        self.assertEqual(fr.should_file(cands, [f"x [retire a@100]"], [], 0, 2), ("b", 200))
        self.assertIsNone(fr.should_file(cands, [], [{"number": 1}], 0, 2))
        self.assertIsNone(fr.should_file(cands, [], [], 2, 2))
        self.assertIsNone(fr.should_file(cands, ["[retire a@100]", "[retire b@200]"], [], 0, 2))


class BuildRunSide(unittest.TestCase):
    def test_the_retirement_request_carries_the_slug_the_build_run_reads(self):
        text = fr.retirement_request("app", "fast-thing")
        self.assertEqual(b.retire_slug(text), "fast-thing")
        self.assertIsNone(b.retire_slug("Add a button"))

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


if __name__ == "__main__":
    unittest.main()
