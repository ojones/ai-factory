# Golden Intakes

Examples of requests the Factory handles well, and of requests it refuses. They show the shape: **say what a person should see, not how to build
it, name the exact words and numbers, and say what must not change.** Intake issues and the app repositories are public: never paste a key,
token or password (the Factory refuses a request that contains one, and the value is already visible).

## A first build (good)

> A small recipe box. A page lists recipes (title and a one-line description). A form with the labels "Title" and "Description" and a button
> "Add recipe" adds one; blank titles show the message "Enter a title". Each recipe has a button "Delete <title>". Data is kept in memory.

Why it works: the visible words are given exactly ("Add recipe", "Enter a title"), the error case is named, and the storage choice is stated.

## An update (good)

> Add GET /api/version that answers 200 with {"version": "1"}. It is a user-visible change, so ship it behind a flag named `version-endpoint`:
> with the flag off, the route answers 404 like any unknown route. Keep all other behaviour unchanged.

Why it works: one behaviour, its status and body, the off state, and "keep everything else". This is Intake #97 on `ojones-todo`.

## An update that needs a decision it states (good)

> Deleting a todo should be undoable. Keep deleted todos for the rest of the session and add a button "Undo delete" that brings back the last
> deleted one. If two are deleted, only the most recent can be undone.

Why it works: where the request could be read two ways, it picks one. If it did not, the planner takes the most conservative reading and records
it as an assumption on the issue.

## Refused: payments

> Let people pay for premium todos with their credit card.

Refused after the planner call (about $0.04): it needs a payment provider account and keys. The comment says what could be built instead, for
example the premium flag without a payment step.

## Refused: a third-party key

> Send me a text message on Twilio when a todo is due. Use account SID `AC...` and auth token `...`.

Refused: it needs a Twilio account, and the value pasted into the request is public. The comment names the kind of secret and says to rotate it.
(If the secret value is present the refusal comes first, before any planning.)

## Refused: personal data

> Store each customer's name, home address and date of birth so we can email them.

Refused: real people's personal data cannot be kept in a public repository's app by the Factory. Made-up sample data is fine.

## Not refused: a mention, not a need

> Add a password field to the login form mockup (no real login, just the form).

Fine: a word is not a need. The planner blocks only a real dependency on a secret, payments or personal data.
