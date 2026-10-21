import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = (ROOT / "docs/module-notes.md").read_text()


def documented_files():
    found, directory = [], ""
    for kind, name in re.findall(r"^(##+) (\S+)", NOTES.split("## Rationale that used to sit in comments")[0], re.M):
        if kind == "##":
            directory = name
        elif kind == "###":
            found.append(ROOT / directory / name)
    return found


def rationale_files():
    section = NOTES.split("## Rationale that used to sit in comments")[1]
    return [ROOT / name for name in re.findall(r"^### (\S+\.py)$", section, re.M)]


class ModuleNotes(unittest.TestCase):
    def test_every_module_with_notes_exists(self):
        missing = [str(p.relative_to(ROOT)) for p in documented_files() + rationale_files() if not p.exists()]
        self.assertEqual(missing, [], "module-notes.md describes a file that no longer exists")


if __name__ == "__main__":
    unittest.main()
