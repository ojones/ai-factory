# A flag the change declares but GrowthBook does not have at release. The release step never creates one: it cannot be tested to work reliably, and a
# missing flag is a sign something earlier went wrong. What it means depends on whether the code reads the flag.
#   - the code reads it: the feature is deployed dark and nothing can switch it on. A failure (`flag_missing`), nothing is rolled back; the story is
#     fixed forward with a flag that exists.
#   - the code does not read it: the change went live on deploy with no gate. If the tests found no problem it is left alone and noted; if they found
#     a failure it is rolled back like any regression. Either way the note is recorded for the retrospective to learn from.


def split(missing, reads):
    # (dark, live): the missing slugs the code reads, and those it does not. `reads(slug)` says whether code reads it.
    dark = [s for s in missing if reads(s)]
    return dark, [s for s in missing if s not in dark]


def guess(slug, named_flag):
    # Why this flag may be missing, for whoever reads the note. `named_flag` is the flag the Orchestrator created for the story (None when the task
    # gave no flag to name: a first build, a run with the planner off, or a plan filed before the Orchestrator named flags).
    if named_flag is None:
        return (f"the task gave the coder no flag to use, so it chose `{slug}` itself and nothing created it (a first build, a run with the planner "
                "off, or a plan filed before the Orchestrator named flags)")
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
