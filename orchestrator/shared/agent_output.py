# The JSON file an Agent is asked to write: finding it, and saying what is wrong with it in words the Agent can act on.
import json
import shutil
from pathlib import Path

from shared.console import log


def adopt_misplaced_file(path, cwd):
    # If `path` was not written but a file of the same name sits directly in the Agent's working directory, copy it to `path`. Returns True
    # when it did. Never overwrites an existing file.
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
    # Why an Agent's output file cannot be used, in words the Agent can act on; None when it can. Used to tell the
    # Agent on its second attempt what was wrong with its first.
    try:
        text = Path(path).read_text()
    except OSError:
        return f"the file {path} was not written (write it at exactly that absolute path, not relative to your working directory)"
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
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def retry_prompt(prompt, note):
    # The prompt for a second attempt: the first prompt and what was wrong with its output.
    if not note:
        return prompt
    return (prompt + f"\n\nYour previous attempt was rejected: {note}. Do the work again as needed and write the file again. "
            "Build the JSON with a short Python script and json.dump, not by typing it by hand.")
