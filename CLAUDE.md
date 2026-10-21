# AI Factory

Python in `orchestrator/` and `agents/` is linted by ruff (`pyproject.toml`, rules are only ever added) and by `orchestrator/style_test.py`. The checks are the style guide; this file holds what no check can say.

Before finishing a Python change, run from the repo root:

- `ruff check .`
- `cd orchestrator && python3 -m unittest discover -p "*_test.py" .`

Tests are named `<name>_test.py`, beside the module (`build_run/run.py` has `build_run/run_test.py`); a `test_<name>.py` file is never found by CI. Commit only when asked.

## Enforced by a check

- Functions are short: aim for 5 to 10 lines, over 20 fails. If a step wants a comment, extract it into a function named for the step.
- No comments and no docstrings: name things so they are not needed. `# noqa`, `# type:`, `# pragma` and a shebang are allowed. The reasoning behind a line goes in `docs/module-notes.md` only when a name cannot carry it.
- Indentation depth is at most 4 (`style_test`). `style_baseline.json` lists code older than these rules: a listed function may not grow, nothing new may break a limit. After shortening code run `python3 orchestrator/style_test.py --update`; `--report` shows the distance to the goal.
- pathlib over `os.path`, absolute imports, imports at module level (a deliberate lazy import carries `# noqa: PLC0415`), an explicit encoding on every file read and write, no re-export aliases, no `try`/`except`/`pass`.

## By convention (no check)

- Look before you leap: test a condition rather than catching the exception it would raise (`if key in mapping`, `path.exists()`). Exceptions are for boundaries a check cannot cover: parsing JSON or dates, the network, subprocesses, the run-ending exceptions in `run_stops` and `endings`, and adding context before re-raising. Otherwise let them bubble.
- Properties and `__len__` are O(1); anything that does I/O or iterates is a named method.
- No backwards-compatibility shims: break the old shape and migrate callers in the same change, unless it is a public API or the user asks.
- One canonical import path: no `__all__` re-exports, empty `__init__.py`.
- Declare a variable next to its use. Do not destructure an object into locals that are used once; read the fields where needed.

## Where things live

[ARCHITECTURE.md](ARCHITECTURE.md) is the single place for why (including the standards a Managed App follows). [docs/flow-spec.md](docs/flow-spec.md) and [docs/invariants.md](docs/invariants.md) are the numbered behaviour spec, kept consistent by tests. The Factory repo changes go through PRs; the "commit to main" rule in ARCHITECTURE.md applies to Managed Apps only.
