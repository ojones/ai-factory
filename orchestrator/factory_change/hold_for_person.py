from shared import github

from factory_change import stop


def hold(repo, token, child, pr_url, paths):
    control = ", ".join(f"`{p}`" for p in paths)
    github.run(["pr", "comment", pr_url, "--repo", repo, "--body", f"This change touches the Factory's control path ({control}), so it does not merge itself. Review it and merge it when you are satisfied."], token)
    return stop.end(repo, token, child, stop.AWAITING_HUMAN, f"{pr_url} touches the Factory's control path and waits for a person to merge it")
