import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import postmortem as pm  # noqa: E402


def write_findings(work, n, summaries):
    (Path(work) / f"findings-{n}.json").write_text(json.dumps(
        {"round": n, "blocking": [{"source": "reviewer", "summary": s, "evidence": ""} for s in summaries], "minor": []}))


STATE = {"app": "demo", "outcome": "round_limit", "message": "4 review rounds used without a clean pass",
         "run_url": "http://run", "issue_number": "7", "spent_usd": 1.5, "commits": ["a"],
         "blocking": [{"summary": "The kill switch is mounted after the new route"}],
         "stages": [{"stage": "Coder", "round": "1", "verdict": "pushed", "cost_usd": 0.2, "usage": {"seconds": 120, "calls": 30}},
                    {"stage": "Release", "round": "-", "verdict": "x", "cost_usd": 0, "usage": None}]}


class Facts(unittest.TestCase):
    def test_recurring_findings_survive_rewording_and_drive_the_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_findings(tmp, 1, ["Kill switch is mounted after the new route", "Missing flag"])
            write_findings(tmp, 2, ["The kill switch mounted after new route!"])
            facts = pm.collect_facts(tmp, STATE)
        self.assertEqual(len(facts["rounds"]), 2)
        self.assertEqual(len(facts["recurring_findings"]), 1)
        self.assertEqual(facts["stages"][0]["seconds"], 120)
        self.assertIsNone(facts["stages"][1]["seconds"])
        again = dict(facts, spent_usd=9.9, run_url="other")
        self.assertEqual(pm.fingerprint(facts), pm.fingerprint(again))
        different = dict(facts, outcome="needs_human")
        self.assertNotEqual(pm.fingerprint(facts), pm.fingerprint(different))
        self.assertIn(pm.fingerprint(facts), pm.title_for(facts))
        self.assertIn("Recurred across rounds", pm.render_facts(facts))

    def test_no_findings_files_still_gives_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            facts = pm.collect_facts(tmp, STATE)
        self.assertEqual(facts["rounds"], [])
        self.assertEqual(facts["final_blocking"], ["The kill switch is mounted after the new route"])
        self.assertEqual(len(pm.fingerprint(facts)), 8)


class Minors(unittest.TestCase):
    def test_final_minor_comes_from_the_last_findings_file_and_titles_are_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "findings-1.json").write_text(json.dumps({"round": 1, "blocking": [], "minor": [{"summary": "old"}]}))
            (Path(tmp) / "findings-2.json").write_text(json.dumps({"round": 2, "blocking": [], "minor": [
                {"summary": "Flag todos-crud is declared but never used", "evidence": "flags.json:1", "file": "flags.json", "line": "1"}]}))
            facts = pm.collect_facts(tmp, dict(STATE, outcome="released"))
        self.assertEqual([m["summary"] for m in facts["final_minor"]], ["Flag todos-crud is declared but never used"])
        self.assertIn("Minor findings still open", pm.render_facts(facts))
        self.assertEqual(pm.minor_title("The flag todos-crud is declared but never used!").split("]")[0],
                         pm.minor_title("Flag todos-crud declared but never used").split("]")[0])


class Paths(unittest.TestCase):
    def test_only_prompts_template_orchestrator_and_docs_are_allowed(self):
        for ok in ("agents/prompts/coder.md", "templates/starter/AGENTS.md", "orchestrator/build_run.py", "STANDARDS.md"):
            self.assertTrue(pm.allowed_path(ok), ok)
        for bad in (".github/workflows/build-run.yml", "templates/starter/.github/workflows/build.yml",
                    "templates/starter/fly/provision.sh", "templates/starter/fly.toml", "README.md",
                    "agents/../.github/x.yml"):
            self.assertFalse(pm.allowed_path(bad), bad)


if __name__ == "__main__":
    unittest.main()
