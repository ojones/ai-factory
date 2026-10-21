import re

APP_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
NO_ANSWER = "_No response_"


def form_section(body, heading):
    out, on = [], False
    for line in (body or "").replace("\r", "").split("\n"):
        if line == f"### {heading}":
            on = True
        elif line.startswith("### "):
            on = False
        elif on:
            out.append(line)
    return "\n".join(out).strip()


def app_name(body):
    name = form_section(body, "App name")
    if not name or name == NO_ANSWER:
        raise ValueError('the "App name" field is empty')
    if not APP_RE.fullmatch(name) or len(name) > 30:
        raise ValueError(f"`{name}` is not a Managed App name (lowercase letters, digits and single hyphens, at most 30 characters)")
    return name


def read_request(body, default_cap, ceiling):
    task = form_section(body, "What should be built?") or form_section(body, "What should change?")
    if not task or task == NO_ANSWER:
        raise ValueError("The Intake's request field (\"What should be built?\" or \"What should change?\") is empty.")
    raw = form_section(body, "Cost cap override (USD)").lstrip("$")
    if not raw or raw == NO_ANSWER:
        return task, float(default_cap)
    try:
        cap = float(raw)
    except ValueError:
        raise ValueError(f"Cost cap override {raw!r} is not a number.")
    if not 0 < cap <= float(ceiling):
        raise ValueError(f"Cost cap override ${cap} must be > 0 and <= the ${ceiling} ceiling.")
    return task, cap
