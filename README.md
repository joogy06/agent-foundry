# Claude Code Skills & Agents

A curated collection of skills and agents for [Claude Code CLI](https://claude.ai/code), covering software engineering, DevOps, data engineering, infrastructure administration, and workflow orchestration.

> **About this file**: This is a template for the public repository root README. When you create the GitHub repo, rename this file to `README.md` at the repo root alongside `skills/` and `agents/`.

---

## What's Inside

- **150+ skills** — domain knowledge Claude loads on demand to help with specific tasks (including `publish-to-github` for releasing this whole tree to public github safely, and `visual-companion` for browser-based mockup/diagram review during design)
- **4 agents** — specialized sub-agents for design, execution, review, and knowledge management
- **Slash commands** — short user-invoked workflows under `~/.claude/commands/` (e.g. `/exit-with-docs` to wrap up a session and update project docs)

Skills are auto-discovered by Claude Code from frontmatter descriptions — you don't call them explicitly. Agents are invoked by name (`forge`, `bob`, `alf`, `pa`, `wiki`). Commands are invoked with a leading slash (e.g. `/exit-with-docs`).

---

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/<your-username>/<repo-name>.git
cd <repo-name>

# 2. Run the installer (asks a few questions; symlinks by default)
python3 install.py
# or, on Linux/macOS:   ./install.sh
# or, on Windows:       install.cmd
```

The installer asks:
1. **Which CLIs?** — Claude Code, Gemini, GitHub Copilot, or all
2. **Mode?** — `link` (symlinks; agent-foundry edits propagate; recommended) or `move` (copy; independent)
3. **Path overrides** — useful on enterprise machines where `~/.claude` etc. are non-standard

It then:
- For **Claude Code**: places skills + agents + commands under `~/.claude/skills/`, `~/.claude/agents/`, and `~/.claude/commands/`
- For **Gemini CLI**: runs `gemini skills link <path>` per skill (or falls back to direct symlink if `gemini` isn't on PATH)
- For **GitHub Copilot**: writes a cross-tool `~/.claude/AGENTS.md` bridge file (Copilot has no native skill concept) and prints VS Code per-project setup instructions

### Non-interactive install

```bash
python3 install.py --noninteractive                       # Claude + link
python3 install.py --target claude,gemini --mode link
python3 install.py --target all --mode move --force       # full copy, overwrite
python3 install.py --claude-home /opt/claude              # custom path
python3 install.py --help                                 # all flags
```

### Windows enterprise notes

- `install.cmd` is the entry point — it tries `python` / `python3` on PATH first, then falls back to `install.ps1` (PowerShell native, Claude install only).
- The PowerShell call uses `-ExecutionPolicy Bypass` so it works on locked-down machines that block dot-sourcing.
- Symbolic links require admin **or** Developer Mode. If symlinks fail, the installer transparently falls back to copy.

### Manual install (alternative)

If you'd rather not run a script:

```bash
cp -r skills/* ~/.claude/skills/
cp -r agents/*.md ~/.claude/agents/
cp -r commands/*.md ~/.claude/commands/
```

On next session, Claude auto-discovers everything in `~/.claude/skills/`, `~/.claude/agents/`, and `~/.claude/commands/`. For the full multi-model experience with Codex and Gemini as second-opinion models, see [Dependencies](docs/dependencies/README.md).

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

`forge` · `agent-teams` · `team-manager` · `challenger` · `qa-reviewer` · `ux-reviewer` · `research-for-skills` · `codex-orchestration` · `web-research` · `development-lifecycle` · `project-documentation` · `simplify` · `publish-to-github` · `visual-companion`

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

`ibm-mainframe` · `cobol-developer` · `db2-mainframe` · `ibm-mq` · `ibm-websphere` · `cognos-admin` · `cognos-user` · `datastage-developer` · `pega-robotics` · `control-m`

z/OS, JCL, COBOL, DB2 z/OS, IBM MQ, WebSphere, Cognos Analytics, DataStage, Pega RPA, Control-M workload automation.
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

## License

[MIT](LICENSE)

---

## Disclaimer

This repository is a collection of prompts, documentation, and configuration designed to work with Claude Code CLI. It does **not** contain executable programs (beyond small helper scripts in some skills). Running the skills and agents requires Claude Code CLI and, for the full experience, additional third-party tools documented in [docs/dependencies/](docs/dependencies/README.md).

The skills encode *how* to perform tasks — Claude reads them and acts on your behalf. You are responsible for reviewing Claude's actions before confirming destructive operations (deletes, force pushes, production deploys, etc.).
