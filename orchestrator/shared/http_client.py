import json
import urllib.error
import urllib.request


def request(method, url, token=None, body=None, timeout=60):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, (json.loads(raw) if raw else {})
            except ValueError:
                return r.status, raw[:500].decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:500].decode(errors="replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e)
