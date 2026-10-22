def split(missing, reads):
    dark = [s for s in missing if reads(s)]
    return dark, [s for s in missing if s not in dark]


def guess(slug, named_flag):
    if named_flag is None:
        return (f"the task gave the coder no flag to use, so it chose `{slug}` itself and nothing created it (a plan filed before the Orchestrator "
                "named flags)")
    if slug != named_flag:
        return f"the coder added `{slug}` besides the flag the Orchestrator created for the story (`{named_flag}`)"
    return f"the flag `{named_flag}` was created at the start of the run but is gone from GrowthBook now (deleted or archived)"


def note(slug, kind, named_flag):
    return {"slug": slug, "kind": kind, "guess": guess(slug, named_flag)}


def dark_message(slugs, named_flag):
    return ("Not released: " + ", ".join(f"`{s}`" for s in slugs) + " is declared and read by the code but does not exist in GrowthBook, so the "
            "change is deployed dark and nothing can switch it on. Nothing was rolled back (users cannot see it). A flag that can be turned "
            "on has to exist before the code is released; add one in the next round. Likely cause: " + guess(slugs[0], named_flag) + ".")


def live_message(slugs, named_flag, failed):
    what = ", ".join(f"`{s}`" for s in slugs)
    if failed:
        return (f"The change went live without a gate: {what} is declared but no code reads it, and the tests found a failure, so the deploy is "
                "rolled back. Likely cause: " + guess(slugs[0], named_flag) + ".")
    return (f"The change went live on deploy without a gate: {what} is declared but no code reads it. The tests found no problem, so it is left as "
            "it is. Likely cause: " + guess(slugs[0], named_flag) + ".")


def unflagged_message():
    return "The change has no flag, so it went live on deploy for everyone, and the tests found a failure: the deploy is rolled back and the fix is a new change."
