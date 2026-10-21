import re
import sys
from pathlib import Path

from shared.shell import sh

NAME = re.compile(r"[a-z_][a-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+")
NOT_FOUND = re.compile(r"ModuleNotFoundError|ImportError|_FailedTest|AttributeError: (module|type object)|Ran 0 tests")
FAILURE = re.compile(r"^(FAIL|ERROR): ", re.M)


def valid_name(name):
    return bool(NAME.fullmatch(name or ""))


def classify_run(returncode, output):
    if returncode == 0:
        return "passes"
    if NOT_FOUND.search(output) or not FAILURE.search(output):
        return "missing"
    return "fails"


def run_named_test(root, name, timeout=600):
    run = sh([sys.executable, "-m", "unittest", name], cwd=Path(root) / "orchestrator", check=False, timeout=timeout)
    return classify_run(run.returncode, run.stdout + run.stderr)


def failure_on_main(root, name):
    state = run_named_test(root, name)
    return None if state == "fails" else f"the reproduction {name} {'does not exist' if state == 'missing' else 'passes'} on main; it has to fail there before an Agent runs"


def pass_on_branch(root, name):
    state = run_named_test(root, name)
    return None if state == "passes" else f"the reproduction {name} {'does not exist' if state == 'missing' else 'still fails'} on the branch"
