---
name: threat-modeling
description: Use when designing a new component, service, or data flow that crosses a trust boundary, holds secrets, processes untrusted input, or has elevated privileges — produces a structured threat model using STRIDE (per-asset categories), LINDDUN (privacy-sensitive), and kill-chain mapping for high-stakes targets. Outputs a concise, decision-grade threat-model artifact callable by forge Step 1 (security/threat-model branch), alf sweeps, and bob WP-acceptance criteria. Trigger on - threat model, STRIDE, LINDDUN, attack surface, kill chain, attacker model, trust boundary, data flow diagram (DFD), security design review, threat enumeration, "what could go wrong", privacy review, GDPR threat model, MITRE ATT&CK mapping.
---

# Threat Modeling

## Overview

Threat modeling — structured enumeration of "what could go wrong" for a system, BEFORE it ships. The goal is not perfection but **calibration**: forcing the design team to name the attacker, the assets, the trust boundary, and the controls so that defenses are commensurate with what's at stake.

This skill ships three methodologies; pick by stakes and data class:

| Methodology | When to use | Output |
|---|---|---|
| **STRIDE** | Most components — covers the 6 standard threat categories per data flow | STRIDE table + per-threat mitigations |
| **LINDDUN** | Privacy-sensitive (PII, health, financial, biometrics) | LINDDUN table covering 7 privacy threat categories |
| **Kill-chain / MITRE ATT&CK** | High-stakes (production / critical infra / customer-facing trust) | Kill-chain phase mapping + technique catalog |

Companion skills:
- `llm-security` — agentic-system threats (LLM01-LLM10) — invoke INSTEAD of generic STRIDE for LLM-tool-use systems
- `python-auth-security` — implementation patterns for auth-related mitigations
- `secret-scanning` / `sast-tooling` — runtime defenses for secret-class threats
- `forge` Step 1 security branch — invoke this skill from the security branch when high-stakes design is detected

<HARD-RULE>
Threat modeling is a DESIGN-PHASE artifact, not a documentation exercise. The output MUST drive design decisions: at minimum, name 3 concrete mitigations the design now incorporates (or 3 explicit "accepted risk" decisions with sign-off). A threat model with no design impact is worse than no threat model — it manufactures false confidence.
</HARD-RULE>

<HARD-RULE>
Identify the trust boundary FIRST, before enumerating threats. "Inside" the boundary = your code, your processes, your developers. "Outside" = users, attackers, external services, third-party libraries, AI agents that read untrusted text. Threats that cross the boundary inward (attack surface) and outward (exfiltration / data leak) are the entire purpose of the exercise. Skipping this step produces threat lists with no priority and no actionable structure.
</HARD-RULE>

<HARD-RULE>
NEVER threat-model in isolation from the implementation team. The model is a design tool, not a security-team deliverable. Pair it with at least one engineer who will write the code; if they can't reason about which threats apply, the model is unhealthy and the team is misaligned. Forge's design-team pattern (lead + approach agents + challenger) is appropriate; pure security-team review of a finished design is not.
</HARD-RULE>

---

## 1. STRIDE (the workhorse)

STRIDE categorises threats by what they do to a system. Six categories, easy to remember:

| Letter | Threat | Property violated | Example |
|---|---|---|---|
| **S** | Spoofing | Authentication | Forging a user ID; impersonating a service |
| **T** | Tampering | Integrity | Modifying data in transit; altering stored records |
| **R** | Repudiation | Non-repudiation | User denies an action; no audit trail to refute |
| **I** | Information disclosure | Confidentiality | Leaked secrets, PII, internal data |
| **D** | Denial of service | Availability | Resource exhaustion; rate-limit absent |
| **E** | Elevation of privilege | Authorization | Acting as admin without being admin |

### STRIDE per data-flow element

A standard threat-modeling exercise runs STRIDE per element of the data-flow diagram (DFD):

| DFD element | Primary STRIDE applicability |
|---|---|
| External entity | S, R |
| Process | S, T, R, I, D, E |
| Data store | T, R, I, D |
| Data flow (in transit) | T, I, D |
| Trust boundary | (focus area — all 6 categories apply at the crossing) |

