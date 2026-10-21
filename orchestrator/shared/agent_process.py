import contextlib
import os
import signal
import subprocess
import time
from pathlib import Path


def agent_command(cmd, env, user, pidfile=None):
    if not user:
        return cmd
    names = ",".join(k for k in env if k != "PATH")
    wrapper = []
    if pidfile:
        wrapper = ["bash", "-c", 'ps -o pgid= -p $$ | tr -d " " > "$0"; exec "$@"', str(pidfile)]
    return ["sudo", "-n", "-u", user, f"--preserve-env={names}", "env", f"PATH={env.get('PATH', '')}", *wrapper, *cmd]


def run_isolation_probes(agent_user):
    marker = subprocess.Popen(["sleep", "60"], env={**os.environ, "ISOLATION_MARK": "SELF-CHECK-SECRET"}, start_new_session=True)
    try:
        env = {"PATH": os.environ.get("PATH", "")}
        workspace = os.environ.get("GITHUB_WORKSPACE", "/home/runner/work")
        probes = {"whoami": "id -un", "environ": f"cat /proc/{marker.pid}/environ 2>/dev/null | tr '\\0' '\\n'",
                  "workspace": f"ls '{workspace}' 2>/dev/null",
                  "env_names": "env | cut -d= -f1 | grep -E '^(FACTORY_|FLY_API|GROWTHBOOK|DEEPINFRA|PREVIEW_MASTER|GITHUB_TOKEN|GH_TOKEN|ACTIONS_RUNTIME_TOKEN|ACTIONS_ID_TOKEN|ACTIONS_CACHE_URL|ACTIONS_RESULTS_URL)' || true",
                  "sudo": "sudo -n true 2>/dev/null && echo yes || echo no"}
        outputs = {}
        for name, script in probes.items():
            p = subprocess.run(agent_command(["bash", "-c", script], env, agent_user), env=env, capture_output=True, text=True, timeout=60)
            outputs[name] = p.stdout
        return isolation_problems(outputs)
    except (OSError, subprocess.TimeoutExpired) as e:
        return [f"the self-check could not run: {type(e).__name__}: {e}"]
    finally:
        marker.kill()


def kill_agent(proc, user, pidfile):
    if user and pidfile and Path(pidfile).is_file():
        pgid = Path(pidfile).read_text(encoding="utf-8").strip()
        if pgid.isdigit():
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run(["sudo", "-n", "kill", "-KILL", "--", f"-{pgid}"], capture_output=True, timeout=30)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        proc.kill()


def isolation_problems(outputs):
    problems = []
    if outputs.get("whoami", "").strip() in ("", os.environ.get("USER", "runner"), "runner"):
        problems.append("the Agent user is not a different account from the Orchestrator's")
    if "SELF-CHECK-SECRET" in outputs.get("environ", ""):
        problems.append("an Agent can read the Orchestrator's environment through /proc")
    if outputs.get("workspace", "").strip():
        problems.append("an Agent can list the runner's workspace")
    if outputs.get("env_names", "").strip():
        problems.append("the Agent's environment holds credential variables: " + outputs["env_names"].strip().replace("\n", ", "))
    if outputs.get("sudo", "").strip() == "yes":
        problems.append("the Agent user can use sudo")
    return problems


def silent_too_long(last_progress, now, stall_seconds):
    return stall_seconds > 0 and now - last_progress >= stall_seconds


def run_watched(cmd, cwd, env, out_path, timeout_s, stall_s, poll=5.0, user=None, pidfile=None):
    with open(out_path, "w", encoding="utf-8") as f:
        proc = subprocess.Popen(agent_command(cmd, env, user, pidfile), cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT,
                                start_new_session=True)
        began = last_change = time.time()
        size = -1
        while True:
            try:
                return proc.wait(timeout=poll)
            except subprocess.TimeoutExpired:
                pass
            now = time.time()
            current = Path(out_path).stat().st_size
            if current != size:
                size, last_change = current, now
            reason = "timeout" if now - began >= timeout_s else "stall" if silent_too_long(last_change, now, stall_s) else None
            if reason:
                kill_agent(proc, user, pidfile)
                proc.wait()
                return reason
