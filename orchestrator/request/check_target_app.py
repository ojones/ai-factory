import re


def is_factory_repo(description, factory_repo):
    return bool(re.match(rf"^Intake: {re.escape(factory_repo)}#\d+$", (description or "").strip()))
