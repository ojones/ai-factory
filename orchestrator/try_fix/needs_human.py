from shared import github

LABEL = "needs-human"


def hold(repo, token, number, why):
    github.ensure_label(repo, LABEL, token, "b60205", "The Orchestrator stopped and needs a person")
    github.run(["issue", "edit", str(number), "--repo", repo, "--add-label", LABEL], token)
    github.run(["issue", "comment", str(number), "--repo", repo, "--body",
                f"**Needs a person:** {why}.\n\nNothing runs until you edit this issue if the request needs to change, then add `proceed-with-change` again. "
                "Its siblings wait."], token)
