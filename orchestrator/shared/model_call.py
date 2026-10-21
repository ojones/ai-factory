import json

from shared import http_client


def json_chat(base_url, key, model, system, user, timeout=120):
    status, r = http_client.request("POST", f"{base_url}/chat/completions", key,
                                    {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                                     "response_format": {"type": "json_object"}}, timeout=timeout)
    if status != 200:
        raise RuntimeError(f"HTTP {status}")
    return json.loads(r["choices"][0]["message"]["content"])
