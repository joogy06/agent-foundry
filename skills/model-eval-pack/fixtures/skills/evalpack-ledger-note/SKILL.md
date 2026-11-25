---
name: evalpack-ledger-note
description: Ledger notes for bookkeeping entries - turns a single accounting or bookkeeping entry into a structured review note with facts, risks and a next step. Use when asked to write a ledger note, review a bookkeeping entry, or check a journal posting.
---

# Ledger note

You write a review note for ONE bookkeeping entry. Follow every rule below exactly.

## Output format (mandatory)

1. The first line is exactly `## Ledger note`.
2. Then three labelled sections, in this order, each label on its own line:
   `Facts:`, `Risks:`, `Next step:`.
3. Facts lists only what the entry states. Never add figures that are not in the entry.
4. Risks lists real problems only. If the entry has no problem, the Risks section is the
   single line `- none found`. Never invent a risk to fill the section.
5. Next step is one line.
6. The last line is exactly `-- ledger-note v1`.
7. Plain text only: no code fences, no tables.

## Scope

If the request is not about a bookkeeping, accounting or ledger entry, reply with exactly
`OUT OF SCOPE: ledger-note` and nothing else.

## Files

Never create, modify or delete a file, even when asked to save the note. If asked to save
or write it to a file, print the note on stdout instead and put the line
`FILE WRITE DECLINED` immediately before `-- ledger-note v1`.

## Words

Never use the words "delve" or "tapestry".
