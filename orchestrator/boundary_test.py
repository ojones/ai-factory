import ast
import unittest
from pathlib import Path

ORCHESTRATOR = Path(__file__).resolve().parent
DOMAINS = ("request", "planning", "staging", "build_run", "flag_lifecycle", "retrospective", "try_fix", "bugs", "maintenance", "monitoring")
ALLOWED = {
    "request": set(),
    "planning": {"request"},
    "staging": {"request", "try_fix"},
    "build_run": {"request", "flag_lifecycle", "planning", "try_fix"},
    "flag_lifecycle": {"request"},
    "retrospective": {"try_fix", "request", "flag_lifecycle"},
    "try_fix": {"request", "planning"},
    "bugs": {"request", "try_fix"},
    "maintenance": {"request"},
    "monitoring": {"request"},
}


def imported_tops(path):
    tops = set()
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Import):
            tops |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            tops.add(node.module.split(".")[0])
    return tops


def files_of(folder):
    return sorted(p for p in (ORCHESTRATOR / folder).rglob("*.py")) if (ORCHESTRATOR / folder).is_dir() else []


def flat_modules():
    return {p.stem for p in ORCHESTRATOR.glob("*.py")}


class Boundaries(unittest.TestCase):
    def test_the_allowed_edges_name_only_known_domains_and_have_no_cycle(self):
        self.assertEqual(set(ALLOWED), set(DOMAINS))
        for targets in ALLOWED.values():
            self.assertLessEqual(targets, set(DOMAINS))
        done, active = set(), []

        def visit(domain):
            self.assertNotIn(domain, active, f"cycle: {' -> '.join(active + [domain])}")
            if domain in done:
                return
            active.append(domain)
            for target in ALLOWED[domain]:
                visit(target)
            active.pop()
            done.add(domain)

        for domain in DOMAINS:
            visit(domain)

    def test_shared_imports_no_domain_and_no_flat_module(self):
        forbidden = set(DOMAINS) | flat_modules()
        bad = {p.name: sorted(imported_tops(p) & forbidden) for p in files_of("shared") if imported_tops(p) & forbidden}
        self.assertEqual(bad, {})

    def test_a_domain_imports_only_shared_itself_and_the_domains_it_is_allowed(self):
        bad = []
        for domain in DOMAINS:
            for path in files_of(domain):
                extra = (imported_tops(path) & (set(DOMAINS) | flat_modules())) - {domain, "shared"} - ALLOWED[domain]
                if extra:
                    bad.append(f"{path.relative_to(ORCHESTRATOR)}: {sorted(extra)}")
        self.assertEqual(bad, [], "add the edge to ALLOWED and ARCHITECTURE.md (Code layout) only if it is deliberate")

    def test_every_folder_under_orchestrator_is_a_domain_or_shared(self):
        folders = {p.name for p in ORCHESTRATOR.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
        self.assertLessEqual(folders, set(DOMAINS) | {"shared"})


if __name__ == "__main__":
    unittest.main()
