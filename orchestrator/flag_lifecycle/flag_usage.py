# Whether the app's code reads a flag. A declared flag that no code outside the tests reads gates nothing: the change is live whatever the flag says.
import re

TEST_FILE_RE = re.compile(r"(\.test\.|\.spec\.|/tests?/|/__tests__/)")


def code_reads(git, head, slug):
    # The `git grep` hits for the slug as a string literal in backend or frontend code, not counting tests. `git(*args)` returns a git command's
    # stdout ('' when it fails), run in the app checkout.
    return [line for line in git("grep", "-n", "-I", "-F", "-e", f'"{slug}"', "-e", f"'{slug}'", head, "--", "backend", "frontend").splitlines()
            if not TEST_FILE_RE.search(line.split(":")[1] if line.count(":") > 1 else line)]
