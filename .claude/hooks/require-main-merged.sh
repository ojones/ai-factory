#!/usr/bin/env bash
cd "$CLAUDE_PROJECT_DIR" || exit 0
branch=$(git symbolic-ref --short -q HEAD) || exit 0
[ "$branch" = "main" ] && exit 0
git fetch -q origin main 2>/dev/null || exit 0
git merge-base --is-ancestor origin/main HEAD && exit 0
echo "BLOCKED: $branch is behind origin/main. Run 'git merge origin/main', resolve any conflicts, rerun ruff check . and the unit tests, then push again." >&2
exit 2
