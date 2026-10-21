import subprocess


def sh(cmd, cwd=None, env=None, check=True, timeout=None):
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])}... failed ({p.returncode}): {(p.stderr or p.stdout)[-600:]}")
    return p
