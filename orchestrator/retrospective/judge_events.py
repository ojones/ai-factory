# STEP 6.7: judge failure events that have no Build Run (a scan of production errors, escaped defects, a failed staging check). One model call for the
# whole batch, from the event records and the App State only, under `retrospective_cost_cap_usd`; the answer goes through the same rules as a run's
# (event_verdicts.decide). Filing a ticket for a `fix` verdict is Try Fix's job (tickets 15c and 15d); this file only returns and prints the verdicts.
#
# Usage: python -m retrospective.judge_events <events.json> <verdicts.json>   (PYTHONPATH=orchestrator; DEEPINFRA_API_KEY)
import json
import os
import sys
from pathlib import Path

from shared import config, model_call
from shared.console import log
from try_fix import event

from retrospective import agent_run, event_verdicts

SYSTEM = (
    "You are the retrospective analyst for the AI Factory. You are given failure events found by scans of deployed Managed Apps. For each event decide "
    "whether it deserves a fix attempt. A failure is always fixed. A warning is fixed only if a fix would clearly help the app's users or stop a "
    "repeat, and you must give the reason; otherwise it is recorded. Name the target (`managed_app` if the app's code or request is wrong, `factory` "
    "if a prompt, the planner, the Starter Template or the orchestrator is) and a short cause. Answer with JSON only: "
    '{"events": [{"key": "...", "verdict": "fix|record", "target": "managed_app|factory", "cause": "...", "reason": "one sentence"}]}'
)


def ask_model(base_url, key, model, system, user):
    return json.dumps(model_call.json_chat(base_url, key, model, system, user))


def answer(events, cfg, key, ask=ask_model, app_state=None):
    # The model's entries for a batch, {event key: entry}. A model that cannot be reached, or whose answer is not JSON, gives none, and the
    # defaults apply: failures fix, warnings record.
    answer = {}
    # A batch of failures alone needs no opinion: every failure is fixed whatever is answered (event_verdicts.decide), so the model is asked only when a warning is in it.
    if any(e["severity"] == "warning" for e in events) and key and "retrospective" in cfg.get("roles", {}):
        role = cfg["roles"]["retrospective"]
        user = json.dumps({"events": events, "app_state": app_state or {}}, indent=2)
        try:
            raw = ask(cfg["provider"]["base_url"], key, role["model"], SYSTEM, user)
            answer = json.loads(raw)
        except Exception as e:  # noqa: BLE001 - judging never fails the scan
            log(f"could not judge the events with the model ({type(e).__name__}); using the defaults")
    return event_verdicts.parse(answer)


def judge(events, cfg, key, ask=ask_model, app_state=None, fixed_today=0):
    # Verdicts for a batch of events with no Build Run.
    return event_verdicts.decide(events, answer(events, cfg, key, ask, app_state), cfg.get("limits", {}), fixed_today)


def main(argv):
    events, cfg, parent = event.load(Path(argv[1])), config.load(), os.environ.get("DEEPINFRA_API_KEY")
    key, budget = agent_run.mint_agent(cfg, parent) if events and parent else (None, None)  # a credential limited to the cap, never the parent key
    verdicts = judge(events, cfg, key)
    if budget and os.environ.get("GITHUB_REPOSITORY") and os.environ.get("FACTORY_GH_TOKEN"):
        agent_run.record_agent_spend(budget, key, os.environ["GITHUB_REPOSITORY"], os.environ["FACTORY_GH_TOKEN"], os.environ.get("GITHUB_RUN_ID", "0"))
    Path(argv[2]).write_text(json.dumps(verdicts, indent=2))
    print(event_verdicts.render(verdicts))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