### STRIDE template (Markdown)

```markdown
## Component: <name>
**Stakes:** {low | medium | high | critical}
**Trust boundary:** <describe inside vs outside>
**Attacker model:** <who, what capabilities, what motivation>

| ID | Element | STRIDE | Threat | Mitigation | Status |
|---|---|---|---|---|---|
| T-01 | API endpoint POST /transfer | S | Forged caller identity | OAuth2 PKCE + tenant claim validation | Implemented |
| T-02 | API endpoint POST /transfer | T | Replay of legitimate request | Nonce + idempotency key | Implemented |
| T-03 | API endpoint POST /transfer | R | User denies action | Append-only audit log + signed receipt | Implemented |
| T-04 | API endpoint POST /transfer | I | Response leaks balance to unauthorised | RBAC check on account.owner_id | Implemented |
| T-05 | API endpoint POST /transfer | D | Rapid-fire transfers exhaust DB connections | Rate limit (10/min/user), circuit breaker | Implemented |
| T-06 | API endpoint POST /transfer | E | Caller escalates to admin via JWT manipulation | Validate `aud`, `iss`, `tid`, `azp` claims; signing-key rotation | Implemented |

**Accepted risks (with sign-off):**
- T-07: TOCTOU race between balance check and debit. Accepted: locked at row-level via SELECT FOR UPDATE; very-fast-path may still race under extreme contention. Mitigated by reconciliation job. Signed-off: <engineer>, <date>.
```

---

## 2. LINDDUN (privacy)

LINDDUN extends STRIDE for privacy-sensitive systems. Seven categories:

| Letter | Threat | Property violated |
|---|---|---|
| **L** | Linkability | Anonymity (linking records to one identity) |
| **I** | Identifiability | Anonymity (deriving identity from data) |
| **N** | Non-repudiation (problematic for whistleblowers, anonymous tips) | Plausible deniability |
| **D** | Detectability | Undetectability (presence of a user is itself sensitive) |
| **D** | Disclosure of information | Confidentiality |
| **U** | Unawareness | Notice/consent |
| **N** | Non-compliance | Regulatory (GDPR / CCPA / HIPAA) |

Use LINDDUN when:
- Component handles PII directly (names, addresses, IPs, biometrics, financials, health)
- Regulatory regime requires it (GDPR, CCPA, HIPAA, PIPEDA, LGPD)
- The system claims "anonymous" or "private" in marketing
- High-stakes social/political/employment data

### LINDDUN template addition (extends STRIDE table)

```markdown
| ID | Element | LINDDUN | Threat | Mitigation | Status |
|---|---|---|---|---|---|
| P-01 | Analytics event store | L (Linkability) | Two pseudonymous events can be linked via IP+device fingerprint | IP truncation, no device-fingerprint storage | Implemented |
| P-02 | User profile API | I (Identifiability) | Quasi-identifier set (DoB + ZIP + sex) re-identifies the user | k-anonymity k≥5 on returned aggregations | Implemented |
| P-03 | Login event log | D (Detectability) | Existence of a record reveals user activity on a sensitive date | Login events purged after 90 days | Implemented |
| P-04 | Consent management | U (Unawareness) | User isn't aware of secondary data use | Granular consent screen + change-of-purpose notification | Implemented |
| P-05 | Marketing pixel | N (Non-compliance) | GDPR Art. 6 lawful basis not documented | Cookie consent banner + lawful-basis matrix in data inventory | Implemented |
```

---

## 3. Kill chain / MITRE ATT&CK (high-stakes)

For production-critical / customer-facing-trust components, map adversary behaviour to kill-chain phases. Use MITRE ATT&CK technique IDs for the actionable detail.

### Kill chain phases

