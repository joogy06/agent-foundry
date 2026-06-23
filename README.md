# Claude Code Skills & Agents

A curated collection of skills and agents for [Claude Code CLI](https://claude.ai/code), covering software engineering, DevOps, data engineering, infrastructure administration, and workflow orchestration.

> **Version:** 1.2.0 · **Last published:** 2026-06-23 · **183 skills · 5 agents · 9 workflows · 2 commands**
> See the [Changelog](#changelog) for what changed in each release.

---

## What's Inside

- **183 skills** — domain knowledge Claude loads on demand to help with specific tasks. Highlights include the **legacy-comprehension family** (`lineage-extract-static`, `mainframe-lineage-parsers`, `legacy-code-intel`, `structure-recovery`, `intent-extract` — data/process lineage, deterministic COBOL/JCL/DB2 + Control-M → OpenLineage, SCIP-style symbol graphs, and record-structure recovery for legacy estates), `env-readiness` (read-only environment readiness doctor), `publish-to-github` (releasing this whole tree to public github safely), `visual-companion` (browser-based mockup/diagram review during design), and `cross-project-mail` (AI-agent messaging across sibling projects on one host)
- **5 agents** — specialized sub-agents for execution, review/evolution, evergreening, task routing, and knowledge management
- **9 saved workflows** — committed `.js` orchestration scripts under `~/.claude/workflows/` (e.g. `bob-serial-exec`, `design-tournament`, `alf-sweep`) that parameterize the existing agents; main-loop-only on Claude Code, with a host-neutral serial fallback for every other host
- **Slash commands** — short user-invoked workflows under `~/.claude/commands/` (e.g. `/exit-with-docs` to wrap up a session and update project docs)

Skills are auto-discovered by Claude Code from frontmatter descriptions — you don't call them explicitly. Agents are invoked by name (`forge`, `bob`, `alf`, `pa`, `wiki`). Commands are invoked with a leading slash (e.g. `/exit-with-docs`).

---

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/<your-username>/<repo-name>.git
cd <repo-name>

# 2. Bootstrap a full environment (recommended for first-time setup)
python3 bootstrap-environment.py
# or, on Windows:  pwsh -NoProfile -NonInteractive -File bootstrap-environment.ps1
```

The bootstrap orchestrator runs `install.py` plus 9 idempotent post-install steps so a fresh machine reaches a complete Claude Code environment in one command. Re-run any time — every step skips work already done.

| Step | What happens |
|---|---|
| 1 | `install.py` places skills / agents / commands under `~/.claude/` |
| 2 | Places `~/.claude/CLAUDE.md` (global instructions) |
| 3 | Symlinks `~/.claude/AGENTS.md → CLAUDE.md` (GitHub Copilot bridge) |
| 4 | Mirrors `pa-server/` into `~/.claude/pa-server/` (MCP server for the `pa` agent) |
| 5 | Merges canonical `SessionStart` hooks into `~/.claude/settings.json` (preserves any you already have; backs the old file up to `.bak`) |
| 6 | Writes `~/.claude/policy-limits.json` with conservative defaults, mode `0600` |
| 7 | Symlinks `~/.claude/bin/claude-observe` for the process-observation skill |
| 8 | Mirrors skills into `~/.codex/skills/*` (only if `codex` CLI is on PATH) |
| 9 | Pins Gemini model to `gemini-3.1-pro-preview` in `~/.gemini/settings.json` (only if file exists) |
| 10 | Prints next-step guidance |

After bootstrap, two more steps inside Claude Code finish the setup:

```
# Inside Claude Code:
/setup                                               # interactive permissions upgrade
                                                      # (conservative -> autonomous)
```

```bash
# Per working repo you care about:
bash scripts/install-pre-push-hook.sh /path/to/repo            # POSIX
# or any OS (incl. enterprise Windows where PowerShell is blocked):
python3 scripts/install-pre-push-hook.py --target-repo /path/to/repo
```

The pre-push hook runs a secrets scanner (live API keys, PEM private keys, AWS credentials, JWTs, inline tokens, etc.) before every `git push`. Critical/high findings block the push; medium/low advisory hits print but don't block. Override per-push with `git push --no-verify`.

### Bootstrap flags

```bash
python3 bootstrap-environment.py --dry-run        # preview without writing
python3 bootstrap-environment.py --force          # overwrite existing CLAUDE.md / pa-server / policy-limits
python3 bootstrap-environment.py --skip-install   # don't run install.py
python3 bootstrap-environment.py --skip-codex     # don't touch ~/.codex/
python3 bootstrap-environment.py --skip-gemini    # don't touch ~/.gemini/settings.json
python3 bootstrap-environment.py --claude-home /opt/claude   # custom config root
python3 bootstrap-environment.py --help
```

### Minimal install (skills + agents + commands only)

If you already have a CLAUDE.md, hooks, and other host config and just want the skill content placed:

```bash
python3 install.py                                       # interactive
python3 install.py --noninteractive                      # Claude + link
python3 install.py --target claude,gemini --mode link
python3 install.py --target all --mode move --force      # full copy, overwrite
python3 install.py --claude-home /opt/claude             # custom path
python3 install.py --help                                # all flags
```

`install.py` is what `bootstrap-environment.py` calls under the hood for step 1, so the flags are pass-through-able via `--install-arg`.

### Windows enterprise notes

- `bootstrap-environment.ps1` is enterprise-hardened — `#Requires -Version 5.1`, `[CmdletBinding()]` with named switch parameters, **no** `-ExecutionPolicy Bypass`, no dot-source, no `-Command`. Invoke with `pwsh -NoProfile -NonInteractive -File bootstrap-environment.ps1`.
- The bootstrap script probes `py` (PEP-397 launcher) → `python3` → `python` in that order and runs the orchestrator with whichever resolves first.
- For backward compatibility, the older `install.cmd` / `install.ps1` entry points are still present. They use `-ExecutionPolicy Bypass` for compatibility with very locked-down machines; prefer `bootstrap-environment.ps1` on modern setups.
- Symbolic links on Windows require **admin** or **Developer Mode**. If symlinks fail, the bootstrap falls back to copy and prints a warning (drift risk if you later edit `CLAUDE.md` — the `AGENTS.md` copy won't update).

### Manual install (alternative)

If you'd rather not run a script:

```bash
cp -r skills/* ~/.claude/skills/
cp -r agents/*.md ~/.claude/agents/
cp -r commands/*.md ~/.claude/commands/
cp CLAUDE.md ~/.claude/CLAUDE.md
ln -s ~/.claude/CLAUDE.md ~/.claude/AGENTS.md
cp -r pa-server ~/.claude/pa-server
```

You'll then need to add the `SessionStart` hooks to `~/.claude/settings.json` by hand — see the bootstrap script's source for the canonical entries. For the full multi-model experience with Codex and Gemini as second-opinion models, see [Dependencies](docs/dependencies/README.md).

---

## What You Need

| Tier | What it gives you | What to install |
|------|-------------------|-----------------|
| **Minimal** | All 150+ domain skills work as Claude reference material. `wiki` agent works fully. | Claude Code CLI only |
| **Standard** | + `forge` / `bob` / `alf` agents with multi-model reviews (Codex + Gemini) | Add Codex CLI + Codex plugin + Gemini CLI MCP |
| **Full** | + `pa` agent with persistent task tracking, browser-based product reviews | Add pa-server MCP (custom) + claude-in-chrome MCP |

See **[docs/dependencies/](docs/dependencies/README.md)** for complete install instructions.

---

## The Agents

| Agent | Purpose | Run standalone? |
|-------|---------|-----------------|
| **forge** | Design exploration with multi-model challengers (Claude + Codex + Gemini). Produces approved design docs. | Yes |
| **bob** | Autonomous implementation executor. Reads approved design docs, decomposes into work packages, delegates to team-based orchestration, verifies output. | Yes (needs a design doc) |
| **alf** | Evolution & improvement reviewer. Audits skills/agents/code/products for staleness, drift, capability gaps, security, performance. Produces evidence-cited reports. | Yes |
| **pa** | Task router and persistent workspace manager. Classifies intent, routes to specialist agents, tracks state across sessions. | Yes (stateless mode without pa-server MCP) |
| **wiki** | Knowledge base builder. Ingests sources into cited, interlinked markdown wiki pages. Compile-once, read-cheaply model. | Yes (no external dependencies) |

Architecture: `pa` routes → `forge` designs → `bob` implements → `alf` reviews → all can query `wiki`. See [Agent Graph](docs/dependencies/agent-graph.md) for the full interaction diagram.

---

## Skill Categories

<details>
<summary><b>Orchestration & Meta</b> (click to expand)</summary>

`forge` · `agent-teams` · `team-manager` · `challenger` · `qa-reviewer` · `ux-reviewer` · `research-for-skills` · `codex-orchestration` · `web-research` · `development-lifecycle` · `project-documentation` · `simplify` · `publish-to-github` · `visual-companion` · `env-adoption` · `env-readiness` · `smart-config` · `knowledge-grounding`

Build and manage agent teams, run multi-model reviews, decompose work.
</details>

<details>
<summary><b>Knowledge Management</b></summary>

`wiki` · `obsidian` · `large-file-analysis` · `confluence-documentation` · `confluence-content-creator` · `confluence-rest-api` · `research-vectorization`

Persistent knowledge bases, large document analysis, Confluence integration, vector search.
</details>

<details>
<summary><b>Python Development</b></summary>

`python-flask-developer` · `python-auth-security` · `python-parallelism` · `python-data-engineer` · `python-enterprise-connectors`

Flask, auth/OAuth/OIDC, asyncio/multiprocessing, SQLAlchemy, enterprise database connectors.
</details>

<details>
<summary><b>JavaScript / Frontend</b></summary>

`content-writer` · plus JS/TS patterns from upstream plugins

Frontend design, content creation, modern web frameworks.
</details>

<details>
<summary><b>Java Enterprise</b></summary>

`java-backend` · `java-frontend`

Spring Boot, Spring Security, Spring Data JPA, Angular 17+, React 18+, NgRx/Redux.
</details>

<details>
<summary><b>Docker</b></summary>

`docker-fundamentals` · `docker-networking` · `docker-storage` · `docker-security` · `docker-cicd` · `docker-compose-patterns` · `docker-admin`

Container lifecycle, networking, volumes, security hardening, CI/CD, multi-stage builds.
</details>

<details>
<summary><b>Linux — RHEL 9 / AlmaLinux / Rocky</b></summary>

`rhel-server-admin` · `rhel-web-servers` · `rhel-databases` · `rhel-docker-host` · `rhel-file-storage` · `rhel-network-infra` · `rhel-monitoring` · `rhel-ollama-nvidia`

Full RHEL 9 administration stack including NVIDIA/CUDA/Ollama for AI workloads.
</details>

<details>
<summary><b>Linux — Ubuntu 24.04 LTS</b></summary>

`ubuntu-server-admin` · `ubuntu-web-servers` · `ubuntu-databases` · `ubuntu-docker-host` · `ubuntu-file-storage` · `ubuntu-network-infra` · `ubuntu-monitoring` · `ubuntu-ollama-nvidia`

Full Ubuntu 24.04 administration stack, parallel to the RHEL set.
</details>

<details>
<summary><b>Linux — Auth & Identity</b></summary>

`linux-centrify`

Centrify/Delinea Server Suite, Active Directory integration, PAM/NSS.
</details>

<details>
<summary><b>Windows Server</b></summary>

`windows-powershell` · `windows-cmd` · `windows-ps-server-admin` · `windows-ps-security` · `windows-ad-admin` · `windows-sso`

PowerShell 7.x + 5.1, batch scripting, AD administration, security hardening, SSO (AD FS, Azure AD, SAML/OAuth/OIDC).
</details>

<details>
<summary><b>Databases</b></summary>

`mongodb` · `db2-rhel` · `db2-mainframe`

MongoDB (replica sets, sharding), DB2 LUW on RHEL, DB2 for z/OS mainframe.
</details>

<details>
<summary><b>IBM Mainframe & Middleware</b></summary>

`ibm-mainframe` · `cobol-developer` · `db2-mainframe` · `ibm-mq` · `ibm-websphere` · `cognos-admin` · `cognos-user` · `datastage-developer` · `pega-robotics` · `control-m` · `pick-developer` · `lineage-extract-static` · `mainframe-lineage-parsers` · `legacy-code-intel` · `structure-recovery` · `intent-extract` · `intent-map-render`

z/OS, JCL, COBOL, DB2 z/OS, IBM MQ, WebSphere, Cognos Analytics, DataStage, Pega RPA, Control-M workload automation, Pick/MultiValue BASIC. The **legacy-comprehension family** extracts data/process lineage (LLM-as-parser + a deterministic COBOL/JCL/DB2 + Control-M → OpenLineage 2.0.2 engine with multi-abstraction views), SCIP-style symbol graphs, record-structure/DDL recovery, and per-component functional intent from legacy estates.
</details>

<details>
<summary><b>Data Engineering</b></summary>

`data-lake` · `data-warehouse` · `data-mart` · `datastage-developer` · `market-data-engineering` · `research-vectorization`

Lakes (Parquet/Iceberg/Delta), warehouses (Kimball/Inmon), marts (star/snowflake), ETL with DataStage, financial data pipelines.
</details>

<details>
<summary><b>SaaS Architecture</b></summary>

`saas-architecture` · `saas-developer`

Multi-tenant patterns, subscription billing, onboarding flows, tenant isolation, feature flags.
</details>

<details>
<summary><b>Trading & Finance</b></summary>

`trading-strategy-backtester` · `trading-risk-management` · `crypto-exchange-integration` · `day-trading-patterns` · `financial-sentiment-analysis` · `geopolitical-market-impact` · `social-trading-signals` · `market-data-engineering` · `trader-psychology-analysis`

Backtesting with vectorbt/backtrader, kill switches, CCXT, intraday patterns, FinBERT sentiment, event-driven signals.
</details>

<details>
<summary><b>SEO & Marketing</b></summary>

`seo-content-strategist` · `seo-keyword-strategist` · `seo-structure-architect` · `seo-meta-optimizer` · `seo-serp-optimizer` · `seo-authority-builder` · `seo-data-analyst` · `ai-search-optimizer` · `conversion-psychology` · `ecommerce-growth`

Full SEO stack including AI search optimization (ChatGPT/Gemini/Perplexity citations), schema markup, topic clusters, GSC/GA4 analytics.
</details>

<details>
<summary><b>WordPress & WooCommerce</b></summary>

`wordpress-developer` · `wordpress-admin` · `woocommerce-developer` · `hostinger-hosting`

Theme/plugin development, block editor, WooCommerce checkout, hosting-specific patterns.
</details>

<details>
<summary><b>Career Development</b></summary>

`career-coach` · `career-assessment` · `career-planning` · `career-positioning` · `career-leadership` · `career-storytelling` · `career-transition`

Career strategy, self-assessment, interview prep, promotion cases, leadership development.
</details>

<details>
<summary><b>Presentations</b></summary>

`presentation-builder` · `presentation-narrative` · `presentation-datavis` · `presentation-diagrams` · `presentation-styling` · `presentation-renderer`

Orchestrated presentation creation — narrative frameworks, charts, diagrams, styling, PPTX/HTML export.
</details>

<details>
<summary><b>Project & Delivery Management</b></summary>

`project-manager` · `delivery-manager` · `project-finance` · `jira-rest-api`

WBS, critical path, EVM, Agile ceremonies, flow metrics, Jira integration.
</details>

<details>
<summary><b>DevOps & CI/CD</b></summary>

`jenkins` · `ansible` · `docker-cicd` · `gcp-workstations`

Pipeline development, infrastructure as code, CI/CD Docker builds, cloud dev environments.
</details>

<details>
<summary><b>Observability</b></summary>

`splunk-developer` · `rhel-monitoring` · `ubuntu-monitoring`

SPL queries, dashboards, Prometheus/Grafana/Loki, ELK stack, alerting.
</details>

<details>
<summary><b>CLI Tools & Integrations</b></summary>

`claude-code-cli` · `gemini-cli` · `gh-copilot-cli` · `codex-orchestration` · `mcp-server-creator`

Claude Code CLI reference, Gemini CLI, GitHub Copilot CLI, Codex delegation, building MCP servers.
</details>

<details>
<summary><b>Image Generation</b></summary>

`nano-banana` · `vertex-banana`

Image generation via Gemini API (primary) and Vertex AI (fallback).
</details>

<details>
<summary><b>Performance</b></summary>

`performance`

Profiling, load testing, query optimization, bottleneck analysis.
</details>

---

## Documentation

- **[docs/dependencies/README.md](docs/dependencies/README.md)** — install tiers, component matrix, quick start
- **[docs/dependencies/local-tools.md](docs/dependencies/local-tools.md)** — Claude Code CLI, Codex CLI, Gemini CLI, plugins, environment variables
- **[docs/dependencies/mcp-servers.md](docs/dependencies/mcp-servers.md)** — Gemini CLI MCP, claude-in-chrome MCP, pa-server MCP
- **[docs/dependencies/agent-graph.md](docs/dependencies/agent-graph.md)** — how agents interconnect, data contracts, minimal subsets
- **[feedback-loop.md](feedback-loop.md)** — known compatibility issues + reporting template. **Read this first if you're installing on Windows / macOS / WSL / a container / an air-gapped host** — this collection was developed on a single Linux host and your environment may behave differently. Your bug report becomes the next user's starting point.

---

## Design Principles

Skills and agents in this repository follow these principles:

1. **Documentation-first** — Most skills are reference material Claude reads on demand, not executable code
2. **Graceful degradation** — Missing optional dependencies produce gap notes, never hard failures
3. **Evidence before assertions** — Agents (especially `alf`) require sources, tiers, confidence levels for all external claims
4. **Model-agnostic language** — Skills avoid Claude-specific constructs where possible; most work in Codex CLI and Gemini CLI too
5. **No secrets, no tokens** — Skills reference environment variable *names*, never values. The `pa` agent explicitly refuses to store credentials
6. **Standalone-capable** — Every agent can run without the others; the full graph is opt-in

---

## Installation Matrix

| Installing | You get | Time |
|-----------|---------|------|
| Skills only | 150+ domain knowledge modules | <1 min |
| Skills + agents | + forge/bob/alf/wiki/pa orchestration | <2 min |
| + Codex CLI + plugin | + GPT-5.4 challenger reviews | ~10 min (Codex auth) |
| + Gemini CLI + MCP | + Gemini 3 third-model verification, 1M-context analysis | ~10 min (Gemini auth) |
| + claude-in-chrome | + browser-based product reviews for alf | ~15 min (Chrome extension) |
| + pa-server (custom) | + persistent task tracking across sessions | Build your own |

---

## Contributing

<!-- TODO: fill this in when publishing -->
_Contribution guidelines — to be added._

---

## Publishing your own copy

The `publish-to-github` skill in `skills/publish-to-github/` is itself the workflow that produced this repo. It scrubs private content, runs security checks, and produces a clean staging directory. To publish your own modified copy:

1. Customize `skills/` and `agents/` for your needs
2. Create `~/.claude/publish-config.json` (template at `skills/publish-to-github/templates/publish-config.example.json`)
3. Run `python3 ~/.claude/skills/publish-to-github/scripts/publish_prep.py --extended-scan`
4. Inspect the staging dir, then `git init / add / commit / push` from there

See `skills/publish-to-github/SKILL.md` for the full workflow.

---

## Changelog

### 1.2.0 — 2026-06-23
- **Memory + preferences subsystem:** formalizes the two-tier file memory (**global** `~/.claude/memory/`, loaded every session, layered with **per-project** memory) and adds a new **`user-preferences`** skill — durable, cross-project preference profiles (`coding` / `presentations` / `email` / `tone`) the agent loads before domain work and moulds to over time. **Capture is explicit-only** (recorded when you state a preference, never inferred). A `_meta/memory_primer.py` SessionStart hook reports which memory tiers loaded + the live `skills · agents · gates` count, and `bootstrap-environment.py` seeds the memory tier + profiles on a fresh machine (never clobbering a populated profile).

### 1.1.1 — 2026-06-23
- **`publish-to-github` gains `sync-metadata`:** a one-source reconciler that derives this catalog's `**N skills**`/`**M agents**`/`**K workflows**` counts, the Version/Last-published header, and the GitHub repo **About** (description + topics) from the live skill tree — so the published counts and the repo description can no longer silently drift.

### 1.1.0 — 2026-06-23
- **legacy-comprehension family — lineage v1:** `mainframe-lineage-parsers` gains a deterministic **Control-M** Automation-API jobs-as-code extractor (scheduler→program→data, job→job event DAG) alongside the existing COBOL/JCL/DB2 path; new OpenLineage facets (standard `columnLineage 1-2-0`, a `controlmDependencies` job facet, and a `sourceCodeLocation.contentSha256` cross-engine join key). `lineage-extract-static` gains **multi-abstraction views** — L1 file-interaction (job-retained) + L2 table/column — as a single `report.html` 3-tab switcher. **Pick/MultiValue + Java** coverage added across the family (LLM-path); `legacy-code-intel` gains a Java symbol addendum.
- **New skill `env-readiness`:** a read-only environment readiness doctor — reviews `~/.claude` + per-project settings (skills/agents/workflows, SessionStart hooks, config, gates, identity, tooling) and prints a READY / READY-WITH-WARNINGS / NOT-READY verdict with repair pointers. Never mutates.
- **Dependency ergonomics:** the lineage skills ship `requirements-optional.txt` + a `check_deps.py` doctor (`--check-deps`) + a "Dependencies & environments" guide (venv / PEP-668 / air-gapped / VS Code) — core stays pure-stdlib, enhancers are opt-in and never auto-installed.
- **AMY (pa-server) M0b:** routine engine, role-lens, review-scopes, nudge-lifecycle, and the AMY brief hook with integration tests.
- Counts: 159 → **182 skills**, 4 → **5 agents**, 8 → **9 workflows**.

### 1.0.x — prior
- Established the curated skill/agent/workflow tree, the bootstrap installer, the security keystone (`llm-security`, `secret-scanning`, `sast-tooling`, `threat-modeling`), the career family, and the legacy-comprehension siblings (`lineage-extract-static`, `legacy-code-intel`, `structure-recovery`).

---

## License

[MIT](LICENSE)

---

## Disclaimer

This repository is a collection of prompts, documentation, and configuration designed to work with Claude Code CLI. It does **not** contain executable programs (beyond small helper scripts in some skills). Running the skills and agents requires Claude Code CLI and, for the full experience, additional third-party tools documented in [docs/dependencies/](docs/dependencies/README.md).

The skills encode *how* to perform tasks — Claude reads them and acts on your behalf. You are responsible for reviewing Claude's actions before confirming destructive operations (deletes, force pushes, production deploys, etc.).
