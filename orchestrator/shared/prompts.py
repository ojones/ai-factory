# Role prompts: loading one and filling in its {{placeholders}}.
import re

from shared import config


def load_prompt(prompt_path):
    # A role prompt, with the shared reviewer rubric spliced in where it asks for `{{rubric}}`.
    text = (config.FACTORY_DIR / "agents" / prompt_path).read_text()
    if "{{rubric}}" in text:
        text = text.replace("{{rubric}}", (config.FACTORY_DIR / "agents" / "prompts" / "reviewer-rubric.md").read_text().strip())
    return text


def render(template, values):
    out = template
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", str(v))
    left = re.findall(r"\{\{\w+\}\}", out)
    if left:
        raise ValueError(f"unreplaced prompt placeholders: {left}")
    return out
