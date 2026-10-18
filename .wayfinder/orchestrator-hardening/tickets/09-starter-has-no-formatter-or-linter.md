---
title: The Starter Template has no formatter or linter
type: task
status: resolved
assignee:
blocked_by: []
---

## Question

STANDARDS-CODING.md says style is "purely mechanical — an auto-formatter is the entire style guide", but `templates/starter/` ships no formatter or linter (no Prettier or ESLint config, no `lint` or `format` script, nothing in `npm run check` beyond `tsc`). Agents are therefore the style guide after all, and the learning loop has nothing to tighten when a recurring finding is a style or quality one. Decide what the Starter Template ships (formatter only, or also lint rules), which rules, how `check` and the Test Gate use it, whether the coder runs the formatter before committing, and how already-seeded apps get it (template sync).

## Added context

- Found while building the learning loop: its auto-merge policy is limited to additive changes to lint and formatter config in the Starter Template, which only works once such config exists. Without it every such lesson ends in a human-merged change that adds the tooling first.
- A formatter that rewrites whole files would produce a large first diff in every app; decide whether the Test Gate checks formatting or only the coder's own run does.
- Constraint: free tooling, and nothing that slows the coder's per-round checks (`npm run check` is meant to be fast).

## Resolution

Starter ships Prettier and ESLint (typescript-eslint recommended). `npm run check` is now tsc plus `npm run lint` (about 2.4s); `format:check` exists but is not a gate, so no old file fails for layout. The coder prompt and AGENTS.md tell it to run `npm run format` before committing. Config is additive-only so the learning loop can auto-merge tightened rules (INV-15). Already-seeded apps get it only through a template-sync Update Intake (not yet built).
