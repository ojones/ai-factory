# What the tester's failed checks become: bugs filed by the retrospective, not decided by the tester.
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_run import verify_deployed_app  # noqa: E402


class Tester(unittest.TestCase):
    def test_the_tester_only_notes_what_failed_and_the_retrospective_files_it(self):
        failures = [
            {"flag": "pin", "check": "new route answers 201", "status": "failed", "scope": "new", "evidence": "got 500", "repro": "curl x"},
            {"flag": "", "check": "GET /api/notes answers 200", "status": "failed", "scope": "existing", "evidence": "got 404", "repro": "curl y"},
            {"flag": "pin", "check": "slow thing", "status": "blocked", "scope": "new", "evidence": "app unreachable"},
            {"flag": "pin", "check": "side effect", "status": "not_run", "scope": "new", "evidence": "skipped"}]
        bugs = verify_deployed_app.bugs_from(failures)
        self.assertEqual([(x["kind"], x["check"]) for x in bugs], [("dark", "new route answers 201"), ("regression", "GET /api/notes answers 200")])
        self.assertEqual(bugs[1]["evidence"], "got 404")
        self.assertEqual(verify_deployed_app.bugs_from([]), [])
        self.assertLessEqual(len(verify_deployed_app.bugs_from(failures * 10)), verify_deployed_app.MAX_BUGS)


if __name__ == "__main__":
    unittest.main()
