# The bench app: how to create it (once)

The whole-run benchmark needs one disposable Managed App, `factory-bench`, frozen at a known commit. Create it through the normal Factory path so it
has a real repo, Fly app, GrowthBook connection and deploy pipeline. It costs about $0.20 once.

1. **File a New App Intake** (the New App Intake form) titled `factory-bench` with this spec, and add `ready-for-staging`:

   > A small todo list API. POST /api/todos with {"text": string} creates a todo and answers 201 with {id, text, done: false}; text is trimmed, blank
   > text answers 400 {"error": "text is required"}. GET /api/todos lists todos in creation order. GET /api/todos/:id answers one or 404
   > {"error": "not found"}. PUT /api/todos/:id with {"done": boolean} updates it. DELETE /api/todos/:id removes it and answers 204. Data is kept in
   > memory. Ids are positive integers; an id that is not a positive integer answers 400 {"error": "invalid id"}.

2. **File an update Intake** for `factory-bench` (the Update App Intake form), add `proceed-with-change`, and let it release:

   > Add GET /api/bench-seed that answers 200 with {"seed": true}. It is a user-visible change, so ship it behind a feature flag named `bench-seed`: with the
   > flag off it answers 404 like any unknown route.

   This leaves a released flag `bench-seed` in `flags.json` and in GrowthBook, which the `retire-named-flag` task retires on every pass (the runner never
   archives `bench-seed`).

3. **Freeze it:** `GITHUB_REPOSITORY=<owner>/ai-factory PYTHONPATH=orchestrator python3 -m monitoring.benchmark freeze`, which writes the bench app's current `main` into
   `agents/benchmark/suite.json` as `base_sha`. Commit that file. Every task starts by forcing the bench app's `main` back to this commit.

4. **Take the first baseline** (a pass with no candidate), then `benchmark.py accept` the result and commit `agents/benchmark/baseline.json`.

Never use the bench app for anything else, and tear it down with the `teardown-managed-app` skill when you no longer want it.
