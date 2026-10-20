# STEP 7: file the bugs for events with no Build Run, after the Retrospective judged them (`retrospective.judge_events` writes the verdicts). Each `fix` verdict gets its
# text from the Try Fix Agent and is filed exactly as for a failed run (file_failure.py); a `record` verdict files nothing. Used by production-feedback.yml.
#
# Usage: python -m try_fix.file_events <verdicts.json>   (PYTHONPATH=orchestrator; env GITHUB_REPOSITORY, FACTORY_PAT, FACTORY_GH_TOKEN, DEEPINFRA_API_KEY)
import json
import os
import sys
from pathlib import Path

from shared import config
from shared.console import log

from try_fix import event, file_failure, write_bug


def fixes_in(verdicts):
    # The `fix` verdicts whose event is well formed.
    return [v for v in verdicts if isinstance(v, dict) and v.get("verdict") == "fix" and event.valid(v.get("event"))]


def main(argv):
    try:
        verdicts = json.loads(Path(argv[1]).read_text())
    except (OSError, ValueError):
        verdicts = []
    cfg, e = config.load(), os.environ
    fixes = fixes_in(verdicts if isinstance(verdicts, list) else [])
    if not fixes or not bool(cfg.get("limits", {}).get("fix_requests", True)):
        log(f"{len(fixes)} event(s) to fix; nothing filed")
        return 0
    repo, token = e["GITHUB_REPOSITORY"], e["FACTORY_GH_TOKEN"]
    done = file_failure.file_failures(repo, token, e["FACTORY_PAT"], fixes, None, None, None, cfg, e.get("DEEPINFRA_API_KEY"),
                                      lambda budget, cred: write_bug.record_spend(budget, cred, repo, token, e.get("GITHUB_RUN_ID", "0")))
    for got in done:
        log(f"event {got['key']} handled ({got['target']}: {got['action']}) {got['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
