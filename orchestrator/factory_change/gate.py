import os
import shutil
import sys
from pathlib import Path

from shared import config

from factory_change import markers, prove_reproduction, tiers, vet_change


def changed_test_files(changes):
    return [p for p, c in changes.items() if c["status"] != "D" and vet_change.TEST_FILE.search(p)]


def copy_tests(head_root, main_root, paths):
    for path in paths:
        target = Path(main_root) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(head_root) / path, target)


def named_reproduction_problem(main_root, head_root, name, changes):
    if not prove_reproduction.valid_name(name):
        return "the change names no valid reproduction test"
    copy_tests(head_root, main_root, changed_test_files(changes))
    return prove_reproduction.failure_on_main(main_root, name) or prove_reproduction.pass_on_branch(head_root, name)


def reproduction_problem(main_root, head_root, body, changes):
    return named_reproduction_problem(main_root, head_root, markers.read(body, markers.REPRODUCTION), changes)


def scope_problem(head_root, limits, base):
    changes = vet_change.read_changes(head_root, base)
    return vet_change.problem(changes, limits, vet_change.patches_of(head_root, changes, base))


def tier_problem(head_root, body, base):
    paths = list(vet_change.read_changes(head_root, base))
    actual = tiers.merge_tier(paths)
    return None if actual == markers.read(body, markers.TIER) else f"the pull request says tier {markers.read(body, markers.TIER)} but its files make it {actual}"


def prove(main_root, head_root, body, base):
    changes = vet_change.read_changes(head_root, base)
    return reproduction_problem(main_root, head_root, body, changes) or scope_problem(head_root, config.load()["limits"], base)


def merge_check(head_root, body, base):
    paths = list(vet_change.read_changes(head_root, base))
    if tiers.merge_tier(paths) != tiers.TIER_ONE:
        return "only a change whose files all merge on green merges itself; a person merges this one"
    return tier_problem(head_root, body, base) or scope_problem(head_root, config.load()["limits"], base)


def main(argv):
    body, base = os.environ.get("PR_BODY", ""), os.environ.get("BASE_REF", "origin/main...HEAD")
    problem = {"prove": lambda: prove(argv[2], argv[3], body, base), "merge-check": lambda: merge_check(argv[2], body, base)}[argv[1]]()
    print(problem or "ok")
    return 1 if problem else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
