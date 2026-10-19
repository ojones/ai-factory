import unittest

from flag_lifecycle import flag_usage


def git_returning(text):
    def git(*args):
        git.args = args
        return text
    return git


class CodeReads(unittest.TestCase):
    def test_a_hit_in_backend_code_counts_and_a_hit_in_a_test_does_not(self):
        out = ("abc:backend/src/routes/todos.ts:12:  isFeatureEnabled(res, 'issue-9')\n"
               "abc:backend/src/__tests__/todos.test.ts:5:  withFlag('issue-9', true)\n")
        hits = flag_usage.code_reads(git_returning(out), "abc", "issue-9")
        self.assertEqual(hits, ["abc:backend/src/routes/todos.ts:12:  isFeatureEnabled(res, 'issue-9')"])

    def test_only_tests_or_nothing_means_the_code_does_not_read_it(self):
        self.assertEqual(flag_usage.code_reads(git_returning("abc:frontend/src/a.spec.tsx:3:  'x'\n"), "abc", "x"), [])
        self.assertEqual(flag_usage.code_reads(git_returning(""), "abc", "x"), [])

    def test_it_searches_the_slug_as_a_quoted_literal_in_backend_and_frontend_at_the_given_commit(self):
        git = git_returning("")
        flag_usage.code_reads(git, "abc", "issue-9")
        self.assertIn('"issue-9"', git.args)
        self.assertIn("'issue-9'", git.args)
        self.assertEqual(git.args[-3:], ("--", "backend", "frontend"))


if __name__ == "__main__":
    unittest.main()
