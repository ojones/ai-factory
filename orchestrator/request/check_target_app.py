# Which apps the Factory may change.
import re


def is_factory_repo(description, factory_repo):
    # True only for a repo App Staging created: its description carries `Intake: <factory repo>#<n>`.
    return bool(re.match(rf"^Intake: {re.escape(factory_repo)}#\d+$", (description or "").strip()))
