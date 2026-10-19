# The one place that runs the GitHub CLI. Every call names its token, so the caller chooses between the Actions token and the PAT
# (a label added with the Actions token starts no workflow, so anything that must start one passes the PAT).
import os
import subprocess


def run(args, token, check=False):
    p = subprocess.run(["gh", *args], capture_output=True, text=True, env={**os.environ, "GH_TOKEN": token})
    if check and p.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {p.stderr.strip()[:200]}")
    return p


def ensure_label(repo, name, token, color="0e8a16", description=""):
    run(["label", "create", name, "--repo", repo, "--color", color, "--description", description], token)


def git_auth_env(header):
    # Environment variables that make git send `header` to GitHub. Passed this way, not as `git -c http.extraheader=...`, because a
    # command line is readable by every user on the machine (`ps`, /proc/<pid>/cmdline) while an environment is not.
    return {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraheader", "GIT_CONFIG_VALUE_0": header}