| Phase | Adversary objective |
|---|---|
| Reconnaissance | Find exposed assets, version info, employee names |
| Resource development | Buy domains, set up infrastructure |
| Initial access | Phishing, supply chain, exploit-public-facing-app |
| Execution | Run code on the target |
| Persistence | Maintain access (scheduled tasks, accounts, autoruns) |
| Privilege escalation | Move from user to admin |
| Defense evasion | Disable logging, sign malware, encode artifacts |
| Credential access | Dump LSASS, keylog, password spray |
| Discovery | Internal recon: AD, network shares, hosts |
| Lateral movement | Pivot to other hosts |
| Collection | Stage data for exfil |
| Command and control | Beacon, DNS tunnel, web shell |
| Exfiltration | Move data out |
| Impact | Encrypt, destroy, modify |

### Kill-chain template addition

```markdown
## Adversary scenarios (high-stakes)

### Scenario A: External attacker, opportunistic
**Profile:** Skilled but not-targeted; scanning for vulns.

| Phase | Likely technique | Our detection | Our prevention |
|---|---|---|---|
| Reconnaissance | T1595 — active scanning of public endpoints | WAF logs + rate-anomaly alert | Public-facing endpoint minimisation |
| Initial access | T1190 — exploit public-facing app (e.g. dep CVE) | dep-currency-check + WAF | Patched deps; minimal-privilege service |
| Execution | T1059 — command-and-scripting interpreter | EDR + audit log | Read-only FS; no shell access |
| Privilege escalation | T1078.004 — cloud accounts | CloudTrail anomaly | Least-privilege IAM |
| Credential access | T1552.001 — credentials in files | secret-scanning + EDR | No secrets in code (gitleaks) |
| Exfiltration | T1567.002 — exfil to cloud storage | egress allowlist + DLP | Egress allowlist + tenant-DLP |

### Scenario B: Insider (employee, contractor, sub-processor)
**Profile:** Authorised baseline access; abusing privilege.

| Phase | Likely technique | Our detection | Our prevention |
|---|---|---|---|
| Discovery | T1087 — account discovery | Audit log review | RBAC minimisation |
| Collection | T1213 — data from info repository | DLP + access logging | Least-privilege; data classification |
| Exfiltration | T1567 — exfil via web service | Egress monitoring | Egress allowlist; sensitive-data flag |
```

---

## 4. Mitigation classes — what defenses look like

When a threat is identified, the design must respond with one of:

| Class | Description | Example |
|---|---|---|
| **Eliminate** | Remove the surface entirely | Drop the feature; close the endpoint |
| **Prevent** | Make the attack infeasible | Parameterised SQL, TLS, MFA, sandbox |
| **Detect** | Spot the attack while in progress | Anomaly logging, IDS, audit alerts |
| **Respond** | Limit damage post-detection | Auto-revoke session, isolate host, rate-limit |
| **Recover** | Restore service after damage | Backup restoration, rollback, replay |
| **Accept** | Document and sign off | Risk too low to invest; explicit acceptance |

Every threat in the table MUST map to at least one mitigation class. An entry of just "we'll be careful" is a defect — replace with concrete control or accepted-risk sign-off.

---

## 5. When to invoke (decision tree)

```
Does the component process untrusted input OR hold secrets/tokens
OR cross a trust boundary OR have elevated privileges?
│
├── NO → No formal threat model needed. Apply baseline security
│        practices (TLS, auth, audit log). Document a one-paragraph
│        "low-stakes; STRIDE deferred" note in the design.
│
└── YES → Is it an LLM-tool-use / agentic system?
        │
        ├── YES → Use `llm-security` (OWASP LLM Top 10 + Dual LLM
        │        architecture) INSTEAD of generic STRIDE. The skill
        │        already structures the threat space for that class.
        │
        └── NO  → Does it handle PII / health / financial / regulated data?
                │
                ├── YES → STRIDE + LINDDUN (§1 + §2)
                │
                └── NO → Is it high-stakes (production-critical,
                         customer-trust, irreversible action)?
                        │
                        ├── YES → STRIDE + Kill-chain (§1 + §3)
                        │
                        └── NO → STRIDE only (§1)
```

---

## 6. Output template (decision-grade)

