---
title: Count how often a lesson or suggestion recurs, and promote it after N distinct runs
type: task
status: resolved
assignee:
blocked_by: []
---

## Question

The learning loop acts on the first occurrence of a finding and the duplicate check stops a reworded repeat from opening a second issue, but nothing counts how many distinct runs and apps a lesson has appeared in, so there is no way to say "this has come back five times, raise its priority", to decide when a Factory ticket is worth a pull request, or to see that a merged fix did not work beyond the existing fix-ineffective reopen. Add the count (distinct run ids and apps, kept on the issue or in the dashboard data), decide the promotion rule (for example open a Factory fix at N runs rather than at the first), and keep it from double-counting a retry of the same run.

## Added context

- Builds on `similar_open_issue` and the fingerprints in `orchestrator/retrospective.py`; `ARCHITECTURE.md` (Learning loop) lists a weekly pass that clusters near-duplicate lessons as not built.
- Ticket 14 left the "file after N distinct runs" threshold undecided for lack of this; ticket 15's lint rules are proposed on the first occurrence for the same reason.
- Keep it deterministic and model-free; a count per issue can be a hidden comment, as the retry state is.

## Resolution (2026-10-14)

Built; the threshold is a default, not put to the owner. Unit-tested, not run live.

- **The count.** A hidden `<!-- seen:{run url: app} -->` marker in the body of each `factory-learning` issue (lessons, minor findings, factory improvements). Keyed by run URL, so a retry or a double report of one run counts once; distinct apps are derivable from the same marker. `note_sighting`, `with_sighting`, `sightings` in `orchestrator/retrospective.py`. Model-free.
- **Promotion rule.** The retrospective Agent analyses an issue and proposes a fix PR only once `limits.promote_after_runs` (default **2**) distinct runs have seen it. Exempt, acting at once: severe lessons (audit violation, watchdog switch-off), the stuck-run issue, and a lesson reopened as `fix-ineffective`. At the threshold the issue also gets the label `recurring`, as the priority signal. A first sighting is still filed and counted, so nothing is lost; it just does not cost an Agent run and a PR until it comes back. Set the limit to 1 for the old behaviour.
- **Not built.** The weekly clustering of near-duplicate lessons (still not built, listed in ARCHITECTURE.md); managed-app suggestion issues are not counted (no Agent PR is proposed for them). Ticket 15's lint rules and ticket 14's finding thresholds can now use the count: a rule is worth proposing at a `recurring` finding.
- **Worth watching.** With few runs, a real one-off problem waits for its second sighting; the dashboard's lessons-open number shows how many are waiting.
