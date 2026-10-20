import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import prompts, starter_template  # noqa: E402

from build_run import gate_release  # noqa: E402


class Guards(unittest.TestCase):
    def test_protected_paths(self):
        bad = starter_template.protected_violations([".github/workflows/deploy-fly.yml", "fly.toml", "fly/provision.sh",
                                      "backend/src/feature-flags.ts", "INTAKE.md", "backend/src/app.ts",
                                      "flags.json", "backend/src/routes/notes.ts"])
        self.assertEqual(len(bad), 5)
        self.assertNotIn("flags.json", bad)

    def test_release_gate_needs_all_four_on_the_same_sha(self):
        self.assertTrue(gate_release.release_gate(True, True, True, True, "abc", "abc"))
        for i in range(4):
            args = [True] * 4
            args[i] = False
            self.assertFalse(gate_release.release_gate(*args, "abc", "abc"))
        self.assertFalse(gate_release.release_gate(True, True, True, True, "abc", "def"))

    def test_render_replaces_and_rejects_leftovers(self):
        self.assertEqual(prompts.render("hi {{a}} {{a}}", {"a": 1}), "hi 1 1")
        with self.assertRaises(ValueError):
            prompts.render("hi {{a}} {{b}}", {"a": 1})


if __name__ == "__main__":
    unittest.main()
