from shared import github
from try_fix import needs_human

MERGED = "merged"
AWAITING_HUMAN = "awaiting_human"
REFUSED = "refused"
NEEDS_HUMAN = "needs_human"
PAUSED = "paused"
OPENED = "pr_open"
OUTCOMES = (MERGED, AWAITING_HUMAN, REFUSED, NEEDS_HUMAN, PAUSED, OPENED)


def comment(repo, token, number, text):
    github.run(["issue", "comment", str(number), "--repo", repo, "--body", text], token)


def end(repo, token, number, outcome, why):
    assert outcome in OUTCOMES, outcome
    if outcome == NEEDS_HUMAN:
        needs_human.hold(repo, token, number, why)
    else:
        comment(repo, token, number, f"**Factory Change {outcome.replace('_', ' ')}:** {why}")
    return outcome
