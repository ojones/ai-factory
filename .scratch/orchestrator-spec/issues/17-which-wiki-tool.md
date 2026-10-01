Type: research
Status: resolved
Note: out of this map's destination — tracked for reference, not part of the Orchestrator spec deliverable. See [map.md](../map.md).

## Question

Separate from Built Application deployment, the Factory's owner wants a low-cost way to view and edit context for projects and the Factory's own Standards/architecture docs — markdown-based, with mermaid.js diagram support, usable as a wiki-like reference. Compare self-hosted open-source options (e.g. Wiki.js, BookStack, Outline, Gollum, a docs-as-code static site like MkDocs Material or Docusaurus hosted free on GitHub Pages, or GitHub's built-in per-repo Wiki) against paying for a SaaS tool like Atlassian Confluence, on: cost, maintenance burden, markdown+Mermaid fidelity, and ease of editing for both humans and Agents. Also note whether a broader "internal developer portal" tool (e.g. Backstage) would meaningfully centralize this with the deployment/IaC tooling.

Recommend one, with the runner-up and why it lost.

## Answer

**Wiki.js**, run in its git storage/sync mode (every page save auto-commits as a real `.md` file to a git repo). Free (AGPL-3.0, no paid tier), native built-in Mermaid support, a genuine browser WYSIWYG editor for a human, and content stays plain markdown in git that an Agent can also read/write directly or via Wiki.js's GraphQL API. Cheap to run (a $5–6/mo VPS or a free-tier container is enough at solo scale).

Runner-up: **MkDocs Material on GitHub Pages** — $0 hosting, the best Mermaid fidelity of anything evaluated, maximally Agent-friendly (pure git/PR-based) — loses the primary slot only because it has no live in-browser WYSIWYG editing, which was a stated requirement.

Also ruled out: BookStack (Mermaid support is a fragile CDN-dependent community hack, not native — disqualifying given Mermaid was a hard requirement); Outline (excellent editing/Mermaid fidelity, but heavier self-host footprint — Postgres + Redis + S3 — and a non-OSI BUSL license, though self-hosting for own use is unrestricted); Backstage (TechDocs' Mermaid support is a flaky plugin, not native, and running it for real needs Postgres + realistically Kubernetes — not worth the ops overhead for a solo operator; same logic rules out paying for Confluence, since Wiki.js is "just as good" at zero license cost).

Full findings with citations: see branch `research/wiki-tooling`, file `.scratch/orchestrator-spec/research/wiki-tooling.md` (commit 034285c).
