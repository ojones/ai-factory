# STEP 7.1: what the reviewer and tester are told for a fix child (a child whose marker has `fix_for`). The fix is filed as a bug Intake (file_bug.py) and planned
# into one ordinary child; this is the sentence the Build Run adds to that child's spec.


def fix_note(fix_for):
    return (f"\n\nThis is a fix for #{fix_for}, which failed after the change was built. Test it like any change: the behaviour that broke "
            "the last time must now work, and a test must cover it.")