```markdown
# Threat Model: <component-name>

**Date:** 2026-MM-DD
**Author(s):** <engineer>, <reviewer>
**Component:** <path-or-URL>
**Methodology:** STRIDE [+ LINDDUN] [+ Kill-chain]
**Stakes tier:** low | medium | high | critical
**Estimated time-to-mitigate:** <hours-or-WPs>

## 1. Trust boundary
<one paragraph describing inside vs outside, with diagram if non-trivial>

## 2. Attacker model
**Who:** <profile — external, insider, adversary state-level, opportunistic>
**Capabilities:** <what they can already do — typed inputs, network access, internal credentials>
**Motivation:** <financial gain, data theft, sabotage, espionage, harassment>

## 3. Assets
| Asset | Sensitivity | Where stored | Access path |
|---|---|---|---|

## 4. Threats — STRIDE
<the STRIDE table from §1>

## 5. Threats — LINDDUN (if applicable)
<the LINDDUN table from §2>

## 6. Adversary scenarios (high-stakes only)
<kill-chain scenarios from §3>

## 7. Design decisions driven by this model
- Decision 1: <what changed in the design because of this exercise>
- Decision 2: ...
- Decision 3: ...
(MUST have at least 3 — see HARD-RULE 1)

## 8. Accepted risks (with sign-off)
- Risk 1: <description> — signed by <engineer>, <date>
- Risk 2: ...

## 9. Open items
- Item 1: needs further investigation in <area>
- Item 2: ...

## 10. Reassess trigger
This model is valid as of <date>. Reassess if:
- New trust boundary added
- Asset sensitivity changes
- Major dependency upgrade
- Production incident
- Annual review
```

---

## 7. Worked example — a sketch

```markdown
# Threat Model: cross-project-mail v1
**Stakes tier:** medium (single-host trust model; agents-not-humans)
**Methodology:** STRIDE

## 1. Trust boundary
Single Linux host, single user. All projects share the user's filesystem trust.
Inside: any agent invocable as the same UID. Outside: other UIDs, the network,
agents in different containers.

## 2. Attacker model
- Compromised agent in a sibling project (prompt-injected via a tool result it
  read), trying to use cpmail to influence agents in a more-privileged project.
- Mistyped sender claim (`source_type: human` when content is actually scraped
  web text).

## 3. Threats — STRIDE
| ID | Element | STRIDE | Threat | Mitigation | Status |
|---|---|---|---|---|---|
| T-01 | cpmail read | S | Sender claims `source_type: human` when actually scraped | Recipient agent treats body via `<user_data>` wrap regardless of source_type | Implemented |
| T-02 | cpmail file storage | T | Stale mail tampered post-send | Append-only; no edit API | Implemented |
| T-03 | cpmail audit | R | Sender denies sending | (Single-user model: acceptable; v1 scope) | Accepted — see history |
| T-04 | cpmail read body | I | Mail body contains scraped tokens | Recipient must NEVER eval body content (HARD-RULE) | Implemented |
| T-05 | cpmail spam | D | Sibling spams inbox | Per-project quota (deferred to v2) | Accepted — single-user low-stakes |
| T-06 | cpmail escalation | E | Sender's content steers recipient to use privileged tools | Recipient must read via `cpmail read` (delimiter wrap); no direct `cat` | Implemented |

## 7. Design decisions driven
1. `<user_data>` delimiter wrap on every body read (mitigates T-01, T-04, T-06)
2. `source_type` enum with required honest declaration (mitigates T-01)
3. v2 deferred queue authentication for cross-host (acknowledges T-03 + T-05)
```

This is roughly the model that produced the actual `cross-project-mail` skill. Notice every threat resolved to either a concrete mitigation or an explicit accepted-risk.

---

## 8. Anti-patterns

