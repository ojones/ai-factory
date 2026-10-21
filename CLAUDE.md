# AI Factory

Python in `orchestrator/` and `agents/` follows [STANDARDS-CODING.md](STANDARDS-CODING.md) ("Factory Python") and [docs/dignified-python-core.md](docs/dignified-python-core.md): short functions (5 lines, never over 10), no comments or docstrings (name things so they are not needed), look before you leap (no exceptions as control flow), pathlib, absolute module-level imports.

Before finishing a Python change, run from the repo root:

- `ruff check .`
- `cd orchestrator && python3 -m unittest discover -p "*_test.py" .`

Tests are named `<name>_test.py`, beside the module. Commit only when asked.
