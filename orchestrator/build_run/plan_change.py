# Planning inside the Build Run (until the planning process takes it out, ticket 13): plan an Update App Intake, check the plan, and file its children.
import json

from planning import file_children, plan_comment, render_child, secrets_marker, triage, validate_plan
from shared import (
    run_stops,
)
from shared.console import log

from build_run import endings


def secrets_note(needed):
    # What the coder is told about the request's secrets: they exist at runtime as environment variables, and it never sees a value.
    names = ", ".join(x["name"] for x in needed)
    return ("\n\nSecrets (set by the owner, already in the running app's environment as process.env.<NAME>; you never see a value): " + names
            + ". Read each in exactly one place, the call to the service; fail closed (a clear error, the feature off) when it is missing; never log it, "
              "return it or send it anywhere else. In the same commit add each name and what it is for (no values) to `secrets.json` at the repo root as "
              '{"secrets": [{"name": "...", "purpose": "..."}]}. In tests, stub the service: the test environment has no real value.')


class PlanChange:
    def plan_change(self):
        # Plan an Update App Intake with the planner Agent, then check the plan deterministically. Returns True when
        # the request was split into several change sets and filed as child issues (this run is then finished), False
        # when there is one change set, which becomes this run's task. A plan that fails the check, or that has a
        # blocking question, stops the run for a person.
        path = self.work / "plan.json"
        limit = int(self.lim.get("planner_max_change_sets", validate_plan.MAX_CHANGE_SETS))
        max_criteria = int(self.lim.get("planner_max_criteria", validate_plan.MAX_CRITERIA))
        problems = []

        def check(doc):
            found, _ = validate_plan.validate_plan(doc, self.build_kind, limit, self.reuse_flags, max_criteria)
            problems[:] = found
            if found:
                raise ValueError("; ".join(found))

        try:
            doc, cost, usage = self.agent_json("planner", "1", {"task": self.task, "plan_path": path}, path, check=check)
        except run_stops.NeedsHuman:
            if problems:
                raise run_stops.NeedsHuman("other", "the planner's plan was rejected: " + "; ".join(problems))
            raise
        blocked, category, reasons, possible = triage.feasibility(doc)
        if blocked:
            self.state.stage("Plan", "planner", "1", cost, f"refused ({category})", usage)
            raise endings.Refused(triage.refusal_text(category, reasons, possible))
        _, questions = validate_plan.validate_plan(doc, self.build_kind, limit, self.reuse_flags, max_criteria)
        if questions and getattr(self, "fix_meta", None):
            # An automatic retry has no person to answer. Take the most conservative reading and say so, in the plan comment.
            doc["assumptions"] = list(doc.get("assumptions") or []) + [
                f"Decided without asking (this retry runs with no person reviewing it): {q} Taking the most conservative reading: "
                "keep existing data and behaviour, and keep the change behind its flag." for q in questions]
            questions = []
        sets = doc["change_sets"]
        self.state.d["plan"] = {"change_sets": [{"id": c["id"], "title": c["title"], "flag": c.get("flag")} for c in sets],
                                "assumptions": doc.get("assumptions") or []}
        self.state.stage("Plan", "planner", "1", cost, f"{len(sets)} change set(s)" + (", needs an answer" if questions else ""), usage)
        (self.art / "plan.json").write_text(json.dumps(doc, indent=2))
        self.post_plan(doc, questions)
        if questions:
            raise run_stops.NeedsHuman("other", "the plan needs a person to answer first: " + " | ".join(questions)
                             + ". Put the answers in the Update App Intake issue, then add `proceed-with-change` again.")
        needed = [x for x in doc.get("secrets") or [] if isinstance(x, dict)]
        if needed:
            if {x["name"] for x in needed} - {x["name"] for x in self.declared_secrets}:  # a secret not yet checked at the start
                self.require_secrets(needed, record=True)
            self.task += secrets_note(needed)
        if len(sets) == 1:
            self.task = render_child.render_change_set_task(sets[0], request=self.task)
            if isinstance(sets[0].get("flag"), str):
                self.state.d["flags"] = [sets[0]["flag"]]  # a slug the planner chose (older plans); `name_the_flag` handles `flag: true`

            self.spec = self.task
            return False
        made = file_children.file_children(self.factory_repo, self.pat, self.app, int(self.issue), sets,
                                           validate_plan.topological_order(sets), self.task, cap=self.cap_override, secrets=needed)
        self.state.d.update(outcome="planned", message="Planned as %d change sets, each now its own Update App Intake and Build Run, in order: %s."
                            % (len(made), ", ".join(f"{cs} (#{n})" for cs, n in made)))
        return True

    def require_secrets(self, needed, record=False):
        # Stop (AwaitingSecret) until every secret declared for this request exists as a GitHub Actions secret on the app's repository. Only
        # names are read (`gh secret list` never returns a value). Records the declared names so the coder's `secrets.json` can be checked
        # against them, and with `record` leaves a hidden marker on the Intake so every later start checks them before paying for anything.
        out = self.gh(["secret", "list", "--repo", self.app_repo, "--json", "name"], check=False)
        if out.returncode != 0:
            raise run_stops.NeedsHuman("other", "could not read the names of the app's GitHub secrets, so the request's secrets cannot be confirmed")
        have = {x.get("name") for x in json.loads(out.stdout or "[]")}
        self.state.d["secrets"] = [x["name"] for x in needed]
        missing = [x for x in needed if x["name"] not in have]
        if record:
            text = triage.secrets_request(missing, self.app_repo) if missing else "This request uses " + ", ".join(x["name"] for x in needed) + " (set)."
            self.gh(["issue", "comment", str(self.issue), "--repo", self.factory_repo, "--body", text + "\n\n" + secrets_marker.secrets_marker(needed)],
                    token=self.factory_token, check=False)
        if missing:
            raise endings.AwaitingSecret("waiting for " + ", ".join(x["name"] for x in missing) + " to be set on " + self.app_repo
                                 + " (the commands are on the Intake issue); then add `proceed-with-change` again")

    def post_plan(self, doc, questions):
        # Put the plan on the Intake issue, so the owner can see what is about to be built and every assumption the
        # planner made (a product decision it made for them is otherwise only in a build artifact). Best effort.
        try:
            body = plan_comment.render_plan_comment(doc, questions)
            self.gh(["issue", "comment", str(self.issue), "--repo", self.factory_repo, "--body", body],
                    token=self.factory_token, check=False)
        except Exception as e:  # noqa: BLE001
            log(f"could not post the plan to the Intake issue: {type(e).__name__}")
