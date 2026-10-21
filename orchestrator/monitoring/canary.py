#!/usr/bin/env python3
import os
import sys

from shared import alert_issue, config, github, provider, run_stops

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


def model_status_cache(cfg):
    base, key = cfg["provider"]["base_url"], os.environ["DEEPINFRA_API_KEY"]
    cache = {}

    def status_of(model):
        if model not in cache:
            try:
                cache[model] = provider.model_status(base, key, model)
            except run_stops.ProviderBlocked:
                cache[model] = "unknown"
        return cache[model]
    return status_of, cache


def main():
    cfg = config.load()
    status_of, cache = model_status_cache(cfg)
    found = drift(cfg, status_of)
    body = render(found, len(cache))
    print(body)
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["FACTORY_GH_TOKEN"]
    github.ensure_label(repo, LABEL, token, "b60205", "A configured model is no longer served")
    alert_issue.sync_alert_issue(repo, token, LABEL, found, body, "A configured model is no longer served", "Every configured model answers again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
