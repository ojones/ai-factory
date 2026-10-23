#!/usr/bin/env python3
import re

SECRET_PATTERNS = (
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("a GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}")),
    ("an AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("an API key (sk- style)", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("a Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("a bearer or JWT token", re.compile(r"\b(?:Bearer\s+)?eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("a password or secret assignment", re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*[\"']?[^\s\"']{8,}")),
)
PLACEHOLDER = re.compile(r"(?i)^(?:<.*>|\$\{.*\}|\{\{.*\}\}|x{4,}|\*{4,}|your[-_ ]|changeme|example|placeholder|todo|none|null|true|false)")

RESERVED_SECRET_NAMES = ("FLY_API_TOKEN", "GROWTHBOOK_CLIENT_KEY", "GROWTHBOOK_ADMIN_PAT", "PREVIEW_TOKEN", "PREVIEW_MASTER_SECRET", "FACTORY_PAT",
                         "DEEPINFRA_API_KEY", "NODE_ENV", "PORT", "PATH", "HOME")
SECRET_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
DIFF_SECRET_KINDS = ("a private key", "a GitHub token", "an AWS access key", "an API key (sk- style)", "a Slack token", "a bearer or JWT token")

CATEGORIES = ("payments", "secrets", "personal_data", "external_api", "outside_stack")
POSSIBLE_IF = {
    "payments": "Taking payments needs a payment provider account and keys, which the Factory does not hold. Build the part that needs no payment, or add the integration by hand.",
    "secrets": "The request would have the Factory create or hold a secret itself. The Factory holds none and the repositories are public. Have the owner set the key as a GitHub Actions secret, or use a feature that needs no key.",
    "personal_data": "The request stores or shows personal data about real people. The repositories are public and the Factory has no data-protection setup. Use made-up sample data instead.",
    "external_api": "The request depends on an outside service that cannot be used with a key the owner sets (it needs payment or the Factory's own account). Name a service the owner can key, or use a free one.",
    "outside_stack": "The request needs something outside Express, React and free npm dependencies (another runtime, a database server, a mobile app).",
}


def find_secrets(text):
    kinds = []
    for kind, pattern in SECRET_PATTERNS:
        for m in pattern.finditer(text or ""):
            value = m.group(0).split("=")[-1].split(":")[-1].strip(" \"'")
            if kind == "a password or secret assignment" and PLACEHOLDER.match(value):
                continue
            if kind not in kinds:
                kinds.append(kind)
            break
    return kinds


def secret_name_problem(name):
    if not isinstance(name, str) or not SECRET_NAME_RE.match(name):
        return f"{name!r} is not a valid secret name (capitals, digits and underscores, starting with a letter, such as OPENWEATHER_API_KEY)"
    if name in RESERVED_SECRET_NAMES or name.startswith(("GITHUB_", "FLY_")):
        return f"{name} is one of the Factory's own names and cannot be an app secret"
    return None


def diff_secrets(patch):
    added = "\n".join(l[1:] for l in (patch or "").splitlines() if l.startswith("+") and not l.startswith("+++"))
    return [k for k in find_secrets(added) if k in DIFF_SECRET_KINDS]


def secrets_request(secrets, app_repo, retry="add `proceed-with-change` again"):
    lines = ["This request needs a third-party secret, which no Agent may hold and the public repositories cannot store. Nothing was built.", "",
             "Set each one as a GitHub Actions secret on the app's repository (the command prompts for the value, so it never appears in an issue, a log or a commit):", ""]
    for x in secrets:
        lines += [f"- **{x['name']}**: {x['purpose']}", f"  `gh secret set {x['name']} -R {app_repo}`"]
    lines += ["", "Use a restricted key with a spending limit at the provider if it offers one. When they are set, " + retry + "; the build "
              "starts only once every name exists, and the deploy copies them to the running app."]
    return "\n".join(lines)


def secret_refusal(kinds):
    return ("The request contains " + " and ".join(kinds) + ". Intake issues and the app's repository are public, so it is already visible: "
            "rotate or revoke it now. Nothing was built. Edit the request to remove the value (describe what it is for instead), then remove "
            "the Intake's label and add it again.")


def feasibility(plan):
    f = plan.get("feasibility") if isinstance(plan, dict) else None
    if not isinstance(f, dict) or f.get("status") != "blocked":
        return False, "", [], ""
    category = f.get("category") if f.get("category") in CATEGORIES else "outside_stack"
    reasons = [str(r).strip()[:300] for r in (f.get("reasons") or []) if str(r).strip()][:5]
    possible = str(f.get("possible_if") or "").strip()[:400] or POSSIBLE_IF[category]
    return True, category, reasons, possible


def refusal_text(category, reasons, possible_if):
    lines = [f"The Factory cannot build this as asked ({category.replace('_', ' ')})."]
    lines += [f"- {r}" for r in reasons]
    lines += ["", possible_if, "", "Nothing was built and nothing was retried. Change the request (for example to the part that needs none of this)."]
    return "\n".join(lines)
