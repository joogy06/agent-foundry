<!-- convergence-rule.v1 id=CONV-1 -->
# CONV-1 — one winner plus named borrowed parts, never a blend

When rival outputs are merged into one, pick one winner, keep it whole, and add only named borrowed parts that
the winner re-makes. Do not average the candidates into a blend: a blend keeps every candidate's compromises and
no candidate's point of view.

This file is the only definition of the rule. Everything else cites it by id (`CONV-1`) and does not restate it;
`skills/_meta/tests/test_convergence_rule.py` fails a citing file that lacks the id and fails a second
definition. The citing files are listed in `skills/_meta/tests/fixtures/convergence/citing-files-sample.json`.

## Applicability

The rule applies only when all three answers are "yes". One "no" means the case is an exclusion: use the table
below instead.

1. Do the candidates fill the same slot?
2. Is exactly one output wanted?
3. Does at least one candidate clear the bar?

## The eligible winner

The winner must be an eligible candidate: one that passes the blocking checks, or one selected for repair and
re-checked before the award is confirmed. A candidate that fails a blocking check and has not been repaired and
re-checked cannot win, however good it looks otherwise.

## Borrowed parts

A borrow is a named part of a losing candidate, re-made by the winner in the winner's own terms. It is never
pasted in from the loser. Each borrow is recorded with the candidate it came from and what it is, so a reader
can see what the final output owes to whom.

## Exclusions

| When | Instead |
|---|---|
| The candidates are complementary layers or slices, not rivals | Compose them and record the interface between them |
| A portfolio is wanted: several outputs, not one | Rank and keep several; merge only near-duplicates |
| The inputs are review findings | Take the union |
| The inputs are a research synthesis | Take the union of the evidence, with the conflicts listed |
| The candidates dispute a fact | Settle it with evidence or a test |
| The choice is a taste or business call the brief does not settle | Ask the user |
| No candidate clears the bar | Record `no_award`; name no winner |
| A borrow would change the winner's core mechanism | Refuse the borrow, or declare the result a new candidate and judge it as one |
