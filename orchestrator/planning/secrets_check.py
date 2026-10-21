import json

from planning import secrets_marker, triage


class SecretsUnreadable(Exception):
    pass


def present_names(run, app_repo):
    out = run(["secret", "list", "--repo", app_repo, "--json", "name"])
    if out.returncode != 0:
        raise SecretsUnreadable("could not read the names of the app's GitHub secrets, so the request's secrets cannot be confirmed")
    return {x.get("name") for x in json.loads(out.stdout or "[]")}


def missing_secrets(needed, have):
    return [x for x in needed if x["name"] not in have]


def request_comment(needed, missing, app_repo, retry="remove the Intake's label and add it again"):
    text = triage.secrets_request(missing, app_repo, retry) if missing else "This request uses " + ", ".join(x["name"] for x in needed) + " (set)."
    return text + "\n\n" + secrets_marker.secrets_marker(needed)


def waiting_message(missing, app_repo, retry):
    return "waiting for " + ", ".join(x["name"] for x in missing) + f" to be set on {app_repo} (the commands are on the Intake issue); then {retry}"


def secrets_note(needed):
    names = ", ".join(x["name"] for x in needed)
    return ("\n\nSecrets (set by the owner, already in the running app's environment as process.env.<NAME>; you never see a value): " + names
            + ". Read each in exactly one place, the call to the service; fail closed (a clear error, the feature off) when it is missing; never log it, "
              "return it or send it anywhere else. In the same commit add each name and what it is for (no values) to `secrets.json` at the repo root as "
              '{"secrets": [{"name": "...", "purpose": "..."}]}. In tests, stub the service: the test environment has no real value.')
