import json
from pathlib import Path

TEXT_KEYS = ("text", "content", "message", "thought", "detail", "error")
TAIL_BYTES = 60_000


def read_tail(path, tail_bytes=TAIL_BYTES):
    path = Path(path)
    if not path.is_file():
        return ""
    data = path.read_bytes()[-tail_bytes:]
    return data.decode("utf-8", errors="replace")


def event_texts(line):
    try:
        event = json.loads(line)
    except ValueError:
        return []
    if not isinstance(event, dict):
        return []
    return [" ".join(event[k].split()) for k in TEXT_KEYS if isinstance(event.get(k), str) and event[k].strip()]


def last_words(path, count=3, width=300):
    texts = [t for line in read_tail(path).splitlines() for t in event_texts(line)]
    return [t[:width] for t in texts[-count:]]


def last_words_note(path):
    words = last_words(path)
    return " Its last messages: " + " | ".join(words) if words else ""
