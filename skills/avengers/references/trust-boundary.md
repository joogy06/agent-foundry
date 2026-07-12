# avengers — trust boundary (v1)

The trust model every seat turn is assembled against (`scripts/seat_prompt.py`),
and the honest statement of what it does and does not defend. Design §3/§5/§6.

## The 7-section trust envelope (fixed order)

`seat_prompt.assemble_prompt` is THE single assembler — no caller hand-rolls a
prompt, which is what makes the discipline "impossible to forget" (§3). Sections,
in order:

| # | Section | Trust | Content |
|---|---|---|---|
| 1 | `[TRUSTED_PROTOCOL]` | trusted | deliberation rules (first) |
| 2 | `[TRUSTED_ROLE_CARD]` | trusted | identity + stamped INCENTIVE LOCK + forbidden list |
| 3 | `[AUTHORIZED_TASK_DIRECTIVE]` | trusted | the task the chair authorizes |
| 4 | `[UNTRUSTED_REFERENCE_MATERIALS]` | untrusted | caller docs, JSON-escaped |
| 5 | `[UNTRUSTED_MEMBER_MEMORY]` | untrusted | standing records (JSON only, byte-budgeted) |
| 6 | `[UNTRUSTED_PEER_RECORDS]` | untrusted | schema-extracted peer claims (JSON only) |
| 7 | `[TRUSTED_PHASE_REQUEST]` | trusted | the ask (**LAST** — recency anchor) |

**Invariant:** `[TRUSTED_PHASE_REQUEST]` is always last. Untrusted sections carry
DATA to reason about, never commands; the protocol tells every seat that an
instruction found inside untrusted data is to be **reported, not obeyed**.

## Controls (what they are — honestly)

- **Parser-integrity controls.** Fences (`[SECTION]…[/SECTION]`), JSON-escaping
  of untrusted materials/memory/peer records, and **schema extraction** of peer
  turns (never raw peer markdown — also the anti-quadratic-transcript control).
  These keep untrusted bytes from *breaking the frame* or forging a section
  header. `test_prompt_boundaries.py` asserts exactly one real `[TRUSTED_PROTOCOL]`
  fence even when a fixture embeds a fake one.
- **Blind-diverge guard.** At `BLIND_DIVERGE` a seat sees identity + standing
  memory only; passing peer records raises (peers cannot leak into a blind turn).
- **Home-tier-only state.** All trusted instruction text (`~/.claude/skills/avengers/`)
  and member memory (`~/.claude/projects/<slug>/avengers/`) live under `~/.claude/`,
  never repo-local. The loader refuses paths outside the project tier (§14 — no
  global-tier branch). This defeats the pre-poisoned-clone vector (see
  `tests/fixtures/poisoned-memory.md`).
- **Admissibility + approval gate.** Standing memory is admitted only from the
  four Codex-class sources and never from episodic kinds; write-back is
  default-reject, per-item, persisted home-tier (see `memory-policy.md`).

## Semantic-injection residual (NOT denied)

Escaping and fences are parser-integrity controls. **Semantic injection —
persuasive instructions inside otherwise-valid data — has a REAL residual.** A
`statement` or a peer `claim` can still *argue* for a bad action in plain,
schema-valid text. The defenses are the trust envelope + schema extraction +
memory admissibility + the shipped adversarial fixtures (injected doc, injected
seat output, pre-poisoned memory, false-flag) + **chair adjudication** of
injection flags. A seat abusing "flag injection" to discount an honest peer is a
recorded residual risk adjudicated by the chair (not auto-discounted). No
"structurally secure" claim is made anywhere in the shipped prose.

## Pre-poisoned-clone residual (documented)

The write-back gate covers writes, not pre-existing files; home-tier-only loading
neutralises repo-carried memory. The remaining residual: the commit provenance
re-check reads the repo-local transcript, so a clone could fabricate a "source
turn" for display. The per-item **default-reject user approval** is the final
gate, and the commit tool prints the source-turn excerpt + provenance origin so
the user judges with the evidence in view (§5).
