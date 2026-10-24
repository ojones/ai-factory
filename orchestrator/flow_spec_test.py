import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = (ROOT / "docs/flow-spec.md").read_text()


def diagram():
    return re.search(r"```mermaid\n(.*?)```", SPEC, re.S).group(1)


def expand(cell):
    out = set()
    for part in re.split(r"\s*,\s*", cell.strip()):
        rng = re.fullmatch(r"(\d+)\.(\d+)-\1\.(\d+)", part)
        if rng:
            out |= {f"{rng.group(1)}.{n}" for n in range(int(rng.group(2)), int(rng.group(3)) + 1)}
        elif re.fullmatch(r"\d+\.\d+", part):
            out.add(part)
        else:
            raise AssertionError(f"not a step ID or range: {part!r}")
    return out


EDGE_LINE = re.compile(r'^\s*(S\d+_\d+) (?:-->|-\.->)(?:\|"[^"]*"\|)? (S\d+_\d+)\s*$')


def edges():
    return [m.groups() for m in map(EDGE_LINE.match, diagram().split("\n")) if m]


def diagram_steps():
    declared = re.findall(r'\bS(\d+)_(\d+)(?:\["|\{"|\(\["|\("|\{")<b>(\d+\.\d+) ', diagram())
    return declared


def index_steps():
    ids = []
    for line in SPEC.split("## Step index", 1)[1].splitlines():
        m = re.match(r"\| (\d+\.\d+(?:-\d+\.\d+)?) \|", line)
        if m:
            ids.append(m.group(1))
    return ids


class FlowSpec(unittest.TestCase):
    def test_the_diagram_declares_each_step_once_and_the_label_matches_the_node_name(self):
        declared = diagram_steps()
        self.assertTrue(declared)
        ids = [label for _, _, label in declared]
        self.assertEqual(len(ids), len(set(ids)), "a step ID is declared twice in the diagram")
        for g, n, label in declared:
            self.assertEqual(f"{g}.{n}", label, f"node S{g}_{n} is labelled {label}")

    def test_every_edge_and_subgraph_refers_to_a_declared_step_or_group(self):
        declared = {f"S{g}_{n}" for g, n, _ in diagram_steps()}
        used = set(re.findall(r"\bS\d+_\d+\b", diagram()))
        self.assertEqual(used - declared, set(), "used but never declared")
        self.assertEqual(declared - used, set())
        groups = set(re.findall(r'subgraph (g\d+)\["', diagram()))
        self.assertEqual(groups, {f"g{n}" for n in range(1, 10)})

    def test_every_arrow_line_in_the_diagram_is_an_edge_the_checks_can_read(self):
        arrows = [line for line in diagram().split("\n") if re.search(r"-->|-\.->", line)]
        self.assertEqual(len(arrows), len(edges()))

    def test_the_diagram_uses_no_syntax_the_editor_previews_fail_on(self):
        self.assertNotRegex(diagram(), r"\be\d+@")
        self.assertNotRegex(diagram(), r"animate|linkStyle")

    def test_the_step_index_lists_exactly_the_diagram_steps(self):
        in_index = set()
        rows = index_steps()
        for cell in rows:
            ids = expand(cell)
            self.assertFalse(in_index & ids, f"{cell} repeats a step already in the index")
            in_index |= ids
        self.assertEqual(in_index, {label for _, _, label in diagram_steps()})

    def test_every_step_cited_in_the_docs_exists(self):
        known = {label for _, _, label in diagram_steps()}
        bad = []
        for path in [*(ROOT / "docs").glob("*.md"), ROOT / "ARCHITECTURE.md", ROOT / "GLOSSARY.md"]:
            for cited in re.findall(r"\bSTEP (\d+\.\d+)\b", path.read_text()):
                if cited not in known:
                    bad.append(f"{path.relative_to(ROOT)}: STEP {cited}")
        self.assertEqual(bad, [])

    def test_every_invariant_names_an_existing_step(self):
        known = {label for _, _, label in diagram_steps()}
        table = (ROOT / "docs/invariants.md").read_text().split("\n## ", 1)[0]
        rows = re.findall(r"^\| (INV-\d\d) \|.*\| ([^|]+) \|$", table, re.M)
        self.assertTrue(rows)
        for inv, step in rows:
            self.assertLessEqual(expand(step), known, f"{inv} names a step that does not exist: {step}")
        count = len(re.findall(r"^\| INV-\d\d \|", table, re.M))
        self.assertEqual(len(rows), count, "an invariant row has no Step cell")


if __name__ == "__main__":
    unittest.main()
