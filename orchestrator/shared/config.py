# The Factory's configuration: agents/profiles.yml, read fresh each time it is asked for.
from pathlib import Path

PROFILES = Path(__file__).resolve().parent.parent.parent / "agents" / "profiles.yml"


def load():
    import yaml
    return yaml.safe_load(PROFILES.read_text())


def limits(config=None):
    return ((config if config is not None else load()).get("limits")) or {}
