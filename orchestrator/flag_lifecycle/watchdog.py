import re
import time

ERROR_LOG_RE = re.compile(r'"level"\s*:\s*"(?:error|fatal)"', re.I)


def count_errors(log_text):
    return len(ERROR_LOG_RE.findall(log_text or ""))


def watchdog_trip(samples, baseline_errors, max_failures, max_new_errors):
    streak = 0
    for sample in samples:
        streak = 0 if sample["healthy"] else streak + 1
        if streak >= max_failures:
            return f"the health check failed {streak} times in a row after the release"
    if samples and max(sample["errors"] for sample in samples) - baseline_errors >= max_new_errors:
        return (f"error-level log lines rose from {baseline_errors} to {max(s['errors'] for s in samples)} "
                f"after the release (limit: {max_new_errors} new)")
    return None


def disable_flags(gb, keys):
    still_on = []
    for key in keys:
        gb("POST", f"/features/{key}", {"environments": {"production": {"enabled": False, "rules": []}}})
        status, r = gb("GET", f"/features/{key}")
        env = ((r.get("feature") or r) if isinstance(r, dict) else {}).get("environments", {}).get("production", {})
        if status != 200 or env.get("enabled") is not False:
            still_on.append(key)
    return still_on


def watch(keys, limits, deadline, disable, error_count, health_status):
    minutes = float(limits.get("watchdog_minutes", 0))
    if minutes <= 0 or not keys:
        return None, None, []
    interval = float(limits.get("watchdog_interval_seconds", 30))
    end = min(time.time() + minutes * 60, deadline)
    baseline = error_count()
    samples = []
    while time.time() < end:
        time.sleep(interval)
        samples.append({"healthy": health_status() == 200, "errors": error_count()})
        reason = watchdog_trip(samples, baseline, int(limits.get("watchdog_max_failures", 3)), int(limits.get("watchdog_max_errors", 5)))
        if reason:
            return minutes, reason, disable(keys)
    return minutes, None, []
