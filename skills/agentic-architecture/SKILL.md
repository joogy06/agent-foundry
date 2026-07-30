---
name: agentic-architecture
description: Use when deciding how an LLM-backed system should be structured — whether it needs an agent at all or a deterministic workflow, which orchestration pattern fits (chain, router, parallel fan-out, orchestrator-worker, evaluator-optimizer, supervisor, hierarchical), how many agents, how state and durability work, where tools and human approval gates belong, how loops terminate within a budget, which framework class to adopt and when, and how to evaluate a trajectory rather than a single answer.
disambiguation: The SHAPE of the agentic system — agent vs workflow, which pattern, how many, how it terminates. Optimising the individual API calls inside it is llm-api-optimization; designing what it retrieves is rag-architecture; wiring external tools in over MCP is mcp-integration; this harness's own forge/bob/alf cascade is agent-teams, and building a Claude Code subagent is research-for-skills.
---

# Agentic architecture

<!-- REVIEW-BY: 2027-01-31 -->
**Verified 2026-07-29.** Framework positions move fast; the patterns below have been stable for
roughly two years and the framework names have not.

## 1. The expensive decision is made before any code

**Most agentic projects that fail, fail on orchestration design rather than model capability** —
forecasts through 2027 put a large share of agentic initiatives at risk of cancellation on cost,
governance and scaling grounds, and the common root is architecture, not the model.

**The strongest single guideline: if the task can be done with one well-prompted call or a fixed
chain, do that.** An agent is what you reach for when the steps genuinely cannot be known in advance
— and that is rarer than it feels during design.

**A healthy production system is mostly deterministic.** Aim for the large majority of the work
running as fixed, testable steps, with agentic reasoning confined to the parts where the path really
does depend on what was found. Deterministic steps are debuggable, cheap and repeatable; agentic
steps are none of those.

## 2. The decision tree

```
Can one well-prompted call do it?
├─ YES → Do that. Stop. Add retries and validation, not an agent.
└─ NO
   │
   Are the steps known in advance?
   ├─ YES → WORKFLOW
   │   ├─ Fixed order, each step feeds the next .............. Prompt chain
   │   ├─ Input kind decides the branch ..................... Router
   │   ├─ Independent subtasks, results combined ............ Parallel fan-out
   │   └─ Quality must clear a bar before release ........... Evaluator–optimizer
   └─ NO — the path depends on what is found → AGENT
       │
       Does one agent with a tool loop cover it?
       ├─ YES → Single agent + tools. Default. Go no further.
       └─ NO — genuinely separate domains, tools or context
           │
           How many, and who decides the split?
           ├─ Decomposed at runtime by a planner .... Orchestrator–worker
           ├─ Fixed specialist roles, one coordinator  Supervisor
           └─ More than ~20 agents ................. Hierarchical — and re-read §3
```

**Two questions carry almost all the weight**: *are the steps known in advance?* (workflow vs agent)
and *is there a real reason for a second agent?* (§3).

## 3. Multi-agent — the bar is higher than it looks

**Every additional agent adds coordination cost, latency, token spend and a new failure mode**, and
information is lost at every handoff — the receiving agent gets a summary, not the context.

Legitimate reasons for a second agent:

- **Context isolation** — one agent's working context would otherwise poison another's. This is the
  strongest reason and often the only real one.
- **Genuinely disjoint tool sets**, where handing all tools to one agent degrades tool selection.
- **Different trust or permission boundaries** — one agent may write, another may not.
- **Independent parallel work** on separable subtasks, where wall-clock matters.

Not reasons: mirroring your org chart · "specialists sound better" · a framework's examples all being
multi-agent · a single agent's prompt getting long (fix the prompt).

**Roughly six patterns cover nearly all enterprise use cases** — supervisor, sequential pipeline,
parallel fan-out, router, hierarchical, evaluator–optimizer — and production systems typically
**compose two or three**, e.g. a router at the front dispatching into orchestrator–worker pipelines
whose output passes an evaluator.

## 4. State, durability and resumption

**An agent that cannot resume is a prototype.** Real runs hit rate limits, timeouts, restarts and
deploys mid-flight.

- **Model the run as explicit state**, not as a call stack. A state machine or graph makes "where is
  it, and what happens next" answerable — from a log, by a person, at 3am.
- **Checkpoint after every externally-visible step.** Resumption is what turns a transient failure
  into a pause instead of a restart.
- **Make tool calls idempotent, or record that they happened.** Resuming a run that already sent the
  email and re-sending it is worse than failing.
