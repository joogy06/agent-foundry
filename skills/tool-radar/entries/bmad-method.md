```radar
name: BMAD-METHOD
slug: bmad-method
category: dev-methodology
alternative_to: forge + bob + agent-teams (agile, role-based AI development workflow)
homepage: https://github.com/bmad-code-org/BMAD-METHOD
repo: https://github.com/bmad-code-org/BMAD-METHOD
licence_code: MIT
licence_other: n/a ("BMad" and "BMAD-METHOD" are trademarks of BMad Code, LLC)
cost: free; optional donations and corporate sponsorship
maturity: v6.12.4 stable (2026-10-14); v7 alpha preview on main
mcp: unknown
ring: assess
reviewed: 2026-10-29
review_by: 2027-01-27
suggested_by: owner (2026-10-29)
related_skills: [forge, agent-teams, adversarial-team-brainstorm, development-lifecycle, research-for-skills]
tags: [bmad, agile, ai-driven-development, methodology, multi-agent, prd, architecture, stories, skills, claude-code, codex]
verdict: Popular MIT agile multi-agent method (54.7k stars). Overlaps forge/bob; worth mining for ideas, not adopting beside forge.
origin: owner request 2026-10-29 (tool-radar intake)
```

## What it is

"Breakthrough Method for Agile AI Driven Development": a set of role-based agents (current docs, which may describe v7: Analyst, PM, Product Owner, Architect, Developer, UX Designer; no standalone QA agent), structured workflows and multi-agent discussions that take work through clarify, plan, build-and-verify and learn. Small changes go straight to build; larger work gets more planning. It installs into a coding agent as skills.

## Verified facts

- VERIFIED: MIT licence; "BMad" and "BMAD-METHOD" are trademarks of BMad Code, LLC (TRADEMARK.md). Source: https://github.com/bmad-code-org/BMAD-METHOD (read 2026-10-29).
- VERIFIED: latest stable tag v6.12.4, dated 2026-10-14; v6.12.0 was 2026-09-04. Source: https://github.com/bmad-code-org/BMAD-METHOD/tags (read 2026-10-29).
- VERIFIED: v7 is an alpha preview on the main branch; the README gave a v7 ETA of 2026-10-16, which had passed with no v7 tag by 2026-10-29. Source: https://github.com/bmad-code-org/BMAD-METHOD (read 2026-10-29).
- VERIFIED: install: stable `npx bmad-method install` (Node.js 20.12+, Python 3.10+); v7 preview via `npx skills add bmad-code-org/BMAD-METHOD --skill '*'` or the Claude Code and Codex plugin marketplaces; both need `uv`. Source: https://github.com/bmad-code-org/BMAD-METHOD (read 2026-10-29).
- VERIFIED: names Claude Code and Codex as hosts; v7 needs "an AI coding tool that supports skills". Source: same (read 2026-10-29).
- VERIFIED: "free and open source, with no paywalled workflows". About 54.7k stars, 6.1k forks. Source: same (read 2026-10-29).
- UNCERTAIN: no MCP server or client is mentioned; recorded as unknown, not none.
- VERIFIED (local, read-only): not installed on the foundry host (no `bmad-method` on PATH, no BMAD plugin found). Source: local read-only check (2026-10-29).

## Claims that are false or overstated

- The v7 ETA (2026-10-16) has slipped; do not plan on v7 being stable.
- "Breakthrough" is branding; the method is a structured agile workflow, comparable in kind to foundry's own.

## Foundry fit

Honest comparison with forge (and bob, agent-teams):

| | BMAD-METHOD | foundry forge + bob |
|---|---|---|
| Shape | planning personas (analyst, PM, architect, UX) map to forge; `bmad-build` ("turns a work item into reviewed, verified code") and `bmad-build-auto` (unattended loop) map to bob | forge designs (design team, challengers, cross-provider review), bob executes approved designs through agent-teams |
| Cross-provider review | same host by default; review lenses can optionally "run on another model"; no provider-diversity rule, budgeted seats or named cross-vendor challenger | built in: Codex and agy seats, provider-diversity rule, budgeted seats |
| Gates and evidence | `bmad-code-review`: several independent lenses, triage into patch / defer / decision-needed, every dismissal "with a recorded reason, never silently", human sign-off; `bmad-retrospective`; optional TEA test-architect module. No signed contract map, ledger or independent verification arbiter | signed contract maps, ledger, gates (`_meta/gates.py`), verification arbiter |
| Scaling by size | small changes skip planning | routing by complexity (TRIVIAL to COMPLEX) |
| Portability | Claude Code, Codex, any skills-capable tool | Claude Code primary; skills mirrored to Codex, agy, Copilot |
| Community | large (54.7k stars), many modules | private, one owner |

- Where BMAD is stronger: product-side artefacts (PRD, UX, story sharding), a disciplined multi-lens review with recorded dismissals, a large community and modules, and a lighter footprint for a project without foundry's machinery.
- Where forge is stronger: adversarial cross-provider review, evidence gates and the ledger, and integration with the rest of the harness.
- Conflicts: installing it beside forge gives two competing routers for the same requests (the global rules route every task through forge), its `npx skills add` may write into the skills tree that `install.py` manages (inferred, not documented), which is the installer-reproducibility problem the repo already fights, and it ships a skill named `bmad-forge-idea`, a name close to forge.

## Decision and next step

Assess. Do not install beside forge. Trigger for trial: the owner wants product-side artefacts forge lacks; then run the BMAD PRD, UX and review skills on a throwaway project in a throwaway home (never the live one) and harvest templates and the dismissal-recording pattern into forge or `audience-experience-design`. Review trigger: v7 shipping stable.

## Sources

- https://github.com/bmad-code-org/BMAD-METHOD (read 2026-10-29)
- https://github.com/bmad-code-org/BMAD-METHOD/tags (read 2026-10-29)
- https://docs.bmad-method.org/build/review-a-change/ (read 2026-10-29)
- https://docs.bmad-method.org/reference/skills-and-agents/ (read 2026-10-29)
