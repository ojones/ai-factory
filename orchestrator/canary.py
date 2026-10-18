#!/usr/bin/env python3
# Model canary: find out that a pinned model is gone before an unattended night run does.
#
# Models are retired and replaced. Each night this sends a one-token request (a fraction of a cent) for every model in agents/profiles.yml: each
# role's `model` and its `fallback_model`. If a primary is no longer served, the Build Run would fall back to the role's fallback (build_run.check_models)
# and the owner should choose a new pinned model; if a fallback is gone too, the next retirement stops runs. Either way one deduplicated
# `model-drift` issue in ai-factory says which role and which model, and it closes itself once every model answers again. Nothing is changed here.
#
# Env: DEEPINFRA_API_KEY, FACTORY_GH_TOKEN, GITHUB_REPOSITORY.
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_run as b  # noqa: E402
import update_intake  # noqa: E402

LABEL = "model-drift"


def drift(cfg, status_of):
    # [(role, model, kind)] for every configured model that is missing. kind is 'primary' or 'fallback'; `status_of(model)` returns ok, missing or unknown.
    out = []
    for role, profile in (cfg.get("roles") or {}).items():
        for kind, key in (("primary", "model"), ("fallback", "fallback_model")):
            model = profile.get(key)
            if model and status_of(model) == "missing":
                out.append((role, model, kind))
    return out


def render(found, checked):
    if not found:
        return f"All {checked} configured models answer."
    lines = ["The provider no longer serves these configured models:", "", "| Role | Model | Kind |", "|---|---|---|"]
    lines += [f"| {role} | `{model}` | {kind} |" for role, model, kind in found]
    lines += ["", "A Build Run uses a role's `fallback_model` when its primary is missing, and stops with the reason if the fallback is missing too. "
              "Choose a replacement in `agents/profiles.yml` and measure it with the benchmark (docs/benchmark-protocol.md)."]
    return "\n".join(lines)


def main():
    cfg = b.load_config()
    base, key = cfg["provider"]["base_url"], os.environ["DEEPINFRA_API_KEY"]
    cache = {}

    def status_of(model):
        if model not in cache:
            try:
                cache[model] = b.model_status(base, key, model)
            except b.ProviderBlocked:
                cache[model] = "unknown"  # an empty balance is its own alert (provider-blocked); it says nothing about this model
        return cache[model]

    found = drift(cfg, status_of)
    body = render(found, len(cache))
    print(body)
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["FACTORY_GH_TOKEN"]
    update_intake.ensure_label(repo, LABEL, token, "b60205", "A configured model is no longer served")
    env = {**os.environ, "GH_TOKEN": token}
    open_issues = json.loads(b.sh(["gh", "issue", "list", "--repo", repo, "--label", LABEL, "--state", "open", "--json", "number,body"], env=env).stdout or "[]")
    if not found:
        for i in open_issues:
            b.sh(["gh", "issue", "close", str(i["number"]), "--repo", repo, "--comment", "Every configured model answers again."], env=env, check=False)
    elif not open_issues:
        b.sh(["gh", "issue", "create", "--repo", repo, "--label", LABEL, "--title", "A configured model is no longer served", "--body", body], env=env, check=False)
    elif (open_issues[0].get("body") or "").strip() != body.strip():
        b.sh(["gh", "issue", "edit", str(open_issues[0]["number"]), "--repo", repo, "--body", body], env=env, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
