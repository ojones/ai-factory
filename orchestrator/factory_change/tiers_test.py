import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from factory_change import tiers  # noqa: E402


class Tiers(unittest.TestCase):
    def test_a_path_is_tier_one_tier_two_or_never(self):
        self.assertEqual(tiers.classify("orchestrator/planning/plan_run.py"), tiers.TIER_ONE)
        self.assertEqual(tiers.classify("agents/prompts/coder.md"), tiers.TIER_ONE)
        self.assertEqual(tiers.classify("orchestrator/build_run/run.py"), tiers.TIER_TWO)
        self.assertEqual(tiers.classify("orchestrator/retrospective/close_child.py"), tiers.TIER_TWO)
        self.assertEqual(tiers.classify("orchestrator/factory_change/tiers.py"), tiers.TIER_TWO)
        self.assertEqual(tiers.classify(".github/workflows/factory-checks.yml"), tiers.NEVER)
        self.assertEqual(tiers.classify("orchestrator/style_baseline.json"), tiers.NEVER)
        self.assertEqual(tiers.classify("README.md"), tiers.NEVER)
        self.assertEqual(tiers.classify("orchestrator/../.github/x.yml"), tiers.NEVER)

    def test_a_change_takes_the_strictest_tier_of_its_files(self):
        self.assertEqual(tiers.merge_tier(["orchestrator/bugs/route_bug.py"]), tiers.TIER_ONE)
        self.assertEqual(tiers.merge_tier(["orchestrator/bugs/route_bug.py", "orchestrator/try_fix/route.py"]), tiers.TIER_TWO)
        self.assertEqual(tiers.merge_tier(["orchestrator/bugs/route_bug.py", "pyproject.toml"]), tiers.NEVER)

    def test_tiers_are_mixed_only_when_both_kinds_are_present(self):
        self.assertTrue(tiers.mixes_tiers(["orchestrator/bugs/route_bug.py", "orchestrator/try_fix/route.py"]))
        self.assertFalse(tiers.mixes_tiers(["orchestrator/try_fix/route.py", "orchestrator/retrospective/x.py"]))

    def test_the_prompt_path_is_found(self):
        self.assertTrue(tiers.touches_prompt_path(["agents/prompts/reviewer.md"]))
        self.assertFalse(tiers.touches_prompt_path(["orchestrator/bugs/route_bug.py"]))

    def test_the_planner_is_told_the_control_path(self):
        text = tiers.tier_two_paths_text()
        self.assertIn("`orchestrator/try_fix/*`", text)
        self.assertIn("`agents/profiles.yml`", text)


if __name__ == "__main__":
    unittest.main()