- **Persist the decisions, not only the messages.** Replaying a conversation to reconstruct why the
  agent branched is guesswork; a recorded decision is not.

## 5. Tools are the agent's real interface

Tool quality determines agent quality more than prompt wording does.

- **Name and describe tools for the model**, not for your codebase. `search_invoices_by_supplier`
  beats `queryDocsV2`.
- **Few, well-scoped tools beat many overlapping ones.** Two tools that both plausibly fit a step
  produce wrong selections — the same degradation `skill-intake` measures for skills.
- **Return errors as instructions.** "No supplier matches 'Acme'; try `list_suppliers` for valid
  names" is recoverable; `Error 500` ends the run.
- **Cap tool output size.** A tool returning 100KB burns the window and may be truncated mid-record.
- **Scope permissions per tool**, and keep destructive ones behind §6.

## 6. Human-in-the-loop, on the actions that cannot be undone

**Autonomy is a per-action decision, not a system-wide setting.** Reads and reversible writes can run
free; payments, external messages, deletions, deploys and anything customer-visible get a gate.

- Present **what will happen**, not "approve step 4" — the reviewer needs the payload.
- Approval must **survive a restart**: a run waiting on a person is a durable state (§4), not a
  blocked thread.
- **An approval nobody has time to read is not a control.** If the gate fires constantly it will be
  rubber-stamped; narrow it until it is rare enough to be read.

## 7. Termination — the failure mode that shows up on the invoice

**Every loop needs a bound, and "the model will stop when it is done" is not one.**

- **Hard caps** on iterations, tool calls, wall-clock and **spend per task**.
- **No-progress detection** — repeated identical tool calls, or a plan that stops changing, means
  stuck, not thinking.
- **Fail loudly.** An agent that quietly returns its best partial guess at the cap is worse than one
  that reports it ran out — the caller cannot tell the difference from success.
- **Budget per task, not per call** (`llm-api-optimization` §9). Loops are invisible in per-call cost.

## 8. Frameworks — adopt after you have a working loop, not before

| Class | Fits |
|---|---|
| **No framework** — a loop, your tools, your state | Single agent, a handful of tools. **Start here** |
| **Graph / state-machine orchestration** | Production stateful workflows needing branching, checkpointing, resumption, human-in-the-loop |
| **Conversation-oriented multi-agent** | Collaborative agents negotiating a result |
| **Role/crew abstractions** | Fast prototyping of fixed specialist teams |

**The 2026 production centre of gravity is graph-based orchestration with durable checkpointing**,
with an integration/toolkit layer beneath it — the graph is the motherboard, the toolkit supplies the
components. But note what that reflects: the winning property is **durable, inspectable state**, not
any particular vendor.

**Write the loop yourself first.** A framework adopted before you understand your own control flow
buys abstractions over a problem you have not yet met, and every one of them is a dependency with its
own upgrade treadmill. Adopt when you need checkpointing, resumption and human-in-the-loop — that is
the point at which hand-rolling stops being cheaper.

## 9. Evaluation — score the trajectory, not just the answer

A correct answer reached by nine redundant retrievals and two lucky guesses is not a working system.

| Level | Measure |
|---|---|
| **Outcome** | End-to-end task success against a golden set |
| **Trajectory** | Steps taken, redundant or repeated calls, whether it stopped when it had enough |
| **Tool use** | Right tool chosen; arguments valid; failures recovered |
| **Cost** | Tokens and spend per **resolved task** |
| **Safety** | Did it stay inside its permissions and gates |

**Build a regression set of real tasks early.** Agent behaviour changes with every prompt, tool and
model edit, and without a fixed set of tasks you are judging on whatever someone tried last.

**Log the whole trajectory in a readable form.** The single highest-value piece of agent
infrastructure is being able to read exactly what the agent did, in order, after the fact.

## 10. Anti-patterns

- **Building an agent** where a chain or a single call would do.
- **Multi-agent because it sounds sophisticated** — paying coordination cost for no isolation benefit.
- **Mirroring the org chart** in agent roles.
- **No durable state**, so any restart loses the run.
- **Non-idempotent tools** with no record of what already executed.
- **Unbounded loops** — no iteration, time or spend cap.
- **Silent partial success** at the cap, indistinguishable from a real answer.
- **Overlapping tools** that make selection ambiguous.
- **Raw stack traces as tool errors**, ending runs that were recoverable.
- **Approval gates so frequent** they are rubber-stamped.
- **Adopting a framework** before a hand-written loop has been made to work.
- **Evaluating only the final answer**, so cost and redundancy stay invisible.
