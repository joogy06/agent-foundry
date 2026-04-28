Update ALL project documentation and exit the session cleanly.

## Steps

1. **Update PROJECT.md** — If `PROJECT.md` exists, update the architecture map to reflect any new components, files, integration edges, or dependencies added/changed this session. If new directories or major files were created, add them. Do NOT create PROJECT.md if it doesn't exist — that's `project-documentation`'s job.

2. **Update COMPONENT.md files** — If any `docs/components/*/COMPONENT.md` files exist for components that were modified this session, update them with new interfaces, dependencies, or behavioral changes. Skip if no component docs exist.

3. **Update history.md** — Append a session entry to `history.md` in the project root (create if missing):
   - Date: today's date
   - Summary: 2-3 bullet points of what was accomplished this session
   - Decisions: any architectural or design decisions made
   - If history.md exists, append to it. If not, create with a `# Session History` header.

4. **Update tasks.md** — Review and update `tasks.md` in the project root (create if missing):
   - Mark completed tasks as done
   - Add any new tasks discovered during the session
   - Note any blocked items with reasons
   - If tasks.md exists, update in place. If not, create with a `# Tasks` header.

5. **Update index.md** — If `index.md` exists, update the file index with any new files created this session. Skip if it doesn't exist.

6. **Update session_control.md** — If `session_control.md` exists, clear completed session instructions and note any carry-over items for the next session. Skip if it doesn't exist.

7. **PA session end** — If PA MCP server is available (`pa_health` responds), call `pa_end_session` with a brief summary.

8. **Report** — Show the user a brief summary:
   ```
   ## Session Wrap-Up
   - PROJECT.md: [updated/skipped/not found]
   - COMPONENT.md: [N updated/skipped/not found]
   - history.md: [N items added]
   - tasks.md: [N completed, N added, N blocked]
   - index.md: [updated/skipped/not found]
   - session_control.md: [updated/skipped/not found]
   - PA session: [logged/unavailable]
   ```

9. **Exit** — Tell the user the session is documented and they can close safely. Do NOT force-exit — let the user close when ready.

## Rules
- Be concise in all entries — facts, not filler
- Only update files that exist AND have meaningful changes to record
- If nothing was done this session, say so and skip file updates
- Convert any relative dates to absolute dates (e.g., "today" → "2026-04-04")
- Read each doc file before updating to preserve existing content
- For PROJECT.md, only add/modify entries for things that actually changed — don't rewrite the whole file
