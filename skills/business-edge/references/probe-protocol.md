# Probe protocol — how to scan an entity without inventing a negative

The scan is the foundation of the engagement. **A false negative here poisons everything downstream**,
because "nothing found" reads as a strategic finding when it is often just a broken tool.

This protocol exists because of a real, recorded failure (2026-07-26): a brand was reported as having
"essentially zero Reddit presence." It had an active footprint that **Google's own AI Overview was
built almost entirely from** — including a founder's technical claim and a public criticism of the
website. Four separate tools failed in four different ways, and the confident wrong answer was fed
into a design deliberation as a load-bearing premise.

---

## 1. Probe status — mandatory on every probe

| Status | Meaning |
|---|---|
| `FOUND` | Results retrieved and relevant |
| `SEARCHED_NOT_FOUND` | Probe **provably executed and returned** — genuine evidence of absence |
| `BLOCKED` | Robots/login/paywall/rate-limit refused the request |
| `CAPTCHA` | Bot challenge served |
| `FAILED` | Error, timeout, or a malformed/nonsense response |
| `NOT_PROBED` | Not attempted — say so rather than implying coverage |

**Only `SEARCHED_NOT_FOUND` supports a claim of absence.** Everything else is missing data.

A surface with no `SEARCHED_NOT_FOUND` and no `FOUND` is **unknown**, not empty. Report it as
unknown, in those words.

---

## 2. Known failure modes — check these before trusting a null

| Tool | Failure observed | Mitigation |
|---|---|---|
| Consumer search APIs | **Region-locked** (US-only), so non-US brands vanish | Use a real browser; add region/locale terms |
| `site:` operators via API | Silently unsupported — returns unrelated results rather than an error | If results look topically unrelated, treat as `FAILED`, not `SEARCHED_NOT_FOUND` |
| Reddit programmatic access | Serves HTML/interstitial instead of JSON | Browser, or search via a general engine restricted to the domain |
| Bing / DuckDuckGo scripted | CAPTCHA or empty body | Browser |
| Any single engine | Index coverage differs per engine | **Never conclude from one engine** |

> **The tell:** if a query for a specific brand returns encyclopedia entries about unrelated
> companies, the operator was not honoured. That is `FAILED`. It is not absence.

---

## 3. Surfaces to sweep

Discovery · communities and forums · review platforms · marketplaces · social · news/PR · company
registries · the competitor set · **and the AI answer layer itself**.

### 3.1 The AI answer layer — often the most valuable surface

Ask each major assistant the questions a real buyer would ask, and record **the answer and its cited
sources**:

- `is <entity> legit / any good / safe to buy from`
- `<entity> reviews` · `<entity> vs <competitor>`
- `best <category> for <use case> under <budget>` — does the entity appear *unprompted*?
- `who should I buy <category> from in <region>`

Capture: is the entity **mentioned**, **recommended**, or **cited with a link** (three different
things); which sources the model leans on; **and any negative claim it repeats.**

> **The brand summary an AI gives is a public artifact the operator does not control and usually has
> never read.** It frequently contains their defects verbatim, and those defects are being delivered
> to buyers at the decision moment. Always capture it, always show it to the operator.

### 3.2 Query families
Brand exact · brand + "reviews"/"legit"/"scam"/"complaints" · brand + competitor · category + region ·
category + use case + budget · the entity's own claims (to check whether they propagate).

Vary locale and phrasing. A UK brand may be invisible to a US-defaulted tool.

---

## 4. Third-party custody

For each claim a buyer would want verified, record **who custodies the proof**:

| Custody | Weight |
|---|---|
| Seller's own domain | Weak — asserted, not corroborated |
| Third-party record (marketplace feedback, review platform, registry, certification) | **Strong — independently checkable** |

Retrieval systems and sceptical humans both discount self-custodied claims. A gap between "the
operator says X" and "an independent record shows X" is one of the most actionable findings the scan
produces.

---

## 5. Output

A surface map plus a probe ledger. The ledger is **not** an appendix — the engagement's confidence
is bounded by it, so any BLOCKED/FAILED surface must be visible in the summary, not buried.

Every downstream claim inherits the status of the probe it rests on. **A strategy built on
`NOT_PROBED` is a guess wearing a citation.**