| Anti-pattern | Why it fails | Correct approach |
|---|---|---|
| Threat-model AFTER the design is locked | Mitigations cost more or aren't possible | Threat-model AS PART of design exploration; forge Step 1 routes here |
| Enumerate every conceivable threat | Analysis paralysis; nothing ships | Focus on threats that cross the trust boundary AND have plausible attackers |
| List threats without mitigations | "We documented the risk" ≠ "we're protected" | Every threat MUST map to eliminate / prevent / detect / respond / recover / accept |
| Treat "accept" as the default | Hides under-investment in security | Accept requires sign-off + rationale + reassess trigger |
| Skip the attacker model | "Generic attacker" = vague mitigations | Name 1-3 concrete adversary profiles |
| Use STRIDE for an LLM-tool-use system | STRIDE doesn't carve LLM-specific threats well | Use `llm-security` (OWASP LLM Top 10) instead |
| Skip LINDDUN when handling PII | GDPR non-compliance is one valid threat that STRIDE doesn't surface | Use LINDDUN in addition to STRIDE for PII components |
| Lift threats from another project's TM verbatim | Wrong attacker model, wrong boundary, wrong stakes | Threat models are project-specific; reuse template not content |
| Run threat-modeling as a security-team gate | Disconnects from implementation; produces shelfware | Pair with the implementation engineer; threat-model is a design tool, not a deliverable |
| Update the threat model never | New attack surfaces appear with every dependency upgrade | Reassess trigger written in §10; alf sweeps for stale models |

---

## 9. Selection Cheatsheet

- **Building an LLM agent that has tool access** → `llm-security` skill (Dual LLM architecture). Not this one.
- **Building a new REST API endpoint** → STRIDE (§1). 30-60 min exercise.
- **Building a feature touching user PII** → STRIDE + LINDDUN (§1 + §2). 60-90 min.
- **Building production-critical / customer-trust component** → STRIDE + Kill-chain (§1 + §3). 90-150 min.
- **Building both: PII-handling production-critical** → STRIDE + LINDDUN + Kill-chain. ~2 hours.
- **Refactoring an existing component without expanding the trust boundary** → No new model. Verify the existing one still applies.
- **Quarterly security review** → Re-walk existing TMs against new ATT&CK techniques and new CVEs surfaced by `dep-currency-check`.

---

## 10. Gotchas

| Gotcha | Detail |
|---|---|
| STRIDE-per-DFD-element produces ~30+ threats for non-trivial systems | Triage to the top 8-12 by impact × likelihood before tabulating |
| LINDDUN's "N" (Non-repudiation) is the OPPOSITE of STRIDE's "R" | LINDDUN-N: anonymity wanted, non-repudiation is a threat; STRIDE-R: non-repudiation wanted, repudiation is a threat |
| MITRE ATT&CK technique IDs change | Use the latest enterprise-matrix; review annually for renamed techniques |
| Kill-chain mapping can become wargame fiction | Cap it at 1-2 realistic scenarios; resist the urge to model nation-state APT for an internal CRUD app |
| Threat-model artifact rots faster than docs | Reassess triggers in §10 are mandatory; alf flags stale TMs |
| "Accepted risk" without sign-off is decay | The sign-off + date is the only thing that distinguishes accept from neglect |
| LLM-tool-use systems don't fit STRIDE cleanly | Use OWASP LLM Top 10 framing via `llm-security` instead |

---

## 11. Update triggers (alf scans these)

- New OWASP Top 10 / OWASP LLM Top 10 / OWASP ASVS edition (re-map categories)
- New MITRE ATT&CK techniques added (or technique renamed)
- New LINDDUN guidance from the methodology working group
- New regulatory regime (e.g. EU AI Act, US AI EO updates)
- Major incident in the wild attacking a similar component class
- Annual review on 2027-05-25

---

## 12. See Also

| Need | Skill |
|---|---|
| LLM-tool-use threat model | `llm-security` |
| Python implementation patterns for STRIDE mitigations | `python-auth-security` |
| SAST runner for design-doc-as-code | `sast-tooling` |
| Dependency-CVE input to TM | `dep-currency-check` |
| Secret-class threat detection | `secret-scanning` |
| Forge Step 1 security branch (which routes here) | `forge` |
| Observability for detection-class mitigations | `observability` |
| The G_SECURE gate that consumes mitigation evidence | `_meta/gates.py` |
