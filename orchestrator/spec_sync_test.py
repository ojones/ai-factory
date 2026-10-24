import re
import subprocess
import unittest
from pathlib import Path

import yaml
from flow_spec_test import expand

ROOT = Path(__file__).resolve().parent.parent
SPECS = ["ARCHITECTURE.md", "GLOSSARY.md", "docs/flow-spec.md", "docs/invariants.md"]
NOT_REPO_FILES = {
    "fly.toml",
    "INTAKE.md",
    "flags.json",
    "state.json",
    ".factory-template",
    "secrets.json",
    "history.json",
    "index.html",
    "artifacts/progress.json",
    "retrospective-facts.json",
    "name_test.py",
    ".scratch/orchestrator-spec/issues/",
}
NOT_LIMIT_KEYS = {"py"}
EXAMPLE_LABELS = {"flag:version-endpoint"}
CODE_FOLDERS = ("orchestrator/", "agents/", ".github/", "templates/", "infra/")
CODE_SUFFIXES = (".py", ".yml", ".yaml", ".sh", ".json", ".ts", ".mjs")
LABEL_MENTION = re.compile(r"`([a-z][a-z0-9:\-]*)` label|labell?(?:ed|s|ing)? (?:it )?`([a-z][a-z0-9:\-]*)`|label `([a-z][a-z0-9:\-]*)`")
QUOTED_VALUE = re.compile(r"`?\b([a-z][a-z_]+)`? ?(?:=|\(|: ) ?(\d+(?:\.\d+)?)\b")
PATH_TOKEN = re.compile(r"^[\w.\-]+(/[\w.\-]+)*(/|\.(py|md|yml|yaml|json|mjs|sh|ts|tsx|toml))$")


def spec_text(name):
    return (ROOT / name).read_text(encoding="utf-8")


def all_spec_text():
    return {name: spec_text(name) for name in SPECS}


def invariant_table():
    return spec_text("docs/invariants.md").split("\n## ", 1)[0]


def defined_invariants():
    return set(re.findall(r"^\| (INV-\d\d) \|", invariant_table(), re.M))


def cited(pattern):
    return {(name, found) for name, text in all_spec_text().items() for found in re.findall(pattern, text)}


def invariant_steps():
    rows = re.findall(r"^\| (INV-\d\d) \|.*\| ([^|]+) \|$", invariant_table(), re.M)
    return {inv: expand(step) for inv, step in rows}


def index_invariants():
    found = {}
    for line in spec_text("docs/flow-spec.md").split("## Step index", 1)[1].splitlines():
        row = re.match(r"\| (\d+\.\d+(?:-\d+\.\d+)?) \|(.*)\|$", line)
        for step in expand(row.group(1)) if row else []:
            found[step] = set(re.findall(r"INV-\d\d", row.group(2)))
    return found


def limits():
    return yaml.safe_load((ROOT / "agents/profiles.yml").read_text(encoding="utf-8"))["limits"]


def flat_limits():
    flat = {}
    for key, value in limits().items():
        flat.update(value if isinstance(value, dict) else {})
        flat[key] = value
    return flat


def quoted_values():
    return {(name, key, number) for name, text in all_spec_text().items() for key, number in QUOTED_VALUE.findall(text)}


def labels_named():
    found = set()
    for name, text in all_spec_text().items():
        found |= {(name, next(g for g in m.groups() if g)) for m in LABEL_MENTION.finditer(text)}
    return found


def code_text():
    files = [f for f in tracked_files() if f.startswith(tuple("/" + c for c in CODE_FOLDERS)) and f.endswith(CODE_SUFFIXES)]
    return "\n".join((ROOT / f.lstrip("/")).read_text(encoding="utf-8", errors="ignore") for f in files)


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return ["/" + line for line in out.splitlines()]


def path_tokens():
    tokens = {(name, tok) for name, text in all_spec_text().items() for tok in re.findall(r"`([^`\s]+)`", text)}
    return {(name, tok) for name, tok in tokens if PATH_TOKEN.match(tok) and tok not in NOT_REPO_FILES}


def path_exists(token, files):
    needle = "/" + token.removeprefix("./")
    if needle.endswith("/"):
        return any(needle in f for f in files)
    return any(f.endswith(needle) for f in files)


class SpecSync(unittest.TestCase):
    def test_every_cited_invariant_is_defined(self):
        missing = sorted(f"{name}: {inv}" for name, inv in cited(r"\bINV-\d\d\b") if inv not in defined_invariants())
        self.assertEqual(missing, [])

    def test_each_invariant_is_listed_in_the_index_row_of_every_step_it_names(self):
        index = index_invariants()
        missing = sorted(f"{inv} not in step {step}" for inv, steps in invariant_steps().items() for step in steps if inv not in index.get(step, set()))
        self.assertEqual(missing, [])

    def test_every_invariant_is_listed_by_some_step(self):
        listed = set().union(*index_invariants().values())
        self.assertEqual(sorted(defined_invariants() - listed), [])

    def test_invariant_numbers_run_from_one_without_gaps(self):
        numbers = sorted(int(inv[4:]) for inv in defined_invariants())
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))

    def test_every_limit_the_specs_name_exists_in_profiles(self):
        named = {(name, key) for name, key in cited(r"\blimits\.([a-z]+(?:_[a-z]+)*)\b")}
        missing = sorted(f"{name}: limits.{key}" for name, key in named if key not in limits() and key not in NOT_LIMIT_KEYS)
        self.assertEqual(missing, [])

    def test_every_number_the_specs_quote_beside_a_limit_equals_its_value(self):
        flat = flat_limits()
        wrong = sorted(
            f"{name}: {key} {number} but profiles.yml has {flat[key]}"
            for name, key, number in quoted_values()
            if key in flat and float(number) != float(flat[key])
        )
        self.assertEqual(wrong, [])

    def test_every_label_the_specs_name_appears_in_the_code_or_workflows(self):
        code = code_text()
        missing = sorted(f"{name}: {label}" for name, label in labels_named() if label not in code and label not in EXAMPLE_LABELS)
        self.assertEqual(missing, [])

    def test_every_path_the_specs_name_exists_in_the_repo(self):
        files = tracked_files()
        missing = sorted(f"{name}: {tok}" for name, tok in path_tokens() if not path_exists(tok, files))
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
