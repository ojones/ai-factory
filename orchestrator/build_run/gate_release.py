# STEP 4.12 and 4.13: the release gate, and the thin glue to Flag Lifecycle (release, watchdog, story link, archive) that keeps the old seams.
import os
import subprocess

from flag_lifecycle import (
    flag_usage,
    missing_flag,
    release_features,
    retirement_archive,
    story_link,
    watchdog,
)
from shared import (
    config,
    github,
    http_client,
    outcomes,
    run_stops,
)
from shared.console import log
from shared.shell import sh


def release_gate(ci_green, deploy_healthy, tester_passed, reviewer_clean, reviewed_sha, head_sha):
    # Release only when all four hold for the pushed SHA.
    return all([ci_green, deploy_healthy, tester_passed, reviewer_clean]) and reviewed_sha == head_sha


class ReleaseStep:
    def gb(self, method, path, body=None):
        return http_client.request(method, f"{config.GROWTHBOOK_API}{path}", os.environ["GROWTHBOOK_ADMIN_PAT"], body)

    def link_flags_to_issue(self, slugs):
        # The story names its flag (flag_lifecycle/story_link.py). Update App Intakes only: a first build's title must stay the bare app name.
        # Best effort, never a reason to stop the run.
        if not self.update_intake or not slugs:
            return
        try:
            self.issue_title = story_link.link(self.gh, github.ensure_label, self.factory_repo, self.factory_token, self.issue,
                                               getattr(self, "issue_title", ""), self.app, self.run_id, self.run_url, slugs)
        except Exception as e:  # noqa: BLE001
            log(f"could not link the flag to its issue: {type(e).__name__}: {e}")

    def archive_retired_flags(self, base, head):
        # Flags this run removed from flags.json are archived in GrowthBook (best effort), so a retired flag leaves nothing behind.
        # Only when the run ended well: an outcome that is not OK did not finish, and its flags are still in use.
        if self.state.d.get("outcome") not in outcomes.OK:
            return
        try:
            for slug, status in retirement_archive.archive_removed(self.gb, self.app, self.git("show", f"{base}:flags.json", check=False).stdout,
                                                                   self.git("show", f"{head}:flags.json", check=False).stdout):
                log(f"archived retired flag {slug} in GrowthBook (HTTP {status})")
                story = getattr(self, "flag_issues", {}).get(slug)
                if story:  # the flag's story hears that its flag is gone
                    self.gh(["issue", "comment", str(story), "--repo", self.factory_repo, "--body",
                             f"Feature flag `{self.app}.feature.{slug}` retired by [Build Run {self.run_id}]({self.run_url}): its behaviour is now simply on, "
                             "and the flag is archived in GrowthBook."], token=self.factory_token, check=False)
        except Exception as e:  # noqa: BLE001
            log(f"could not archive retired flags: {type(e).__name__}: {e}")

    def release(self, flags, head):
        # Switch on the story's own flag(s). A flag that does not exist is never created here (flag_lifecycle/missing_flag.py): if the code reads it
        # the change is dark with nothing to turn it on, which fails the run; if the code does not read it the change is already live, which is
        # noted and left alone.
        to_switch, kept, missing = release_features.check_flags(self.gb, self.app, flags, list(self.story_flags) + list(self.reuse_flags))
        if missing:
            named = self.state.d.get("named_flag")
            dark, live = missing_flag.split(missing, lambda slug: bool(flag_usage.code_reads(lambda *a: self.git(*a, check=False).stdout, head, slug)))
            self.state.d["flag_notes"] = ([missing_flag.note(s, "missing_dark", named) for s in dark]
                                          + [missing_flag.note(s, "live_without_flag", named) for s in live])
            if dark:
                raise run_stops.FlagMissing(missing_flag.dark_message(dark, named))
            self.state.d["flag_message"] = missing_flag.live_message(live, named, False)
            log(self.state.d["flag_message"])
        release_features.switch_on(self.gb, to_switch)
        released = to_switch
        body = (f"**Released** by Build Run [{self.run_id}]({self.run_url}) for commit `{head}`.\n\n"
                f"Enabled for everyone: {', '.join(f'`{k}`' for k in released) or 'none'}.\n"
                + (f"Left untouched (already existed): {', '.join(f'`{k}`' for k in kept)}.\n" if kept else "")
                + (f"\n{self.state.d['flag_message']}\n" if self.state.d.get("flag_message") else "")
                + "\nRoll back by turning the flag off in GrowthBook.")
        self.gh(["api", f"repos/{self.app_repo}/commits/{head}/comments", "-f", f"body={body}"])
        self.state.d["release"] = {"released": released, "kept": kept}
        self.state.stage("Release", "-", "-", 0, f"{len(released)} flag(s) released")

    def ungated_flags(self, head, flags):
        # The declared flags no code reads: the change they belong to went live on deploy, whatever the flag says.
        return [s for s in flags if not flag_usage.code_reads(lambda *a: self.git(*a, check=False).stdout, head, s)]

    def app_error_count(self):
        try:
            p = sh(["flyctl", "logs", "--no-tail", "--app", self.app],
                   env={**os.environ, "FLY_API_TOKEN": os.environ.get("FLY_API_TOKEN", "")}, check=False, timeout=120)
            return watchdog.count_errors(p.stdout or "")
        except (OSError, subprocess.TimeoutExpired):
            return 0

    def disable_flags(self, keys):
        return watchdog.disable_flags(self.gb, keys)

    def watch_release(self):
        # After a release, watch the app (flag_lifecycle/watchdog.py). A run of failed health checks, or a rise in error-level log lines,
        # switches the flags this run released off by itself (never one that already existed, which the owner controls) and ends the run
        # as `watchdog_disabled` so finalize opens the Issue. The flag is the rollback lever, and the release step never turns it back on.
        # The outcome was set just before this call and is not on disk yet. Save it now: the watch below can take
        # minutes, and a run cancelled during it must still report `released`, not look like a crash.
        self.state.save()
        keys = list((self.state.d.get("release") or {}).get("released") or [])
        if float(self.lim.get("watchdog_minutes", 0)) > 0 and keys:
            log(f"watching {self.app} for {float(self.lim['watchdog_minutes']):g} minutes after the release")
        minutes, reason, still_on = watchdog.watch(keys, self.lim, self.deadline, self.disable_flags, self.app_error_count,
                                                   lambda: http_client.request("GET", f"https://{self.app}.fly.dev/api/health", timeout=20)[0])
        if minutes is None:
            return
        if reason:
            note = f" Could not confirm these are off: {', '.join(still_on)}; turn them off in GrowthBook now." if still_on else ""
            self.state.d.update(outcome="watchdog_disabled", message=(f"Released {len(keys)} flag(s), then switched them off: {reason}.{note}"))
            self.state.stage("Watchdog", "-", "-", 0, "flags switched off")
            return
        self.state.stage("Watchdog", "-", "-", 0, f"clean for {minutes:g} min")
