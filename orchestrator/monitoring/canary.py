#!/usr/bin/env python3
import json
import os
import sys

from shared import config, github, provider, run_stops, shell

LABEL = "model-drift"


def drift(cfg, status_of):
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
    cfg = config.load()
    base, key = cfg["provider"]["base_url"], os.environ["DEEPINFRA_API_KEY"]
    cache = {}

    def status_of(model):
        if model not in cache:
            try:
                cache[model] = provider.model_status(base, key, model)
            except run_stops.ProviderBlocked:
                cache[model] = "unknown"
        return cache[model]

    found = drift(cfg, status_of)
    body = render(found, len(cache))
    print(body)
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["FACTORY_GH_TOKEN"]
    github.ensure_label(repo, LABEL, token, "b60205", "A configured model is no longer served")
    env = {**os.environ, "GH_TOKEN": token}
    open_issues = json.loads(shell.sh(["gh", "issue", "list", "--repo", repo, "--label", LABEL, "--state", "open", "--json", "number,body"], env=env).stdout or "[]")
    if not found:
        for i in open_issues:
            shell.sh(["gh", "issue", "close", str(i["number"]), "--repo", repo, "--comment", "Every configured model answers again."], env=env, check=False)
    elif not open_issues:
        shell.sh(["gh", "issue", "create", "--repo", repo, "--label", LABEL, "--title", "A configured model is no longer served", "--body", body], env=env, check=False)
    elif (open_issues[0].get("body") or "").strip() != body.strip():
        shell.sh(["gh", "issue", "edit", str(open_issues[0]["number"]), "--repo", repo, "--body", body], env=env, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
