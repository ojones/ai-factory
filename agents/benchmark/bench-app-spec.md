# The bench app: how to create it (once)

The whole-run benchmark needs one disposable Managed App, `factory-bench`, frozen at a known commit. Create it through the normal Factory path so it
has a real repo, Fly app, GrowthBook connection and deploy pipeline. It costs about $0.20 once.

1. **File a New App Intake** (the New App Intake form) titled `factory-bench` with this spec; submitting it starts planning, and the app is staged and then built from the plan (ai-factory#140 did this on 2026-10-20 with a smaller spec; the app exists, but it has to be re-seeded as below and frozen before a pass):

   > A small todo list API. POST /api/todos with {"text": string} creates a todo and answers 201 with {id, text, done: false}; text is trimmed, blank
   > text answers 400 {"error": "text is required"}. GET /api/todos lists todos in creation order. GET /api/todos/:id answers one or 404
   > {"error": "not found"}. PUT /api/todos/:id with {"done": boolean} updates it. DELETE /api/todos/:id removes it and answers 204. Data is kept in
   > memory. Ids are positive integers; an id that is not a positive integer answers 400 {"error": "invalid id"}.

2. **File an update Intake** for `factory-bench` (the Update App Intake form), add `proceed-with-change`, and let it release:

   > Add GET /api/bench-seed that answers 200 with {"seed": true}. It is a user-visible change, so ship it behind a feature flag: with the flag off it answers 404
   > like any unknown route.

   The Orchestrator names that flag after its issue (`issue-<n>`, the number of the child ticket the plan filed). Note it: it is the released flag in `flags.json` and in
   GrowthBook that the `retire-named-flag` task retires on every pass, and the runner never archives it.

3. **Freeze it:** `GITHUB_REPOSITORY=<owner>/ai-factory PYTHONPATH=orchestrator python3 -m monitoring.benchmark freeze --seed-flag issue-<n>` (the flag from step 2), which writes the bench app's current `main` into
   `agents/benchmark/suite.json` as `base_sha` and the flag as `seed_flag`. Commit that file. Every task starts by forcing the bench app's `main` back to this commit.

4. **Take the first baseline** (a pass with no candidate), then `benchmark.py accept` the result and commit `agents/benchmark/baseline.json`.

Never use the bench app for anything else, and tear it down with the `teardown-managed-app` skill when you no longer want it.
