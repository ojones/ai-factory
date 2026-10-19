import json
import unittest

from flag_lifecycle import flag_manifest, retirement_check


class RetirementChecks(unittest.TestCase):
    def test_removed_slugs_are_the_flags_a_run_retired(self):
        base = json.dumps([{"slug": "a"}, {"slug": "b"}])
        self.assertEqual(flag_manifest.removed_flag_slugs(base, json.dumps([{"slug": "b"}])), ["a"])
        self.assertEqual(flag_manifest.removed_flag_slugs(base, base), [])
        self.assertEqual(flag_manifest.removed_flag_slugs("not json", base), [])

    def test_a_leftover_reference_in_code_fails_the_retirement_but_a_comment_does_not(self):
        lines = ["abc:backend/src/routes/todos.ts:12:  if (await isFeatureEnabled(res, \"old\")) {",
                 "abc:backend/src/routes/todos.ts:30:  // old was retired: always on",
                 "abc:backend/src/__tests__/todos.test.ts:5:  it(\"old flag off answers 404\", () => {"]
        hits = retirement_check.code_references(lines)
        self.assertEqual(hits, ["backend/src/routes/todos.ts:12", "backend/src/__tests__/todos.test.ts:5"])
        self.assertIn("still referenced", retirement_check.retirement_problem("old", hits))
        self.assertIsNone(retirement_check.retirement_problem("old", retirement_check.code_references([lines[1]])))

    def test_tests_and_flags_json_count_as_references_to_a_retiring_slug(self):
        lines = ["abc:backend/src/__tests__/todos.test.ts:9:  await withFlag(\"old\", false, async () => {",
                 "abc:flags.json:3:    \"slug\": \"old\",",
                 "abc:backend/src/__tests__/todos.test.ts:20:  // withFlag(\"old\", true, f) is gone"]
        hits = retirement_check.code_references(lines)
        self.assertEqual(hits, ["backend/src/__tests__/todos.test.ts:9", "flags.json:3"])
        problem = retirement_check.retirement_problem("old", hits)
        self.assertIn("withFlag(slug, false, ...)", problem)
        self.assertIn("unwrap", problem)


if __name__ == "__main__":
    unittest.main()
