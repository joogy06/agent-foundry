# Drift symptoms — how to recognize drift in real time

If you notice any of these in your own behavior, you are drifting. Stop, run
`anti-drift checkpoint`, and re-anchor.

## Tier 1 — High-confidence drift indicators

1. **Proposing the same fix twice** in different forms across the conversation.
   Example: "Let me try X" → fail → "What if we try X but slightly different?"
   Cause: Lost track of what was already attempted. Externalized state would catch this.

2. **Forgetting which sub-task you're on**.
   Example: User asks for status, you reply with what you were doing 20 turns ago.
   Cause: Persona collapse + context rot. Need to re-anchor.

3. **Claiming completion without verifiable evidence**.
   Example: "Done!" without showing test output, file paths, or command results.
   Cause: Drift from "verification before completion" rule. Run metacognitive audit.

4. **Hedging heavily** ("I think", "perhaps", "this might", "let me try")
   when the original task was specific.
   Cause: Persona collapse — drifted into generic assistant mode.

5. **Generic responses** that don't reference the specific task context.
   Example: User asks about their PostgreSQL query, you give general SQL advice.
   Cause: Lost context of the project / task scope.

## Tier 2 — Medium-confidence drift indicators

6. **Re-asking a question already answered**.
   Cause: Lost-in-the-middle — the answer is buried in middle of context.

7. **Suggesting tools or approaches the user already rejected**.
   Cause: Persona collapse + LITM — forgot the rejection.

8. **Using outdated information** from earlier in the conversation
   when you should be using more recent input.
   Cause: Recency bias inverted — should be using most recent info but defaulting to old.

9. **Skipping verification gates** because "it's obvious".
   Cause: Drift from hard-rules-checklist. Always run the audit.

10. **Treating soft suggestions as requirements** or vice versa.
    Cause: Lost track of which were strict and which were preferences.

## Tier 3 — Low-confidence drift indicators (could be other things)

11. **Long, structured responses to simple questions**.
    Could be: drift, or could be appropriate thoroughness. Context-dependent.

12. **Asking for clarification on something previously specified**.
    Could be: drift, or could be legitimate ambiguity. Re-read original message first.

13. **Switching between formal and casual register mid-conversation**.
    Could be: drift, or could be appropriate adaptation. Check the system prompt.

## What to do when you spot a symptom

1. **Acknowledge it** — "I notice I'm drifting on X"
2. **Run `anti-drift checkpoint`** to re-anchor
3. **Externalize state** if not already done
4. **Re-read the task brief** verbatim
5. **Continue from a refreshed context**

Do NOT try to power through drift. The drift compounds.
