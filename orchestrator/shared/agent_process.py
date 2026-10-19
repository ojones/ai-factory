# Running an Agent as a process: as the unprivileged Agent account when isolation is on, with a self-check, a stall watch and a kill by process group.
import os
import subprocess
import time
from pathlib import Path


def agent_command(cmd, env, user, pidfile=None):
    # `cmd` as it is run for an Agent. With a `user` (limits.agent_isolation: user) it runs as that unprivileged account through
    # sudo: the variables in `env` are passed by name, so no value shows on a command line, and a wrapper records the process group
    # in `pidfile` so the runner (which cannot signal another user's processes) can kill it through sudo.
    if not user:
        return cmd
    names = ",".join(k for k in env if k != "PATH")
    wrapper = []
    if pidfile:
        wrapper = ["bash", "-c", 'ps -o pgid= -p $$ | tr -d " " > "$0"; exec "$@"', str(pidfile)]
    return ["sudo", "-n", "-u", user, f"--preserve-env={names}", "env", f"PATH={env.get('PATH', '')}", *wrapper, *cmd]


def run_isolation_probes(agent_user):
    # Run probes as the Agent user (no model involved) and return what is wrong; see isolation_problems.
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
    # Kill an Agent's whole process group, whether it runs as the runner or, through sudo, as the Agent user.
    import signal
    if user and pidfile:
        try:
            pgid = Path(pidfile).read_text().strip()
            if pgid.isdigit():
                subprocess.run(["sudo", "-n", "kill", "-KILL", "--", f"-{pgid}"], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        proc.kill()


def isolation_problems(outputs):
    # What an isolation self-check found wrong, from {probe: output of the probe run as the Agent user}. Empty means isolated.
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
    # True when an Agent's output has not grown for `stall_seconds` (0 turns the check off).
    return stall_seconds > 0 and now - last_progress >= stall_seconds


def run_watched(cmd, cwd, env, out_path, timeout_s, stall_s, poll=5.0, user=None, pidfile=None):
    # Run an Agent writing its event stream to `out_path`. Returns its exit status, or "timeout" after `timeout_s` of wall time,
    # or "stall" when the stream stops growing for `stall_s` seconds (the process group is killed either way). A real run once sat
    # 45 minutes twice with no output at all, so a silent Agent is cut off long before the overall timeout.
    with open(out_path, "w") as f:
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
            current = os.path.getsize(out_path)
            if current != size:
                size, last_change = current, now
            reason = "timeout" if now - began >= timeout_s else "stall" if silent_too_long(last_change, now, stall_s) else None
            if reason:
                kill_agent(proc, user, pidfile)
                proc.wait()
                return reason
