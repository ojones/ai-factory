# What an Agent's conversation cost in model calls and context, read from OpenHands' persisted state.

def summarize_token_usage(base_state):
    # Per-invocation context stats from OpenHands' persisted base_state.json.
    #
    # prompt_tokens of one LLM call is that call's context size, so the max over calls is the
    # invocation's peak context. The condenser's own calls are counted separately.
    metrics = (base_state.get("stats") or {}).get("usage_to_metrics") or {}
    agent = (metrics.get("agent") or {}).get("token_usages") or []
    condenser = (metrics.get("condenser") or {}).get("token_usages") or []
    prompts = [u.get("prompt_tokens", 0) for u in agent]
    latencies = (metrics.get("agent") or {}).get("response_latencies") or []
    return {"calls": len(agent), "condenser_calls": len(condenser),
            "peak_context": max(prompts, default=0), "last_context": prompts[-1] if prompts else 0,
            "prompt_tokens": sum(prompts), "completion_tokens": sum(u.get("completion_tokens", 0) for u in agent),
            "cache_read_tokens": sum(u.get("cache_read_tokens", 0) for u in agent),
            "llm_seconds": round(sum(l.get("latency", 0) for l in latencies), 1), "seconds": 0.0}


def merge_usage(a, b):
    # Combine two invocations' stats (a retry of the same role).
    if not a:
        return b
    if not b:
        return a
    out = {k: a[k] + b[k] for k in a if k not in ("peak_context", "last_context")}
    out["peak_context"] = max(a["peak_context"], b["peak_context"])
    out["last_context"] = b["last_context"]
    return out
