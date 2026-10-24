import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from try_fix import event, group_fixes  # noqa: E402


def verdict(fp, app="demo", story=12, target="managed_app", source="build_run"):
    ev = event.make(source, "failure", app, "boom", fp, story=story)
    return {"key": ev["key"], "verdict": "fix", "target": target, "event": ev}


def keys(groups):
    return [[v["key"] for v in g] for g in groups]


class Group(unittest.TestCase):
    def test_events_on_one_story_and_target_are_one_group_led_by_the_first(self):
        a, b = verdict("a"), verdict("b", source="tester")
        self.assertEqual(keys(group_fixes.group([a, b])), [[a["key"], b["key"]]])

    def test_an_event_with_no_story_is_never_merged(self):
        a, b = verdict("a", story=None), verdict("b", story=None)
        self.assertEqual(keys(group_fixes.group([a, b])), [[a["key"]], [b["key"]]])

    def test_another_story_app_or_target_is_another_group(self):
        a = verdict("a")
        others = [verdict("b", story=13), verdict("c", app="other"), verdict("d", target="factory")]
        self.assertEqual(len(group_fixes.group([a, *others])), 4)

    def test_groups_keep_the_order_the_stories_first_appeared(self):
        a, b, c = verdict("a", story=1), verdict("b", story=2), verdict("c", story=1)
        self.assertEqual(keys(group_fixes.group([a, b, c])), [[a["key"], c["key"]], [b["key"]]])


if __name__ == "__main__":
    unittest.main()
