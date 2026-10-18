# How the Orchestrator finds and applies updates to Managed Apps

Sources: `ARCHITECTURE.md` (Intake, Update Intake), `.github/workflows/*.yml`, `orchestrator/{template_sync,maintenance,production_feedback,update_intake,fixrequest,flag_retirement}.py`, `orchestrator/build_run.py`.

Five small diagrams, each one stage. Whatever finds a change, it ends as an `update-intake` issue that gets `proceed-with-change`, and the same Build Run handles it. Nothing edits an app directly.

## 0. The whole thing in one line each

```mermaid
flowchart LR
    A["1. Find a change<br/>(triggers)"] --> B["2. Start<br/>(label + plan)"]
    B --> C["3. Build Run<br/>(code, test, review)"]
    C --> D["4. Release<br/>(flag on + watchdog)"]
    C --> E["5. Record + learn"]
    D --> E
    E -->|"failure: retry, fix request, retire"| A
```

## 1. What finds a change

Each one files an Update Intake issue in ai-factory and puts `proceed-with-change` on it with the PAT (labels added with the Actions token would not start workflows).

```mermaid
flowchart TD
    OWNER["Owner files the Update Intake form"]
    TS["Template sync<br/>nightly 07:47 UTC<br/>app seeded before latest Starter change"]
    MNT["Maintenance<br/>daily 08:07 UTC<br/>app's open Dependabot PRs (npm, Docker)"]
    PF["Production feedback<br/>every 6 h<br/>Fly error logs by fingerprint<br/>or owner-written escaped-defect issue"]
    RETRY["Fix-request retry<br/>(see diagram 5)"]
    RET["approve-retire label<br/>on a dark-broken story"]

    FLOOD{{"Flood control<br/>one open Intake per fingerprint and app,<br/>daily cap, owner-written text only"}}
    PF --> FLOOD

    OWNER --> ISSUE
    TS --> ISSUE
    MNT --> ISSUE
    FLOOD --> ISSUE
    RETRY -->|"same issue, same flag"| ISSUE
    RET -->|"Intake that deletes flag, code, tests"| ISSUE

    ISSUE["Update Intake issue<br/>labelled proceed-with-change"]
```

## 2. Start and plan

```mermaid
flowchart TD
    ISSUE["Issue labelled proceed-with-change"] --> UI["update-intake.yml<br/>update_intake.py start"]
    UI -->|"app repo missing or no Intake marker"| REFUSE["Comment, remove label"]
    UI -->|"adds app:slug, dispatches Build Run"| PLAN["Planner<br/>change sets, acceptance criteria, flag slug"]
    PLAN -->|"blocking question or invalid plan"| STOP["Stop: comment, remove label<br/>edit issue and re-add label to retry"]
    PLAN -->|"several change sets"| CHILD["One child issue per change set (plan:parent)<br/>first gets proceed-with-change, rest waiting-on-plan"]
    CHILD -->|"on success: close, start next sibling<br/>whose dependencies are closed"| ISSUE
    PLAN -->|"one change set"| RUN["Build Run (diagram 3)"]
```

## 3. Build Run: code, deploy dark, test

One Build Run per app at a time (`concurrency: build-run-<app>`).

```mermaid
flowchart TD
    CODE["Coder commits locally<br/>behind a flag in flags.json"] --> PRE["Pre-push reviewer reads the local commit"]
    PRE -->|"blocked: nothing pushed"| CODE
    PRE -->|"clean"| PUSH["Orchestrator pushes with the PAT"]
    PUSH --> CI["App CI: Test Gate, then deploy<br/>deploys DARK (flag off)"]
    CI --> TEST["Tester runs checks on the deployed app<br/>tags: new / existing"]
    TEST -->|"failed checks, rounds left"| CODE
    TEST -->|"all pass"| GATE["Release gate (diagram 4)"]
    TEST -->|"behaviour that was live broke"| RB["rollback-fly.yml<br/>redeploy previous SHA image"]
    TEST -->|"rounds used up"| FAIL["Run ends failed (diagram 5)"]
```

## 4. Release and watchdog

```mermaid
flowchart TD
    GATE{"Release gate: CI green, deploy healthy,<br/>tester passed, reviewer clean,<br/>same SHA reviewed and pushed"}
    GATE -->|"no"| DARK["Stays dark behind its flag"]
    GATE -->|"yes"| REL["Release: flag on in GrowthBook"]
    REL --> WD["Watchdog for watchdog_minutes<br/>health checks + error count"]
    WD -->|"healthy"| OK["Run ends: released"]
    WD -->|"health fails or errors rise"| OFF["Flag turned off automatically<br/>needs-human issue; release never re-enables it"]
    MAN["flag-set.yml (manual)"] -.-> REL
```

## 5. Record, learn, retry

```mermaid
flowchart TD
    END["Run ends (any outcome)"] --> FIN["finalize + retrospective Agent<br/>summary once on the story, lessons, improvements"]
    FIN --> REC["Writes: App State issue (app repo),<br/>story comments and labels, registry issue, scoreboard"]
    FIN -->|"run did not end well"| ROUTE{"fixrequest.py<br/>routes by the cause named"}
    ROUTE -->|"app cause, attempts left<br/>(spec_ambiguity, model_limit, regression)"| RETRY["Comment on the SAME story,<br/>PAT re-adds proceed-with-change, same flag"]
    ROUTE -->|"app cause, attempts used up"| NH["Stays dark: needs-human + dark-broken"]
    NH -->|"owner adds approve-retire"| RET["Retirement Intake removes the feature"]
    ROUTE -->|"factory cause<br/>(prompt, template, orchestrator, plan gap)"| FF["ai-factory issue: factory-fix-request"]
    FF -->|"owner adds ready-for-factory-run"| FR["Factory Run: retrospective Agent<br/>as isolated user proposes a learning PR"]
    FR --> PR["Learning PR: auto-merge only for additive<br/>lint, format, template defaults; else a human"]
    PR -->|"reaches apps via"| TSN["Template sync (diagram 1)"]
    ROUTE -->|"no cause or infrastructure"| INFO["ai-factory fix-request issue for a person"]
```
