import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import github  # noqa: E402

from factory_change import protection  # noqa: E402


def answer(returncode, doc=None):
    return mock.Mock(return_value=SimpleNamespace(returncode=returncode, stdout=json.dumps(doc or {}), stderr=""))


class Protection(unittest.TestCase):
    def problem(self, run):
        with mock.patch.object(github, "run", run):
            return protection.problem("o/f", "pat")

    def test_protection_requiring_the_checks_passes(self):
        self.assertIsNone(self.problem(answer(0, {"required_status_checks": {"contexts": ["unit", "starter"]}})))

    def test_no_protection_or_a_missing_check_blocks_the_start(self):
        self.assertIn("unit, starter", self.problem(answer(1)))
        self.assertIn("starter", self.problem(answer(0, {"required_status_checks": {"contexts": ["unit"]}})))
        self.assertIn("unit, starter", self.problem(answer(0, {})))


if __name__ == "__main__":
    unittest.main()
