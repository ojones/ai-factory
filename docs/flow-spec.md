# The flow: the numbered spec

This is the official specification of how a request becomes a running, recorded change. Every step has a stable ID (`group.step`, for example `STEP 4.9`, Test the deployed app) so that docs, tickets, tests and verification runs can cite it. [ARCHITECTURE.md](../ARCHITECTURE.md) explains the parts; where it disagrees with this page, this page is the intended behaviour and ARCHITECTURE.md is brought into line. These are the only flow diagrams kept in the repo (the full one and the group-level summary); the older ones were deleted, and a new one is drawn only when it is needed.

**Status.** This is the workflow the code implements. The failure-to-ticket path (6.7, 7.1, 7.6, 8.x) is built (tickets 15b to 15d and 16); the live proof is ticket 17. A fault in the Factory ends at step 7.2 as an issue for a person; no Agent changes the Factory. The plan, order of work and the tickets that close each gap are in `.wayfinder/intake-planning-redesign/`. The "Implemented by" and "Verified by" columns are filled as each group is built and then checked in the last ticket.

**Domains.** Each numbered group is a domain with its own folder under `orchestrator/` (see [ARCHITECTURE.md](../ARCHITECTURE.md#code-layout)): 1 Request (`request`), 2 Planning (`planning`), 3 Staging (`staging`), 4 Build Run (`build_run`), 5 Flag Lifecycle (`flag_lifecycle`), 6 Retrospective (`retrospective`, record and advance included), 7 Try Fix (`try_fix`), 8 Bugs (`bugs`). Maintenance and Monitoring have no steps.

**Rules for changing this page.**
- The full diagram has no edge IDs (`e1@-->`), no `animate` lines and no `linkStyle` lines: the VS Code Mermaid viewers fail to render it with "Cannot read properties of null (reading 'getAttribute')". `flow_spec_test.py` fails when any of them is added.
- IDs are stable. Never renumber a step; add the next free number in its domain, or retire an ID by leaving it in the index marked retired. A step deleted from the diagram and the index together is gone for good, and its ID is never reused.
- Cite a step as `STEP n.m` in any doc; `flow_spec_test.py` fails when a cited ID does not exist, when the diagram and the index disagree, or when an invariant's Step names a step that does not exist.
- An invariant in [invariants.md](invariants.md) names the step it enforces in its Step column.

## Diagram

```mermaid
flowchart TD
    subgraph g1["1. Request"]
        S1_1["<b>1.1 New App Intake submitted</b><br/>owner form, label new-app-intake"]
        S1_2["<b>1.2 Update App Intake submitted</b><br/>owner form, label update-app-intake"]
        S1_3["<b>1.3 Automated change request</b><br/>template sync, maintenance, retirement,<br/>bug Intakes written by Try Fix<br/>filed with the PAT, label update-app-intake"]
    end

    S1_1 --> S2_1
    S1_2 --> S2_1
    S1_3 --> S2_1

    subgraph g2["2. Planning (plan.yml, its own process)"]
        S2_1["<b>2.1 Plan</b><br/>Planner Agent<br/>new app: reads the spec only<br/>update: reads the app's code"]
        S2_2["<b>2.2 Refuse</b><br/>comment: refused"]
        S2_3["<b>2.3 Stop for a person</b><br/>comment on the issue<br/>fix it, remove and re-add the label"]
        S2_4["<b>2.4 File child tickets</b><br/>sub-issues under the parent<br/>each body = complete coding instructions<br/>one flag each, sized to roll back alone<br/>new app with declared secrets: also comments<br/>the names and gh secret set commands"]
        S2_5["<b>2.5 Start the first child</b><br/>planner puts proceed-with-change<br/>on the first child with no dependencies"]
        S2_6{"<b>2.6 Route the child</b><br/>by kind"}
        S2_1 -->|"feasibility blocked"| S2_2
        S2_1 -->|"blocking question, bad plan,<br/>or (existing app)<br/>missing secret"| S2_3
        S2_1 -->|"valid plan"| S2_4
        S2_4 --> S2_5
        S2_5 --> S2_6
    end

    S2_3 -.->|"retry"| S2_1

    subgraph g3["3. Staging (new app only, child 1)"]
        S3_1["<b>3.1 Stage the app</b><br/>stage.sh: repo from Starter, Fly app,<br/>flag service, Intake marker"]
        S3_2["<b>3.2 Verify infrastructure</b><br/>CI green, deploy healthy, flag round trip,<br/>preview token, secrets, smoke test<br/>deterministic checks, no Agent<br/>no business logic, no flag<br/>then the staging child closes and the first business child starts"]
        S3_3["<b>3.3 Wait for the owner's secrets</b><br/>a declared secret name is missing from the new repo<br/>an owner wait, like awaiting_secret: an answer, not a failure<br/>comment: gh secret set NAME -R owner/app<br/>no business child starts, no Agent, no failure event"]
        S3_1 --> S3_2
        S3_2 -->|"a declared secret is missing"| S3_3
        S3_3 -.->|"owner sets each secret,<br/>re-adds proceed-with-change"| S3_1
    end

    S2_6 -->|"staging"| S3_1

    subgraph g4["4. Build (every other child)"]
        S4_1["<b>4.1 Prepare the run</b><br/>read the child body only<br/>Orchestrator ensures flag issue-N exists, OFF"]
        S4_2["<b>4.2 Retire ride-along flags</b><br/>up to 5, oldest first,<br/>never a run of their own"]
        S4_3["<b>4.3 Code</b><br/>CODER Agent commits locally behind the flag<br/>format, build, unit tests incl. flag off and on<br/>a key the plan missed is added to secrets.json;<br/>if its secret is not set the run ends awaiting_secret<br/>(an owner wait) before the Reviewer is paid for"]
        S4_4["<b>4.4 Pre-review check</b><br/>Orchestrator: npm run check<br/>type-check, lint, flag off/on test check"]
        S4_5["<b>4.5 Review</b><br/>REVIEWER Agent reads the local commit<br/>BEFORE anything is pushed"]
        S4_6["<b>4.6 Push</b><br/>Orchestrator pushes with the PAT"]
        S4_7["<b>4.7 CI and dark deploy</b><br/>app CI: Test Gate, then deploy DARK<br/>flag off, nothing visible to users"]
        S4_8["<b>4.8 Diagnose pipeline failure</b><br/>PIPELINE Agent reads the logs<br/>coder fixes, reviewed again before any push"]
        S4_9["<b>4.9 Test the deployed app</b><br/>TESTER Agent runs AFTER the push<br/>Preview Token reaches the dark feature<br/>api-check and ui-check record every result<br/>repo tests, spot-check of behaviour that was live<br/>each check: passed / failed / blocked / not_run<br/>scope: new or existing<br/>regression: behaviour live before the run broke,<br/>or an ungated change (no flag, or flag read by no code) failed"]
        S4_10["<b>4.10 Retest</b><br/>look again at the same deployed commit<br/>(test_retries 1), then needs-human"]
        S4_11["<b>4.11 Roll back the deploy</b><br/>only for a regression (INV-25); no other ending rolls back<br/>rollback-fly: redeploy previous image<br/>flag stays off"]
        S4_12{"<b>4.12 Release gate</b><br/>CI green, deploy healthy,<br/>tester passed, reviewer clean,<br/>same SHA reviewed and pushed"}
        S4_13["<b>4.13 Release</b><br/>existing flag issue-N turned ON<br/>story labelled flag:issue-N<br/>5.8 watches the release"]
        S4_14["<b>4.14 Child fails</b><br/>child stays open, siblings keep waiting"]

        S4_1 --> S4_3
        S4_1 -.->|"at the start of every Build Run"| S4_2
        S4_3 --> S4_4
        S4_4 -->|"fails: back, costs no review"| S4_3
        S4_4 --> S4_5
        S4_5 -->|"blocking findings"| S4_3
        S4_5 -->|"clean"| S4_6
        S4_6 --> S4_7
        S4_7 -->|"CI or deploy fails"| S4_8
        S4_8 --> S4_3
        S4_7 --> S4_9
        S4_9 -->|"failed new check, rounds left<br/>(review_rounds 4, test_rounds 2)"| S4_3
        S4_9 -->|"blocked or not_run"| S4_10
        S4_10 --> S4_9
        S4_9 -->|"existing behaviour broke = regression"| S4_11
        S4_11 --> S4_14
        S4_9 -->|"all checks passed"| S4_12
        S4_9 -->|"coder rounds (review and pipeline fixes), cost cap<br/>or time limit used up"| S4_14
        S4_12 -->|"pass"| S4_13
        S4_12 -->|"a gate does not hold"| S4_14
    end

    S2_6 -->|"update"| S4_1

    subgraph g5["5. Flag lifecycle (short-lived by design)"]
        S5_1["<b>5.1 Dark</b><br/>flag off, code deployed"]
        S5_2["<b>5.2 Released</b><br/>flag ON for everyone"]
        S5_3["<b>5.3 Eligible for retirement</b>"]
        S5_4["<b>5.4 Retired</b><br/>coder deletes the flag check, the flag-off tests<br/>and the flags.json line in its own commit; unwraps flag-on tests<br/>verifier rejects the commit while issue-N appears anywhere<br/>TESTER checks the behaviour is still on for an ordinary visitor<br/>flag archived in GrowthBook, story comment says so"]
        S5_5["<b>5.5 Dark-broken candidate</b><br/>the watchdog (5.8) switched it off<br/>flag stays off; its child is failed and waits for a fix, then runs again behind it"]
        S5_6["<b>5.6 Owner approves retirement</b><br/>adds approve-retire to the story"]
        S5_8["<b>5.8 Watch the release</b><br/>watchdog, ten minutes after 4.13<br/>health check fails in a row, or new error lines<br/>switches off only the flags its own run released"]
        S5_7["<b>5.7 Retirement intake</b><br/>update-app-intake, planned, one child, no flag<br/>deletes check, code, tests, flags.json line<br/>nothing removes a dark feature on its own"]
        S5_1 --> S5_2
        S5_2 -->|"a LATER Build Run also ends released<br/>and at least 1 day has passed"| S5_3
        S5_8 -->|"trips: the watchdog switches the flag off"| S5_5
        S5_5 -->|"fixed and released"| S5_2
        S5_5 -->|"cause not fixable:<br/>needs-human + dark-broken"| S5_6
        S5_6 --> S5_7
        S5_7 --> S5_4
    end

    S5_3 --> S4_2
    S4_2 --> S5_4
    S4_13 --> S5_2
    S4_13 --> S5_8
    S4_1 -.->|"flag created OFF"| S5_1

    S3_2 --> S6_1
    S4_13 --> S6_1

    subgraph g6["6. Record and advance"]
        S6_1["<b>6.1 Child closed</b>"]
        S6_2["<b>6.2 Retrospective</b><br/>finalize + retrospective Agent<br/>(every run, always)<br/>summary, lessons, names the cause<br/>and judges every event of the run:<br/>failures and warnings, verdict fix or record"]
        S6_3["<b>6.3 Advance to the next child</b><br/>next waiting child whose dependencies<br/>are closed gets proceed-with-change"]
        S6_4["<b>6.4 Parent closes</b><br/>last child closed"]
        S6_5(["<b>6.5 App live and recorded</b>"])
        S6_6["<b>6.6 Ongoing signals</b><br/>template sync, maintenance, owner requests"]
        S6_7["<b>6.7 Judge events with no run</b><br/>production errors, escaped defects,<br/>a failed staging check<br/>(not a missing secret, 3.3)<br/>one batch per scan, same Agent and verdicts<br/>(a scan has no Build Run to finalize)"]
        S6_1 --> S6_2
        S6_2 -->|"child succeeded"| S6_3
        S6_3 -->|"last child closed"| S6_4
        S6_4 --> S6_5
        S6_5 --> S6_6
    end

    S4_14 --> S6_2
    S6_3 -->|"more children"| S2_6
    S6_6 --> S1_3
    S6_5 --> S1_2

    subgraph g7["7. Try fix (fix first, never retry the unchanged child)"]
        S7_6["<b>7.6 Write the bug ticket</b><br/>Try Fix Agent, one job: a good ticket<br/>from the bug template: how it was found,<br/>root cause, what it takes to resolve,<br/>numbered checkable requirements<br/>never decides cause or target, never plans"]
        S7_1["<b>7.1 File the bug Intake</b><br/>update-app-intake + bug, filed with the PAT<br/>planned by 2.1 like any Intake<br/>failed child: marker fix_for,<br/>exactly one child with a flag of its own, blocks the failed child<br/>released story: no marker, blocks nothing"]
        S7_2["<b>7.2 Factory fix request (the pipeline stops here)</b><br/>same bug template, written for a person, in ai-factory<br/>factory-fix-request issue, each repeat a Failed again comment<br/>nothing reads the label: a person fixes the Factory by hand"]
        S7_4["<b>7.4 Resume the failed child</b><br/>the bug Intake closes: the story gets a<br/>solution comment, the origin parent advances"]
        S7_5["<b>7.5 Needs human</b><br/>nothing runs until the owner edits and re-labels"]
        S7_2 -->|"the failed child waits"| S7_5
        S7_6 --> S7_1
        S7_6 -->|"factory target"| S7_2
        S7_1 -->|"bug Intake closes"| S7_4
    end

    S6_2 -->|"verdict fix, app cause<br/>(code wrong, spec ambiguous)"| S7_6
    S6_7 -->|"verdict fix"| S7_6
    S7_1 -->|"plan the bug Intake"| S2_1
    S6_2 -->|"verdict fix, factory cause"| S7_6
    S6_2 -->|"no cause found / infrastructure"| S7_5
    S7_4 --> S4_1
    S3_2 -->|"any other check fails"| S6_7

    subgraph g8["8. Bugs found later"]
        S8_1["<b>8.1 Bug while still dark</b><br/>flag never released, off,<br/>or switched off by the watchdog:<br/>failure comment on the same story,<br/>the open child waits for its fix"]
        S8_2["<b>8.2 Validated release</b><br/>flag released and still on:<br/>feature is fully released"]
        S8_3["<b>8.3 Watch production</b><br/>production feedback, a scan every six hours<br/>Fly errors, escaped-defect issue<br/>each finding becomes an event"]
        S8_4["<b>8.4 Regression</b><br/>a bug now is a REGRESSION:<br/>new bug Intake, nothing waits,<br/>comment on the story linking it"]
        S8_3 --> S8_1
        S8_3 --> S8_2
        S8_2 -->|"a bug now"| S8_4
    end

    S6_5 --> S8_3
    S8_3 -->|"events"| S6_7
    S8_1 -->|"how to file: fix_for"| S7_1
    S8_4 -->|"how to file: no marker"| S7_1
    S5_5 -.-> S8_1

```

## Diagram: how the groups connect

The same flow with each group collapsed to one box. Round boxes are what sits outside every group and still acts on one: the Owner, Monitoring, Scheduled upkeep (Maintenance and the Starter Template) and Services (Fly and GrowthBook). Dashed lines come from outside a group or are optional. This is a summary of the diagram above: when an edge there crosses a group, it appears here.

```mermaid
flowchart TD
    owner(["Owner (a person)<br/>forms, secrets, approve-retire, edits and re-labels,<br/>fixes the Factory by hand"])
    mon(["Monitoring (no steps)<br/>benchmark, canary, dashboard, Fly audit"])

    subgraph upkeep["Scheduled upkeep"]
        maint(["Maintenance (no steps)<br/>template sync, dependency updates"])
        starter(["Starter Template"])
    end

    subgraph services["Services"]
        fly(["Fly<br/>app, deploys, rollback, errors"])
        gb(["GrowthBook<br/>flag service"])
    end

    G1["<b>1. Request</b>"]
    G2["<b>2. Planning</b>"]
    G3["<b>3. Staging</b><br/>new app, child 1"]
    G4["<b>4. Build</b><br/>every other child"]
    G5["<b>5. Flag lifecycle</b>"]
    G6["<b>6. Record and advance</b><br/>incl. Retrospective"]
    G7["<b>7. Try fix</b>"]
    G8["<b>8. Bugs found later</b>"]

    G1 -->|"Intake issue"| G2
    G2 -->|"staging child"| G3
    G2 -->|"update child"| G4
    G3 -->|"child closed,<br/>or a failed check other than a missing secret"| G6
    G4 -->|"child closed or failed"| G6
    G4 -->|"flag created OFF, released, watched (5.8), retired"| G5
    G5 -->|"eligible: retired as a ride-along"| G4
    G5 -.->|"retirement Intake"| G1
    G5 -->|"dark-broken flag"| G8
    G6 -->|"next child"| G2
    G6 -->|"ongoing signals, app live:<br/>automated and update Intakes"| G1
    G6 -->|"verdict fix, or no cause"| G7
    G6 -->|"app live and recorded"| G8
    G8 -->|"events with no run"| G6
    G8 -->|"how to file the bug Intake"| G7
    G7 -->|"bug Intake to plan"| G2
    G7 -->|"bug Intake closed:<br/>resume the failed child"| G4

    owner -.->|"New and Update App Intake forms"| G1
    owner -.->|"fix and re-label a stopped plan"| G2
    owner -.->|"sets the declared secrets (3.3),<br/>re-adds proceed-with-change"| G3
    owner -.->|"approve-retire"| G5
    owner -.->|"edit and re-label (7.5)"| G7
    G7 -.->|"Factory fix request (7.2)"| owner
    maint -.->|"change requests"| G1
    starter -.->|"repo for a new app"| G3
    starter -.->|"template changes"| maint
    mon -.->|"benchmark Intakes"| G1
    G3 -->|"provisions"| fly
    G4 -->|"deploys dark, rolls back"| fly
    fly -.->|"errors, escaped defects"| G8
    G3 -->|"creates the flag service"| gb
    G4 -->|"flag issue-N"| gb
    G5 -->|"turns on, archives"| gb
```

## Diagram: finding and adding keys

How a third-party key is found and supplied. Built (not yet seen live): the Coder lists any key the plan missed in secrets.json and carries on, the Orchestrator adds those names to the child ticket's list (another `factory-secrets` comment on the ticket being run, so a re-run asks for them from the start), and the same missing-name check runs once more right after the Coder, before the Reviewer is paid for. There is no Coder stop and no second file: a key is one more name in a list that already exists, and a missing one is the owner wait that already exists (an answer, not a failure: no retry, no failure event, no bug Intake, no lesson, the Intake stays open). These are part of steps 4.3 (INV-48, INV-49) and have no step of their own.

```mermaid
flowchart TD
    subgraph plan["Planning (2.1 to 2.4)"]
        K1["<b>Planner lists every key</b><br/>across all change sets, not only the first<br/>existing app: reads the app's secrets.json first<br/>a service the request leaves unnamed:<br/>one free-tier provider, recorded as an assumption"]
        K2{"app?"}
        K3["<b>Existing app: stop (2.3)</b><br/>awaiting_secret if a name is missing<br/>one comment, every gh secret set command"]
        K4["<b>New app: file the children (2.4)</b><br/>comment lists every name"]
        K1 --> K2
        K2 -->|"existing"| K3
        K2 -->|"new"| K4
    end

    subgraph stage["Staging (new app only, 3.2, 3.3)"]
        K6["<b>Check the declared names</b><br/>gh secret list, names only"]
        K7["<b>Owner wait (3.3)</b><br/>the commands for the names still missing"]
        K6 -->|"a name is missing"| K7
    end

    K4 --> K6

    owner(["<b>Owner</b><br/>runs gh secret set NAME -R owner/app for each name<br/>the command prompts, so no value reaches an issue or a log<br/>re-adds the label"])

    K3 -.-> owner
    K7 -.-> owner
    owner -.->|"re-add the Intake label"| K1
    owner -.->|"re-add proceed-with-change"| K5

    subgraph build["Build Run"]
        K5["<b>Setup check (4.1), every start</b><br/>every name in the Intake's list<br/>must exist as a GitHub Actions secret"]
        K8["<b>Code (4.3)</b><br/>reads each key from process.env, in one place<br/>lists every key, including any the plan missed,<br/>in secrets.json with its purpose, never a value"]
        K9["<b>Accept new names (4.3)</b><br/>a name the plan did not declare is allowed<br/>if it passes the name rules and is not a Factory name<br/>it is added to the ticket's list"]
        K10["<b>Invalid name</b><br/>rejected as today: the Coder is told and fixes it"]
        K11["<b>Check before the review (4.3)</b><br/>after every Coder round, before the Reviewer<br/>every name must exist as a secret"]
        K12["<b>Owner wait: awaiting_secret</b><br/>one comment, every missing command<br/>no Reviewer, push or deploy has happened"]
        K14["<b>Review, push and dark deploy (4.5 to 4.7)</b><br/>the deploy copies the declared names"]
        K5 -->|"a name is missing"| K12
        K5 -->|"all set"| K8
        K8 --> K9
        K9 -->|"invalid"| K10
        K10 --> K8
        K9 -->|"valid"| K11
        K11 -->|"a name is missing"| K12
        K11 -->|"all set"| K14
    end

    K12 -.-> owner
```

## Diagram: proposal, one fix per story, planned from its ticket

**Proposal, not built.** Nothing in the code or the step index reflects this yet, and the numbered diagram above still shows today's flow (a bug Intake goes through 2.1). Two changes are proposed, and only the part that changes is drawn: from the Retrospective's `fix` verdicts to the start of the fix child.

**Group by story (new step 7.7).** Today every `fix` verdict becomes its own ticket and bug Intake, so two failure events on one dark story file two fix children that both block the same failed child, each computing the same attempt number. The proposal groups the `fix` verdicts in code, by `(app, story, target)`, before the Try Fix Agent runs: one group gives one ticket and one bug Intake. Verdicts stay per event (INV-58), an event with no story id and an app fix against a Factory fix are never merged, and the Agent plays no part in the grouping. Grouping by shared root cause across stories is left out on purpose.

**Plan a fix from its ticket (new step 2.7).** Today a bug Intake with `fix_for` is planned by the Planner Agent (2.1) even though the outcome is fixed: exactly one change set (INV-39, `planning/fix_for.py` tells the Planner so), and the Try Fix Agent (7.6) has already written numbered, checkable requirements. The Planner call turns those requirements into a change set the ticket already describes. The proposal drops that model call for a `fix_for` Intake and builds the one change set from the ticket in code (new step 2.7). Everything around it stays: `plan.yml` still starts on the label and still scans for secret values (INV-56, INV-40), the child is still filed as a sub-issue by 2.4, blocks the failed child, and runs through the same Build Run.

```mermaid
flowchart TD
    R6["<b>6.2 Retrospective</b><br/>verdict fix, app cause"]
    R77["<b>7.7 Group the fix verdicts (NEW)</b><br/>Orchestrator, no model call<br/>one group per app, story and target<br/>verdicts stay per event, one primary event key<br/>the daily warning cap still counts events"]
    R76["<b>7.6 Write the bug ticket</b><br/>Try Fix Agent, once per group<br/>numbered, checkable requirements<br/>covering every event in the group"]
    R71["<b>7.1 File the bug Intake</b><br/>update-app-intake + bug, marker fix_for<br/>the Intake is the parent of the fix child"]
    R20["<b>plan.yml starts</b><br/>on the label; scans for secret values (unchanged)"]
    RD{"<b>Marker fix_for?</b>"}
    R21["<b>2.1 Plan</b><br/>Planner Agent<br/>only a bug Intake with no marker (8.4)<br/>and every ordinary Intake"]
    R27["<b>2.7 Plan a fix from its ticket (NEW)</b><br/>Orchestrator, no model call<br/>one change set: title and criteria are the ticket's<br/>numbered requirements, flag true<br/>same limits as any plan (size, at most 6 criteria)"]
    R23["<b>2.3 Stop for a person</b><br/>requirements missing or over the limits<br/>fix the ticket, remove and re-add the label"]
    R24["<b>2.4 File the child ticket</b><br/>one sub-issue under the bug Intake<br/>blocks the failed child, fix_attempt counted (unchanged)"]
    R25["<b>2.5 Start the child</b><br/>proceed-with-change"]
    R41["<b>4.1 Prepare the run</b><br/>Build Run as today"]

    R6 --> R77
    R77 --> R76
    R76 --> R71
    R71 --> R20
    R20 --> RD
    RD -->|"no"| R21
    RD -->|"yes"| R27
    R27 -->|"valid"| R24
    R27 -->|"invalid"| R23
    R21 --> R24
    R24 --> R25
    R25 --> R41

    classDef changed fill:#cfe5d9,stroke:#4a8f6d,stroke-width:2px,color:#1d3a2c
    class R77,R27,RD changed
```

What is saved and what is risked:

- **Saved:** one bug Intake and one fix child per story instead of one per event, no two fix children racing to unblock the same failed child, one model call and its latency per bug Intake, and the Planner's failure modes on a fix (a rejected plan, a question, a "blocked" verdict). Today each of those stops the fix for a person (2.3) even though the ticket was already validated by 7.6.
- **Not changed:** a bug Intake with no marker (a regression on a released flag, 8.4) can still need several change sets, so it keeps the Planner. The Try Fix Agent (7.6) stays; merging it into the Retrospective is a separate idea.
- **Open points for grouping:** the group's dedupe key is the primary event's key, so a repeat of any member must still find the open Intake and add a "Seen again" comment; the Try Fix Agent's input and the 6-criteria limit must hold for several events at once (trim, or keep the failure's requirements first); INV-26, INV-39 and INV-58 need their wording moved from "event" to "group of events on one story".
- **Open points for 2.7:** the feasibility check (`blocked` for payments, an outside service and so on) currently also runs on the Planner's answer; for a fix it would have to run on the ticket's text or be judged unnecessary, because the failed child already passed it. A fix never declares new secrets today; if one needs a key the Coder's found-key path (4.3) is the route.

## Diagram: proposal, one secret check at the start of every run

**Proposal, not built.** A declared third-party secret is checked in four places today: planning for an existing app (2.3), the staging check for a new app (3.3), the start of every Build Run (4.1) and after each Coder round (4.3). The proposal keeps the last two and drops the first two. 4.1 already runs before any Agent (`run.py` calls `setup()`, which requires the declared names, before the first Coder round), so no model call is saved by checking earlier. The staging check (3.2) keeps checking the Factory's own staging secrets (`FLY_API_TOKEN`, `GROWTHBOOK_CLIENT_KEY`, `PREVIEW_TOKEN`) and stops looking at the app's declared names, which the starter-template smoke test never uses. The owner still gets the names and `gh secret set` commands early: for a new app, 2.4 comments them when it files the children, and for an existing app the Planner's plan comment carries them. Only the gate goes, not the heads-up.

```mermaid
flowchart TD
    M21["<b>2.1 Plan</b><br/>Planner lists every key it can see,<br/>recorded on the Intake as names"]
    M24["<b>2.4 File child tickets</b><br/>comments the names and gh secret set commands<br/>(unchanged; no check, no stop)"]
    M32["<b>3.2 Verify infrastructure (new app)</b><br/>checks the Factory's staging secrets only<br/>no longer the app's declared names"]
    M41["<b>4.1 Prepare the run</b><br/>every name on the Intake must exist<br/>as a GitHub Actions secret, before any Agent"]
    M43["<b>4.3 Code</b><br/>a key the plan missed is added to secrets.json<br/>checked right after the Coder round, before the Reviewer"]
    MW["<b>Owner wait: awaiting_secret</b><br/>one comment, every missing gh secret set command<br/>not a failure: no retry, fix request or lesson<br/>owner re-adds proceed-with-change"]
    MX["<b>DROPPED</b><br/>2.3 planning stop for an existing app<br/>3.3 wait at staging for a new app<br/>the 6.7 and group diagram exceptions for 3.3"]

    M21 --> M24
    M24 --> M32
    M32 --> M41
    M41 -->|"a name is missing"| MW
    M41 -->|"all set"| M43
    M43 -->|"a found key is missing"| MW
    MW -.->|"owner sets the secrets"| M41

    classDef changed fill:#cfe5d9,stroke:#4a8f6d,stroke-width:2px,color:#1d3a2c
    classDef retired fill:#e8e8e8,stroke:#999,stroke-dasharray:5 5,color:#666
    class M32,M24 changed
    class MX retired
```

## Step index

"Implemented by" names the tickets that built the step (the domain tickets in `.wayfinder/intake-planning-redesign/`); "Verified by" names its unit tests, its invariants (INV-n) and what was seen live (ai-factory#140 and #145 on `factory-bench`, 2026-10-20). Walked in ticket 18; the gaps it found are ticket 19 (open) and ticket 20 (closed), and the steps with no live sighting are listed in ticket 17.

| ID | Title | Actor | Main code today (or new) | Implemented by | Verified by |
|---|---|---|---|---|---|
| 1.1 | New App Intake submitted | owner | `ISSUE_TEMPLATE/new-app-intake.yml` | 06 | live #140 (the form's issue shape only; no unit test of the form) |
| 1.2 | Update App Intake submitted | owner | `ISSUE_TEMPLATE/update-app-intake.yml` | 06, 13 | INV-22; plan_run_test; live #145 |
| 1.3 | Automated change request | maintenance, template_sync, flag_lifecycle, try_fix | each module's `file_*`, `try_fix/file_bug.py` | 06, 15d | INV-33, INV-35; maintenance tests; file_bug_test; live: scheduled sources only, no bug Intake yet |
| 2.1 | Plan | Planner Agent | `planning/plan_run.py` (`plan.yml`), `planning/validate_plan.py` | 09, 13 | plan_run_test, validate_plan_test; INV-54, INV-56; live #140 (four attempts), #145 |
| 2.2 | Refuse | Orchestrator | `planning/triage.feasibility`, `Refused` | 09, 13 | triage tests, refusal_test; INV-40; no live refusal |
| 2.3 | Stop for a person | Orchestrator | `NeedsHuman`, `AwaitingSecret` (an existing app only; a new app has no repository to check, see 3.3) | 09, 13 | plan_run_test, secrets_check_test; INV-48; live: needs_human twice on #140 |
| 2.4 | File child tickets | Orchestrator | `planning/file_children.py`, `shared/child_tickets.py` | 09 | file_children_test, child_tickets_test; INV-48, INV-54, INV-56; live #140, #145 |
| 2.5 | Start the first child | Orchestrator | `retrospective/close_child.ready_to_start` | 09, 10 | close_child_test (ready_to_start); INV-24, INV-55; live: #141, #146 started by the planner, #142, #147 by the advance |
| 2.6 | Route the child | Orchestrator | `factory-plan` marker `kind` | 12, 14 | staging/route_child_test, INV-57, INV-61; live #140, #145 |
| 3.1 | Stage the app | stage.sh | `infra/app-staging/stage.sh`, `staging/read_staging_child.py` | 14 | stage_script_test, read_staging_child_test; INV-57; live #141 |
| 3.2 | Verify infrastructure | Orchestrator | `staging/verify_infrastructure.py` | 14 | verify_infrastructure_test; INV-48, INV-57; live #141 (six checks passed) |
| 3.3 | Wait for the owner's secrets | owner | `staging/verify_infrastructure.secret_commands`, `waiting_on_owner`, `planning/secrets_check.new_app_comment` | 14 | verify_infrastructure_test (the report, and no failure event), plan_run_test; INV-48, INV-57; not seen live |
| 4.1 | Prepare the run | Orchestrator | `build_run/prepare_run.py`, `flag_lifecycle/flag_slug.ensure_feature` | 08b, 11, 12 | prepare_run_test; INV-10, INV-18, INV-50, INV-51, INV-55; live #142 (flag issue-142) |
| 4.2 | Retire ride-along flags | Orchestrator, Coder | `flag_lifecycle.retirement_selection.piggyback_slugs` | 08c | retirement_selection_test; INV-37; no live run with a ride-along flag |
| 4.3 | Code | Coder Agent | `agents/prompts/coder.md`, `build_run/write_code.require_found_secrets` | 11 | agent prompts, write_code_test (found secrets); INV-01, INV-02, INV-09, INV-12, INV-13, INV-21, INV-32, INV-34, INV-41, INV-48, INV-49; smoke-coder; live #142, #146 |
| 4.4 | Pre-review check | Orchestrator | `limits.precheck`, Starter `scripts/check-flags.mjs` | 08c | check-flags.mjs; INV-47, INV-53; live #142 |
| 4.5 | Review | Reviewer Agent | `reviewer.md`, `build_run/review_code.py` | 11 | review_code_test; INV-04, INV-11, INV-46; live #142 |
| 4.6 | Push | Orchestrator | `build_run/ship_code.py` | 11 | ship_code_test; INV-42; live #142 |
| 4.7 | CI and dark deploy | app CI | Starter workflows | Starter | INV-16 (Starter workflows, no kill switch); live #142 (CI and dark deploy) |
| 4.8 | Diagnose pipeline failure | Pipeline Agent | pipeline role | 11 | ship_code_test (the diagnosis, retries and coder fixes), run_test; INV-62; no live pipeline failure |
| 4.9 | Test the deployed app | Tester Agent | `tester.md`, `build_run/verify_deployed_app.py`, `shared/api_check.py`, `build_run/ui_check.py` | 11 | verify_deployed_app_test, api_check_test, ui_check_test; INV-05, INV-08, INV-28, INV-30, INV-36, INV-44; live #142 |
| 4.10 | Retest | Orchestrator | `limits.test_retries` | 11 | run_test (retests); no live retest |
| 4.11 | Roll back the deploy | Orchestrator | `rollback-fly.yml` | 11 | rollback_test; INV-25; no live regression |
| 4.12 | Release gate | Orchestrator | `build_run/gate_release.py` | 11 | gate_release_test; INV-03; live #142 |
| 4.13 | Release | Orchestrator | `build_run/gate_release.py`, `flag_lifecycle/` | 08, 11 | gate_release_test; INV-06, INV-52; live #142 (clean watch; a trip not seen) |
| 4.14 | Child fails | Orchestrator | `retrospective/close_child.finish_update_intake` | 10, 11, 15d | finalize_test, close_child_test; INV-19, INV-29; live: #147 stopped provider_blocked and was left without the start label |
| 5.1-5.7 | Flag lifecycle | Orchestrator | `flag_lifecycle/`, `retrospective/app_state.py` | 08, 08b, 08c | flag_lifecycle tests, app_state_test; INV-37, INV-38, INV-43, INV-51, INV-53; live: 5.1, 5.2 (issue-142, issue-146); 5.3 to 5.7 not seen |
| 5.8 | Watch the release | Orchestrator | `flag_lifecycle/watchdog.py`, `build_run/gate_release.py` | 08 | watchdog_test; INV-07; live #142 (clean watch; a trip not seen) |
| 6.1 | Child closed | Orchestrator | `retrospective/close_child.finish_update_intake` | 10 | close_child_test; live #141, #142, #146 |
| 6.2 | Retrospective | Retrospective Agent | `retrospective/finalize.py`, `retrospective/run_retrospective.py`, `retrospective/cause.py`, `retrospective/event_verdicts.py` | 10, 15b | finalize_test, cause_test, event_verdicts_test; INV-17, INV-20, INV-45, INV-58; live: released runs and one provider_blocked; no failure with a cause |
| 6.3 | Advance to the next child | Orchestrator | `retrospective/close_child.advance` | 10 | close_child_test; INV-23; live: #141 to #142, #146 to #147 |
| 6.4 | Parent closes | Orchestrator | `retrospective/close_child.advance` | 10 | close_child_test; live #140 |
| 6.5 | App live and recorded | Orchestrator | `retrospective/app_state.py` | 10 | app_state_test; live: the App State issue was not read |
| 6.6 | Ongoing signals | scheduled workflows | `template_sync`, `maintenance` | 07 | dependency_updates_test, template_sync_test; INV-33, INV-35; live: scheduled runs succeed daily |
| 6.7 | Judge events with no run | Retrospective Agent | `retrospective/judge_events.py`, `retrospective/event_verdicts.py` | 15b | judge_events_test, event_verdicts_test; INV-58; no live batch yet (production-feedback.yml runs every six hours) |
| 7.1 | File the bug Intake | Orchestrator | `try_fix/file_bug.py`, `planning/fix_for.py`, `retrospective/close_child.settle_fix` | 15, 15d | file_bug_test, file_failure_test; INV-15, INV-26, INV-27, INV-39; no live bug Intake |
| 7.2 | Factory fix request | Orchestrator | `try_fix/factory_fix_request.py`, bug template (ticket 15c) | 15, 15d | factory_fix_request_test, file_bug_test; INV-14, INV-26; no live Factory cause |
| 7.4 | Resume the failed child | Orchestrator | `retrospective/close_child.advance` | 15, 15d | close_child_test (settle_fix); INV-27; no live resume |
| 7.5 | Needs human | Orchestrator | `try_fix/needs_human.py` | 15 | file_bug_test, file_failure_test; INV-27; live: only the provider alert (#148) |
| 7.6 | Write the bug ticket | Try Fix Agent | `try_fix/write_bug.py`, `try_fix/validate_bug.py`, `try_fix/render_bug.py` | 15c | write_bug_test, validate_bug_test, render_bug_test; INV-59; the model's tickets unmeasured |
| 8.1-8.4 | Bugs found later | bugs domain | `bugs/scan_production.py`, `bugs/scan_logs.py`, `bugs/escaped_defects.py`, `bugs/route_bug.py`, `bugs/to_event.py`, `bugs/flood_limits.py`; `try_fix/file_events.py` | 16 | bugs tests (scan_logs, flood_limits, route_bug, to_event, scan_production), file_events_test; INV-31, INV-60; no live production error |

## Flag lifecycle mechanics

Group 5, with STEP 4.1 to 5.8. One story, one flag; short-lived; retired by riding along in a later run; a dark-broken feature removed only after `approve-retire`. The mechanics are deterministic and named after the issue (the why is in [ARCHITECTURE.md](../ARCHITECTURE.md#release-and-retirement)):

- **Name (built).** The slug is `issue-<n>`, `<n>` the number of the story's issue (an issue that runs again keeps its flag). The planner no longer chooses a slug; it only says whether the change set is flagged (`flag: true`) or internal only. The GrowthBook key stays `<app-slug>.feature.issue-<n>`.
- **Created at the start of the Build Run (built).** The Orchestrator creates the GrowthBook feature (production off, description linking the story issue, tag `intake-<n>`) and writes the `flags.json` entry in a local commit before the coder starts, so the coder only wraps code and the flag exists while the coder and tester work. Release only switches production on the story's own flag, after the same four gates, and never creates a flag. Existing flags are never touched. **A flag that does not exist at release** means one of two things. If the code reads it, the change is deployed dark with nothing to turn it on: the run ends as a failure (`flag_missing`), nothing is rolled back, and the failure says that a flag which can be turned on has to be added in the next round. If no code reads it, the change went live on deploy with no gate: if the tests found no problem it is left alone with a note, and if they found a failure the deploy is rolled back like any regression. Either way the run records what was missing and a guess why (`flag_notes` in the Report), so the retrospective can recommend a fix to the Orchestrator or the app.
- **Watched after release (built, INV-07).** Step 5.8 is the watchdog: for `watchdog_minutes` after 4.13 it samples the deployed app every `watchdog_interval_seconds`, and trips when the health check fails `watchdog_max_failures` times in a row or the error-level log lines rise by `watchdog_max_errors` over the count before the release. A trip switches off in GrowthBook only the flags its own run released and the feature becomes 5.5. The production scan (8.3) is a separate, later watch.
- **Dark mode is unit tested (built, INV-53).** The Starter provides a test helper `withFlag(slug, on, fn)`, and `npm run check` fails a commit when a slug in `flags.json` lacks a flag-off test or a flag-on test, or has more than one entry point.
- **Retirement removes the tests too (built, INV-53).** The coder deletes the flag check, the `flags.json` line and the flag-off tests, and unwraps the flag-on tests, in its own commit; the Orchestrator rejects the commit while the slug still appears in code, tests or `flags.json` (comments aside). Only the owner-approved `approve-retire` is planned, as one child with no flag.
- **A failure is fixed through a bug Intake** (STEP 7.1, `fix_for`) instead of an automatic retry of the unchanged issue; the fix child has its own flag, and the failed child runs again behind its own.
- **Bugs after release.** While the flag is dark or off the work is not finished and the same story stays open; once the flag has been released and is still on a bug is a regression, filed by Try Fix as a new bug Intake planned like any change (STEP 8.4). A flag the watchdog switched off counts as dark: the child is failed and waits for its fix.

## From a failure to a fix

One rule for every failure and warning, whatever found it (a failed child, a failed staging check other than a missing secret, the watchdog, a production error, an escaped defect, a dark-only test failure, a check that could not be run). Each Agent has one job.

1. **An event.** Whatever finds it writes a failure event: source, severity (`failure` or `warning`), app, the story it belongs to if any, a fingerprint, a summary and the evidence. A Build Run's events come from its facts; a scan's events (8.3, a failed staging check 3.2 other than a missing secret, which is 3.3) are handed to the Retrospective.
2. **A verdict (6.2, 6.7).** The Retrospective Agent alone names the cause and the target (`managed_app` or `factory`) and gives every event a verdict, `fix` or `record`, with a reason. A failure is always `fix`; a warning is `record` unless the Agent says why a fix is worth it. A scan with no Build Run is judged in one batch (6.7). `record` keeps today's learning record and files nothing; the Factory no longer files Suggestion issues in a Managed App's repo.
3. **A ticket (7.6).** The Try Fix Agent writes one bug ticket from the bug template for each `fix` verdict. It does not decide the cause or target, and it does not plan or split work. If it fails or its output does not validate, the Orchestrator writes the ticket from the facts.
4. **An Intake or a request (7.1, 7.2).** An app fix is an `update-app-intake` labelled `bug`, planned by 2.1, so it has the same size and criteria limits as any change. A Factory cause (`orchestrator_gap`, `prompt_gap`, `template_gap`, `plan_gap`) is one `factory-fix-request` issue in ai-factory (7.2), written for a person, with each repeat a "Failed again" comment. That is where the pipeline stops: no workflow reads the label, no Agent plans or changes the Factory, and the failed child is held `needs-human` (7.5) until the person who fixed the Factory adds `proceed-with-change` again.
5. **Dark or released.** If the story's flag was never released, is off, or was switched off by the watchdog (8.1), the failure is added as a comment on the story, the bug Intake carries `fix_for` (the failed child), the plan has exactly one child, an ordinary child with a flag of its own (or none), and the failed child waits on it. If the flag was released and is still on (8.2), a bug is a regression (8.4): a new bug Intake with no marker that nothing waits for, and the story gets a comment linking it.
6. **Closing the loop (7.4).** When the bug Intake closes, the story gets a solution comment and the origin parent advances; the failed child resumes through the normal advance and runs again behind its own flag, which already exists, off.
7. **Bounded.** A fix that fails is handled like any failed child: a follow-up bug Intake whose `fix_for` is the failed fix. Attempts are counted along that chain back to the original story; after `fix_attempts_max` (2) the child is held `needs-human` and nothing more is filed. One bug per event key.
