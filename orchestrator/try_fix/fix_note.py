def fix_note(fix_for):
    return (f"\n\nThis is a fix for #{fix_for}, which failed after the change was built. Test it like any change: the behaviour that broke "
            "the last time must now work, and a test must cover it.")
