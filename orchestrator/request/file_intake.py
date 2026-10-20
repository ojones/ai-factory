# Filing an Update App Intake for a Managed App. Every automated source (template sync, maintenance, production feedback, flag retirement) files
# through here. The issue is created with the PAT and its `update-app-intake` label at creation is what starts planning (STEP 1.3, 2.1): an event made by
# the Actions token does not start workflows, so the Actions token files nothing that must start.
import re

from shared import github

from request import intake_labels, render_form


def file_update_app_intake(repo, token, pat, app, title, request_text, source_label=None, source_label_desc="", started_note=None, check=False):
    # Returns the new issue's number, or None if GitHub did not return one. With `check`, a failed gh call raises instead.
    wanted = [(intake_labels.UPDATE_APP_INTAKE, "1d76db", "A change request for an existing Managed App"),
              (intake_labels.app_label(app), "1d76db", f"Issues about the Managed App {app}")]
    if source_label:
        wanted.append((source_label, "fbca04", source_label_desc))
    for name, color, desc in wanted:
        github.ensure_label(repo, name, token, color, desc)
    applied = ",".join([intake_labels.UPDATE_APP_INTAKE, intake_labels.app_label(app)] + ([source_label] if source_label else []))
    out = github.run(["issue", "create", "--repo", repo, "--title", title, "--label", applied, "--body", render_form.form_body(app, request_text)],
                     pat, check=check).stdout
    made = re.search(r"/issues/(\d+)", out or "")
    if not made:
        return None
    number = int(made.group(1))
    if started_note:
        github.run(["issue", "comment", str(number), "--repo", repo, "--body", started_note], token)
    return number
