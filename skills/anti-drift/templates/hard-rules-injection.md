# End-of-prompt recency anchor (for sub-agent spawning)

> Append this to the END of any sub-agent spawn prompt. The placement is structurally
> important — last-token bias > first-token recall.

---

## CRITICAL REMINDERS — re-read before each action

These rules must be followed without exception. They are stated last because they are
the most important.

1. **Verify before claiming complete**. No task is done without tangible evidence
   (file path, command output, test result, build success). Self-reports do not count.

2. **Externalize state**. Do not rely on recall. Write progress to .session-state.md
   and re-read it at decision points.

3. **Never retry a failed approach** without changing something material. If approach
   X failed once, X' must be meaningfully different from X.

4. **Run the metacognitive audit** before claiming complete. Switch to Checker persona,
   re-read the brief verbatim, demand evidence for each requirement.

5. **Stop and ask** if you're uncertain about a destructive action (rm, force push,
   deploy). The cost of asking is small; the cost of an undone action is high.

[Add task-specific critical rules here, also at the bottom for recency.]
