import json
import shutil
from pathlib import Path

from shared.console import log


def adopt_misplaced_file(path, cwd):
    if not cwd or Path(path).exists():
        return False
    stray = Path(cwd) / Path(path).name
    if stray.is_file():
        try:
            shutil.copyfile(stray, path)
            log(f"The Agent wrote {stray.name} in its working directory instead of {path}; using that copy.")
            return True
        except OSError:
            return False
    return False


def json_problem(path, check=None):
    if not Path(path).is_file():
        return f"the file {path} was not written (write it at exactly that absolute path, not relative to your working directory)"
    text = Path(path).read_text(encoding="utf-8")
    if not text.strip():
        return f"the file {path} is empty"
    try:
        doc = json.loads(text)
    except ValueError as e:
        where = f" at line {e.lineno} column {e.colno}" if hasattr(e, "lineno") else ""
        return (f"it is not valid JSON ({getattr(e, 'msg', e)}{where}); the usual cause is a quote, newline or backslash "
                "inside a string that was not escaped")
    try:
        if check is not None and check(doc) is False:
            return "its contents were not accepted"
    except (ValueError, AttributeError, TypeError) as e:
        return f"its contents were not accepted: {e}"
    return None


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def retry_prompt(prompt, note):
    if not note:
        return prompt
    return (prompt + f"\n\nYour previous attempt was rejected: {note}. Do the work again as needed and write the file again. "
            "Build the JSON with a short Python script and json.dump, not by typing it by hand.")
