import json

from shared import github

REQUIRED = ("unit", "starter")


def missing_checks(repo, token):
    out = github.run(["api", f"repos/{repo}/branches/main/protection"], token)
    if out.returncode != 0:
        return list(REQUIRED)
    required = (json.loads(out.stdout or "{}").get("required_status_checks") or {}).get("contexts") or []
    return [name for name in REQUIRED if name not in required]


def problem(repo, token):
    missing = missing_checks(repo, token)
    return f"branch protection on `main` does not require {', '.join(missing)}; a Factory Change does not start until it does" if missing else None
