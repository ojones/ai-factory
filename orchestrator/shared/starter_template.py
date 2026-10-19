# The Starter Template files an Agent may not change, and the ones the Orchestrator copies in itself.

# Starter Template files the coder must not change: the workflows hold the Fly
# token, and the flag wrapper is the release gate's other half.
PROTECTED = (".github/", "fly.toml", "fly/", "backend/src/feature-flags.ts", "INTAKE.md", "eslint.config.mjs", "scripts/check-flags.mjs", ".prettierrc.json", ".prettierignore")


# Protected files a template-sync Build Run copies from the Starter Template itself, before any Agent runs (an Agent may not edit
# them, and no Agent is involved). Only files that are safe to overwrite belong here: nobody but the template ever changes them.
TEMPLATE_FILES_APPLIED_BY_ORCHESTRATOR = (".github/dependabot.yml", ".github/workflows/test-gate.yml", ".github/workflows/rollback-fly.yml",
                                            ".github/workflows/deploy-fly.yml")


# The Starter's lint and formatter config is owned by the Orchestrator too, so the coder cannot loosen a rule to make a check pass. A tighter rule
# can fail the app's existing code, so these are committed locally and pushed together with the coder's fixes (a push of the config alone would
# put a red Test Gate on `main`); the coder, and only the coder, fixes what the new rules report.
TEMPLATE_FILES_HELD = ("eslint.config.mjs", "scripts/check-flags.mjs", ".prettierrc.json", ".prettierignore")


TEMPLATE_FILES_OWNED_BY_ORCHESTRATOR = TEMPLATE_FILES_APPLIED_BY_ORCHESTRATOR + TEMPLATE_FILES_HELD


def protected_violations(changed_files):
    return [f for f in changed_files if f.startswith(PROTECTED) or f in PROTECTED]
