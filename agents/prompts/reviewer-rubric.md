A finding is **blocking** when it is any of:
- a correctness bug: wrong logic, off-by-one, unhandled error, missing validation of input the code trusts (a missing or malformed body: Express leaves `req.body` undefined when there is no JSON body, so destructuring it throws and answers 500; wrong types; unknown ids), or parsing that accepts malformed input and acts on the wrong record (for example `parseInt("1abc")` deleting item 1)
- a route mounted before the global kill switch in `backend/src/app.ts` (only the health route may be), because the kill switch then does not cover it
- a security problem: injection, path traversal, secrets in code, unsafe handling of user input
- a requirement in `INTAKE.md` that the change does not meet, including any flag it names
- on an **update** to an existing app only: a user-facing change, or a change that alters behavior for every route (middleware, a global error handler), that is not wrapped by a flag checked with `isFeatureEnabled(res, slug)`. One flag around the whole change is enough, so do not ask for a flag per route or screen. A **first build** needs no flags: never report a missing flag on one
- a flag checked in code whose slug is missing from `flags.json`, on any build, because an unrecorded flag is never released
- a flag whose default is set to anything but `false` in the diff (flags fail closed). `isFeatureEnabled(res, slug)` takes no default and already fails closed, so a plain call to it is correct and is not a finding
- code that a test would obviously not catch and the change clearly needs one

A **declared but unused flag** is a **minor** finding: a slug in `flags.json` that no `isFeatureEnabled(res, slug)` call in the repository reads. It would be released with nothing behind it. Look for the slug in the whole repository, not only the diff, because the check may already exist in older code. Quote the `flags.json` entry as evidence.

Anything else is **minor**. Formatting and naming are the formatter's job, so leave them out.
