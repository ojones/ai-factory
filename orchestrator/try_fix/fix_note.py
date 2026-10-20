# STEP 7.1: what the reviewer and tester are told for a fix child (a child whose marker has `fix_for`). The fix is filed as a bug Intake (file_bug.py) and planned
# into one child that keeps the failed story's flag; this is the sentence the Build Run adds to that child's spec.


def fix_note(story_flag_number, fix_for):
    # Its flag is the failed story's, and is released again once the fix passes.
    return (f"\n\nThis is a fix for #{fix_for}, which failed after the change was built. It keeps that story's flag `issue-{story_flag_number}`. Test it like a new flag: "
            "dark without the Preview Token (the feature must not be reachable) and working with the token, including the behaviour that broke the "
            "last time. When this passes, the flag is released again.")
