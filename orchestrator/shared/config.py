import os
from pathlib import Path

FACTORY_DIR = Path(__file__).resolve().parent.parent.parent
PROFILES = FACTORY_DIR / "agents" / "profiles.yml"
GROWTHBOOK_API = os.environ.get("GROWTHBOOK_API_HOST", "https://ai-factory-growthbook.fly.dev:3100") + "/api/v1"


def load():
    import yaml  # noqa: PLC0415
    return yaml.safe_load(PROFILES.read_text())


def limits(config=None):
    return ((config if config is not None else load()).get("limits")) or {}
