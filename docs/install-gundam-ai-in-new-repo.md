# Install Gundam AI in new repo

This guide is for a Claude Code session working in a different repo (for example the AI factory repo) that should send its Claude Code usage to the local telemetry stack in the gundam-ai checkout.

The telemetry records workflow metadata only: event names, tool names, outcomes, failure classes, skill names, prompt length buckets. It never records prompt text, code, file names, commands or tool output. Everything stays on this Mac: hooks write to a local spool, an uploader sends to a fake server on `localhost:8080`, and a dashboard on `127.0.0.1:8081` shows totals. Nothing leaves the machine.

The gundam-ai checkout is at `/Users/oz/Documents/git/gundam-ai`. Nothing needs to be copied into the target repo or installed with pip. The hooks run from that checkout using an absolute `PYTHONPATH`.

## Rules for the session doing this

- Do not edit anything in the gundam-ai checkout. Only edit settings files.
- If a settings edit is blocked or needs approval, ask the user to make the edit or approve it. Do not work around it.
- Merge into existing settings. Never replace a user's existing hooks, permissions or `statusLine`.
- Do not copy hook input, prompts or tool output anywhere while testing.

## Step 1: Check the requirements

```sh
python3 --version
test -d /Users/oz/Documents/git/gundam-ai/telemetry && echo found
```

Python must be 3.10 or newer. The second command must print `found`.

## Step 2: Start the local stack (once per login)

Run from the gundam-ai checkout:

```sh
cd /Users/oz/Documents/git/gundam-ai
make token
make up
```

`make token` creates the shared credential in the macOS Keychain; it is safe to run again. `make up` starts the fake ingest server, the dashboard and the uploader in the background. It prints `dashboard: http://127.0.0.1:8081/`. `make down` stops them. Logs are in `/tmp/claude-telemetry/`.

If the stack is not running, nothing breaks in Claude Code. Events wait in the local spool and upload when `make up` is run later.

## Step 3: Generate the hooks block

```sh
cd /Users/oz/Documents/git/gundam-ai
python3 -c "
import json
from telemetry.managed_settings import managed_settings
print(json.dumps(managed_settings('PYTHONPATH=$PWD python3 -m telemetry.hook'), indent=2))"
```

The output is a JSON object with a `hooks` key. Every entry is an async command hook, so a Claude session never waits for telemetry and the hook cannot approve, deny or change anything.

## Step 4: Add the hooks to settings

Choose where, and ask the user if it is not clear:

- **All repos on this Mac:** `~/.claude/settings.json`.
- **Only the target repo:** `.claude/settings.json` in that repo.

Merge the `hooks` entries from step 3 into the chosen file:

- If the file has no `hooks` key, add the whole block.
- If it already has hooks for the same event (for example `PostToolUse`), append the telemetry command to that event's existing `hooks` list. Do not replace the existing entries.
- Keep the command string exactly as generated, including `PYTHONPATH=/Users/oz/Documents/git/gundam-ai python3 -m telemetry.hook` and `"async": true`.

Do not put `async` on anything else and do not add decision fields to these hooks.

## Step 5: Optional settings

Set these in the `env` key of the settings file, or in the shell that starts Claude Code:

| Variable | Meaning |
|---|---|
| `TELEMETRY_REPO_ID` | A short name for this repo (for example `ai-factory`), so the dashboard can tell repos apart. Without it the field is null. |
| `TELEMETRY_USER_ID`, `TELEMETRY_TEAM_ID` | Pseudonymous keys. Leave unset for a single-user local setup. Never derive them from a username or path. |

Example:

```json
{
  "env": { "TELEMETRY_REPO_ID": "ai-factory" }
}
```

## Step 6: Optional context-size reminders

These remind the developer to hand off a long session. They are separate from the telemetry: no events, no network. Add them only if the user wants them. Both entries go in the same settings file as step 4.

Hooks (append to the existing `UserPromptSubmit` and `Stop` lists):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "matcher": "*", "hooks": [
        { "type": "command", "command": "PYTHONPATH=/Users/oz/Documents/git/gundam-ai python3 -m telemetry.context_nudge deliver" }
      ] }
    ],
    "Stop": [
      { "matcher": "*", "hooks": [
        { "type": "command", "command": "PYTHONPATH=/Users/oz/Documents/git/gundam-ai python3 -m telemetry.context_nudge record", "async": true }
      ] }
    ]
  }
}
```

The `deliver` command is deliberately not async: it must return text to Claude. It only checks for a small pending file, so it adds no noticeable delay.

Status line (only if the user has no `statusLine` of their own; a project `statusLine` replaces a personal one):

```json
{
  "statusLine": {
    "type": "command",
    "command": "PYTHONPATH=/Users/oz/Documents/git/gundam-ai python3 -m telemetry.statusline"
  }
}
```

If the user already has a status line script, call `python3 -m telemetry.statusline` from it instead of replacing it. It reads the status line JSON on stdin and prints one segment.

## Step 7: Start a new session and check that it works

Hooks are read at session start, so the user must start a new Claude Code session in the target repo. Then:

1. In that session, run `/hooks` and confirm the telemetry command is listed for the events.
2. Test the hook by hand. It must print nothing and exit 0:

   ```sh
   echo '{"hook_event_name":"Stop","session_id":"test"}' | PYTHONPATH=/Users/oz/Documents/git/gundam-ai python3 -m telemetry.hook; echo $?
   ```

3. After a few prompts, check the queue and the loss counters:

   ```sh
   cd /Users/oz/Documents/git/gundam-ai
   make health
   make aggregate
   ```

   `make health` shows queue depth and the last upload time. `make aggregate` shows what the fake server has received.
4. Open http://127.0.0.1:8081/ for the dashboard. Allow about 30 seconds for the uploader.

Empty results after a session mean the hooks are not registered or the command path is wrong.

## Skill names

The dashboard's Skills section lists every skill name, whether Claude invoked it or the user typed `/name`. Built-in commands and private skill names are recorded too. Skill arguments and the rest of the prompt are never recorded.

## Turn it off or remove it

- Stop collecting: remove the telemetry hook entries from the settings file and start a new session.
- Stop the local stack: `make down` in the gundam-ai checkout.
- Delete what is stored on this Mac: remove `~/Library/Application Support/claude-telemetry` (the spool) and `~/Library/Application Support/claude-telemetry-ingest` (the fake server's store).

## More detail

In the gundam-ai checkout: `README.md` (usage), `docs/privacy.md` (what is collected), `docs/decisions.md` (design decisions) and `local-architecture.md` (diagrams).
