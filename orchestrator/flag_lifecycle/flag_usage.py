import re

TEST_FILE_RE = re.compile(r"(\.test\.|\.spec\.|/tests?/|/__tests__/)")


def code_reads(git, head, slug):
    return [line for line in git("grep", "-n", "-I", "-F", "-e", f'"{slug}"', "-e", f"'{slug}'", head, "--", "backend", "frontend").splitlines()
            if not TEST_FILE_RE.search(line.split(":")[1] if line.count(":") > 1 else line)]
