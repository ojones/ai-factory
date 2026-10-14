#!/usr/bin/env python3
"""Template sync: a Starter Template improvement reaches the Managed Apps that were seeded before it.

An app is seeded once from `templates/starter/`. Without this, a better linter, test script or default never reaches an app that
already exists, and the learning loop's fixes only help new apps. Each app carries `.factory-template`, the ai-factory commit its
template files correspond to (App Staging writes it; an older app has none, so the commit current when its repo was created is
used). When the template has changed since then, this files one Update Intake per app that gives the coder the template's own diff
and starts it. The coder applies it to the app's corresponding files, keeps the app's own code, and writes the new commit into
`.factory-template`.

  python3 template_sync.py       (run from a full checkout of ai-factory; on a push that touches templates/starter, daily, or by hand)

Only files an Agent may change are synced. The protected ones (.github/, fly.toml, fly/, feature-flags.ts) are listed in the
Intake as "not applied" for a person. One Intake per app and target commit (a failed one is not refiled; its fix request is), and one
open at a time per app. Env: FACTORY_PAT, FACTORY_GH_TOKEN, GITHUB_REPOSITORY.
"""
import base64
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_run as b  # noqa: E402
import production_feedback as pf  # noqa: E402

LABEL = "template-sync"
STAMP = ".factory-template"
TEMPLATE = "templates/starter/"
SKIP = ("package-lock.json",)  # the coder regenerates it with npm install
MAX_DIFF_CHARS = 20000
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


# --- pure logic (unit-tested) -------------------------------------------------


def parse_name_status(text):
    """[(status, path)] with the template prefix removed, from `git diff --name-status -M` output."""
    out = []
    for line in (text or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            out.append((parts[0][0], parts[-1].removeprefix(TEMPLATE)))
    return out


def orchestrator_applied(changes):
    """The changed paths the Build Run copies itself (b.TEMPLATE_FILES_APPLIED_BY_ORCHESTRATOR), which no Agent applies or reports."""
    return [path for _, path in changes if path in b.TEMPLATE_FILES_APPLIED_BY_ORCHESTRATOR]


def split_changes(changes):
    """(applicable, protected, ignored) path lists from [(status, path)]. Files the Orchestrator applies itself are in none of them."""
    applicable, protected, ignored = [], [], []
    for status, path in changes:
        if path in b.TEMPLATE_FILES_APPLIED_BY_ORCHESTRATOR:
            continue
        if path in SKIP:
            ignored.append(path)
        elif b.protected_violations([path]):
            protected.append(path)
        else:
            applicable.append((status, path))
    return applicable, protected, ignored


def stamp_value(text):
    value = (text or "").strip()
    return value if SHA_RE.match(value) else None


def should_sync(applicable, target, stamp, filed_titles, open_for_app, app):
    """True when there is something to apply, the app is behind, this target was not already filed, and nothing is open."""
    if not applicable or stamp == target or open_for_app:
        return False
    return not any(f"[sync {target[:7]}]" in t for t in filed_titles)


def sync_request(app, target, base, applicable, protected, diff_text, by_orchestrator=()):
    files = "\n".join(f"- {s} `{p}`" for s, p in applicable)
    parts = [f"The Factory's Starter Template changed after `{app}` was seeded. Apply these changes to the app's corresponding files "
             f"(the template's `backend/`, `frontend/` and root files map to the same paths in this repo).",
             "", f"Template commit this app is being brought up to: `{target}` (it was last synced to `{base[:12]}`).", "",
             "Files changed in the template:", files]
    if by_orchestrator:
        parts += ["", "Already applied by the Orchestrator before you start (do not touch them): " + ", ".join(f"`{p}`" for p in by_orchestrator)]
    if protected:
        parts += ["", "Not applied here, because Agents may not change them (a person must): " + ", ".join(f"`{p}`" for p in protected)]
    clipped = diff_text if len(diff_text) <= MAX_DIFF_CHARS else diff_text[:MAX_DIFF_CHARS] + "\n... (clipped; read the rest from the Factory repo)"
    parts += ["", "The template's own diff (from the Factory repository, not user input):", "", "```diff", clipped, "```", "",
              "How to apply it: keep the app's own code and behaviour. Where the app has changed the same file, merge by intent instead of "
              "overwriting. If `package.json` changed, run `npm install`. Run `npm run format` first, then `npm run check` and `npm test`. "
              f"Finally write the single line `{target}` to a file named `{STAMP}` at the repository root. This is a tooling change that "
              "users cannot see, so it needs no feature flag; do not add behaviour."]
    return "\n".join(parts)


# --- git and GitHub (not unit-tested) -----------------------------------------


def git(*args):
    return b.sh(["git", *args], cwd=b.FACTORY_DIR, check=False).stdout


def app_stamp(owner, app, pat):
    out = b.sh(["gh", "api", f"repos/{owner}/{app}/contents/{STAMP}", "--jq", ".content"], env={**os.environ, "GH_TOKEN": pat}, check=False)
    if out.returncode != 0:
        return None
    try:
        return stamp_value(base64.b64decode(out.stdout).decode())
    except ValueError:
        return None


def baseline(owner, app, pat):
    """The ai-factory commit the app's template files correspond to: its stamp, else the commit current when its repo was created."""
    stamp = app_stamp(owner, app, pat)
    if stamp and git("cat-file", "-t", stamp).strip() == "commit":
        return stamp
    created = b.sh(["gh", "api", f"repos/{owner}/{app}", "--jq", ".created_at"], env={**os.environ, "GH_TOKEN": pat}, check=False).stdout.strip()
    return git("rev-list", "-n1", f"--before={created}", "HEAD").strip() if created else ""


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    owner, token, pat = repo.split("/")[0], os.environ["FACTORY_GH_TOKEN"], os.environ["FACTORY_PAT"]
    target = git("rev-parse", "HEAD").strip()
    for app in pf.managed_apps(repo, token):
        try:
            base = baseline(owner, app, pat)
            if not base or base == target:
                continue
            changes = parse_name_status(git("diff", "--name-status", "-M", base, target, "--", TEMPLATE))
            applicable, protected, _ = split_changes(changes)
            by_orchestrator = orchestrator_applied(changes)
            titles = [i["title"] for i in pf.intakes_with(repo, token, app, LABEL, "all")]
            open_now = pf.intakes_with(repo, token, app, LABEL, "open")
            if not should_sync(applicable or by_orchestrator, target, app_stamp(owner, app, pat), titles, open_now, app):
                continue
            paths = [p for _, p in applicable]
            diff_text = git("diff", "-M", base, target, "--", *[TEMPLATE + p for p in paths]) if paths else ""  # no paths would diff everything
            n = pf.file_intake(repo, token, pat, app, f"{app}: template sync [sync {target[:7]}]",
                               sync_request(app, target, base, applicable, protected, diff_text, by_orchestrator), LABEL,
                               "Filed and started by the Orchestrator to bring an app up to the Starter Template",
                               "Started automatically: the Starter Template changed after this app was seeded. The planner runs first.")
            b.log(f"{app}: template sync filed as #{n} ({len(paths)} file(s), {len(protected)} protected)")
        except Exception as e:  # noqa: BLE001 - one app's failure never stops the others
            b.log(f"{app}: template sync failed: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
