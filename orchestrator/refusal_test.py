# A refusal is an ending of its own: not a failure to retry or learn from (planning/triage.py decides it; the Build Run and the retrospective treat it).
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_run as b  # noqa: E402
import retrospective as pm  # noqa: E402
from shared import outcomes  # noqa: E402


class Ending(unittest.TestCase):
    def test_a_refusal_is_not_a_failure_to_retry_or_learn_from(self):
        self.assertFalse(pm.wants_fix_request({"outcome": "refused"}, {}))
        self.assertFalse(pm.records_stuck_issue("refused"))
        self.assertNotIn("refused", outcomes.OK)
        self.assertIn("refused", b.OUTCOME_TITLES)
        self.assertTrue(issubclass(b.Refused, Exception))


if __name__ == "__main__":
    unittest.main()
