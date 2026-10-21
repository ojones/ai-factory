#!/usr/bin/env python3
import base64
import os
import re
import sys

from request import file_intake, find_intakes  # noqa: E402
from shared import app_state_record, config, console, shell, starter_template

LABEL = "template-sync"
STAMP = ".factory-template"
TEMPLATE = "templates/starter/"
SKIP = ("package-lock.json",)
MAX_DIFF_CHARS = 20000
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def parse_name_status(text):
    out = []
    for line in (text or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            out.append((parts[0][0], parts[-1].removeprefix(TEMPLATE)))
    return out


def orchestrator_applied(changes):
    return [path for _, path in changes if path in starter_template.TEMPLATE_FILES_OWNED_BY_ORCHESTRATOR]


def split_changes(changes):
    applicable, protected, ignored = [], [], []
    for status, path in changes:
        if path in starter_template.TEMPLATE_FILES_OWNED_BY_ORCHESTRATOR:
            continue
        if path in SKIP:
            ignored.append(path)
        elif starter_template.protected_violations([path]):
            protected.append(path)
        else:
            applicable.append((status, path))
    return applicable, protected, ignored


def stamp_value(text):
    value = (text or "").strip()
    return value if SHA_RE.match(value) else None


def should_sync(applicable, target, stamp, filed_titles, open_for_app, app):
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


def git(*args):
    return shell.sh(["git", *args], cwd=config.FACTORY_DIR, check=False).stdout


def app_stamp(owner, app, pat):
    out = shell.sh(["gh", "api", f"repos/{owner}/{app}/contents/{STAMP}", "--jq", ".content"], env={**os.environ, "GH_TOKEN": pat}, check=False)
    if out.returncode != 0:
        return None
    try:
        return stamp_value(base64.b64decode(out.stdout).decode())
    except ValueError:
        return None


def baseline(owner, app, pat):
    stamp = app_stamp(owner, app, pat)
    if stamp and git("cat-file", "-t", stamp).strip() == "commit":
        return stamp
    created = shell.sh(["gh", "api", f"repos/{owner}/{app}", "--jq", ".created_at"], env={**os.environ, "GH_TOKEN": pat}, check=False).stdout.strip()
    return git("rev-list", "-n1", f"--before={created}", "HEAD").strip() if created else ""


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    owner, token, pat = repo.split("/")[0], os.environ["FACTORY_GH_TOKEN"], os.environ["FACTORY_PAT"]
    target = git("rev-parse", "HEAD").strip()
    for app in app_state_record.managed_apps(repo, token):
        try:
            base = baseline(owner, app, pat)
            if not base or base == target:
                continue
            changes = parse_name_status(git("diff", "--name-status", "-M", base, target, "--", TEMPLATE))
            applicable, protected, _ = split_changes(changes)
            by_orchestrator = orchestrator_applied(changes)
            titles = [i["title"] for i in find_intakes.intakes_with(repo, token, app, LABEL, "all")]
            open_now = find_intakes.intakes_with(repo, token, app, LABEL, "open")
            if not should_sync(applicable or by_orchestrator, target, app_stamp(owner, app, pat), titles, open_now, app):
                continue
            paths = [p for _, p in applicable]
            diff_text = git("diff", "-M", base, target, "--", *[TEMPLATE + p for p in paths]) if paths else ""
            n = file_intake.file_update_app_intake(repo, token, pat, app, f"{app}: template sync [sync {target[:7]}]",
                               sync_request(app, target, base, applicable, protected, diff_text, by_orchestrator), LABEL,
                               "Filed and started by the Orchestrator to bring an app up to the Starter Template",
                               "Started automatically: the Starter Template changed after this app was seeded. The planner runs first.")
            console.log(f"{app}: template sync filed as #{n} ({len(paths)} file(s), {len(protected)} protected)")
        except Exception as e:  # noqa: BLE001 - one app's failure never stops the others
            console.log(f"{app}: template sync failed: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
