# Model routing and cost in VS Code / Copilot

<!-- REVIEW-BY: 2026-10-31 -->

## The rule: detect, never hardcode

**No model version appears in any config in this folder, deliberately.** Copilot's roster changes
frequently and varies by plan, organisation policy and region. A model id baked into a config becomes
a silent failure that presents as a permissions error — the worst kind, because it looks like access
rather than staleness.

```bash
python3 vs-code/scripts/detect_models.py           # at install AND at runtime
```

The answer legitimately differs between those two moments: an org policy or plan change moves the
roster without touching this machine. **If detection returns nothing, that means detection could not
reach a roster — not that no models exist.** Check the picker in VS Code and record what you see.

## Why multi-model matters here, not just cost

foundry-lab's design assumes **provider diversity**: Claude, plus Codex, plus a third arm. The reason
is recorded in the Claude arm and it holds identically here — **a second opinion from the same family
shares the first one's blind spots**, so a cross-check between two models of one vendor is theatre.

Copilot typically offers Anthropic, OpenAI and Google families in one picker, which makes genuine
cross-vendor review *easier* here than in the CLI arm, not harder. Use that.

## Routing by task weight

| Work | Tier | Why |
|---|---|---|
| Mechanical edits, renames, formatting, boilerplate | **cheap/fast** | No judgement required; a premium model buys nothing |
| Implementation against a clear spec | **mid** | Correctness matters, novelty does not |
| Design, architecture, review, debugging something subtle | **strong** | Where model quality actually changes the outcome |
| **Adversarial second opinion** | **different VENDOR** | The point is disagreement, not more capability |

**Switch deliberately and say why.** "Moving to a stronger model because this is an architecture
call" is useful; a silent switch that triples cost is not.

## Cost control

- **Premium requests are metered.** Treat the strong tier as a budget, not a default.
- **Do not leave a premium model selected** for a session of mechanical work.
- **Prefer one well-framed strong-model call** over several weak ones that need re-doing — cheapest
  is not the same as least total cost.
- **Scope the context.** A whole-repo request costs more and answers worse than a targeted one.
- Where the Claude arm would fan out to several agents, **VS Code subagents cost real requests** —
  fan out when the work genuinely parallelises, not by reflex.

## Mapping from `smart-config`

The Claude arm grades a task into a tier and resolves tier → model per project
(`~/.claude/model-policy.yaml`). VS Code has **no equivalent resolver**; selection is the picker or
`@`-mention in chat.

**Correction (verified 2026-07-29): the mapping is more mechanical than first written.** `.agent.md`
frontmatter supports a **`model:` field taking a single name OR a prioritised list**, so a tier can be
pinned per agent rather than chosen by hand each time:

```yaml
---
name: Reviewer
description: Design and code review — the strong tier.
model: ['<strong-model>', '<fallback-model>']   # detected ids, never hardcoded
tools: ['codebase', 'search', 'problems']
---
```

A prioritised list is exactly the fallback behaviour `smart-config` wants: first choice, then a
degrade path when it is unavailable under the current plan or policy.

**What still does not port:** there is no per-project resolver equivalent to
`~/.claude/model-policy.yaml`, and no automatic task grading. The tier lives in the agent definition,
so **one agent per tier** is the shape — not one agent that re-grades per task. Say "tier pinned per
agent", not "smart-config parity".

**Fill the model ids from detection**, never from memory — `scripts/detect_models.py`.
