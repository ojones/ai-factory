import subprocess

DEFAULT_TIMEOUT = 300
TIMED_OUT = 124


def run_bounded(cmd, cwd, env, timeout):
    try:
        return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=DEFAULT_TIMEOUT if timeout is None else timeout)
    except subprocess.TimeoutExpired:
        if timeout is not None:
            raise
        return subprocess.CompletedProcess(cmd, TIMED_OUT, "", f"timed out after {DEFAULT_TIMEOUT}s")


def sh(cmd, cwd=None, env=None, check=True, timeout=None):
    p = run_bounded(cmd, cwd, env, timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])}... failed ({p.returncode}): {(p.stderr or p.stdout)[-600:]}")
    return p
