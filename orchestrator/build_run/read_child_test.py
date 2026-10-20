import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import run_stops  # noqa: E402

from build_run import read_child  # noqa: E402

FORM = ("### What should be built?\r\n\r\nA notes app\r\nwith tags\r\n\r\n"
        "### Cost cap override (USD)\r\n\r\n{cap}\r\n")


class Intake(unittest.TestCase):
    def test_default_cap(self):
        task, cap = read_child.parse_intake(FORM.format(cap="_No response_"), 2.0, 10.0)
        self.assertEqual((task, cap), ("A notes app\nwith tags", 2.0))

    def test_override_with_dollar_sign(self):
        self.assertEqual(read_child.parse_intake(FORM.format(cap="$3.5"), 2.0, 10.0)[1], 3.5)

    def test_rejects_over_ceiling_zero_and_garbage(self):
        for bad in ("10.01", "0", "abc"):
            with self.assertRaises(run_stops.NeedsHuman):
                read_child.parse_intake(FORM.format(cap=bad), 2.0, 10.0)

    def test_rejects_empty_task(self):
        with self.assertRaises(run_stops.NeedsHuman):
            read_child.parse_intake("### What should be built?\n\n_No response_\n", 2.0, 10.0)


if __name__ == "__main__":
    unittest.main()
