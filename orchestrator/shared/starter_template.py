PROTECTED = (".github/", "fly.toml", "fly/", "docker-entrypoint.sh", "backend/src/feature-flags.ts", "INTAKE.md", "eslint.config.mjs", "scripts/check-flags.mjs", ".prettierrc.json", ".prettierignore")


TEMPLATE_FILES_APPLIED_BY_ORCHESTRATOR = (".github/dependabot.yml", ".github/workflows/test-gate.yml", ".github/workflows/rollback-fly.yml",
                                            ".github/workflows/deploy-fly.yml")


TEMPLATE_FILES_HELD = ("eslint.config.mjs", "scripts/check-flags.mjs", ".prettierrc.json", ".prettierignore")


TEMPLATE_FILES_OWNED_BY_ORCHESTRATOR = TEMPLATE_FILES_APPLIED_BY_ORCHESTRATOR + TEMPLATE_FILES_HELD


def protected_violations(changed_files):
    return [f for f in changed_files if f.startswith(PROTECTED) or f in PROTECTED]
