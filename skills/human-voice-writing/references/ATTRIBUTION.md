# Attribution: where the pattern probe comes from

`scripts/pattern_probe.py` is this library's OWN code. It was written from this library's own catalogue of
machine-writing patterns. One open-source project was looked at for the idea of a checker and for the names of
its pattern categories. No code, no pattern, no word list and no passage of that project is in this library,
and nothing of it was installed, imported or run.

**Contents:** Route taken · The source that was looked at · Intake verdict · Where the categories come from · What differs by design · Copy check

<!-- FRESHNESS:v1
anchors:
  - kind: date_review
    subject: looked-at-source-commit-and-intake-verdict
    review_by: "2027-04-12"
-->

## Route taken

The plan for this probe had two routes: adapt the external checker once a person had signed its intake
record, or write the probe as our own code from the published categories. **The second route was taken.** The
intake record of the source is a caution that no person has signed, so nothing of the source was adopted.
Adapting the checker itself stays open: it needs a person to read the triage sheet and sign the record
(`intake.py triage <id> --accept --reason "..."`), and that decision is the user's.

## The source that was looked at

| | |
|---|---|
| Project | SlopMonster |
| Repository | <https://github.com/ItsssssJack/SlopMonster> |
| Commit looked at | `3fc9787d9337b57c599a80afbefbbb3be5a8eb0b` (committed 2026-09-26) |
| Licence | MIT License |
| Copyright notice of the source | Copyright (c) 2026 Jack Roberts |
| Looked at on | 2026-10-12 |
| What was read | The README's table of five category names and the section headings of its pattern catalogue, as text |
| What was not read into this work | Its checker program (`tools/deslop.py`), its shell tool, its prompts and its word lists |

The MIT licence asks that its notice travel with copies of the software or substantial portions of it. No copy
and no portion is here, so the licence text is not reproduced; the project is credited because it prompted the
probe.

## Intake verdict

| | |
|---|---|
| Scanner | `skills/intake-scan` (`intake.py scan <clone> --kind repo --offline`) |
| Intake verdict id | `q20261012T143823Z-747fcbad` |
| Verdict | **caution**, not signed by a person |
| Scanned on | 2026-10-12 |

The scan found no block-rule hit. It returned caution for static-analysis notes on the source's Python test file
and skill text, and for coverage gaps (two shell files in a language with no static analysis here, files
inspected only in part). A caution is adopted only after a person signs it. This one is unsigned, so the unit
was not adopted, and the probe does not depend on it.

## Where the categories come from

Every category but one is a row of this library's own catalogue,
`career-coach/references/ai-tells-catalog.md`:

| Probe category | Our catalogue |
|---|---|
| `focal-word-cluster` | section 2, the focal-word cluster and its cluster-not-blocklist rule |
| `dash-density` | section 3, em-dash density |
| `not-only-but` | section 3, "Not only X but (also) Y" |
| `inverted-contrast` | section 3, "It's not X, it's Y" |
| `list-of-three` | section 3, tricolons |
| `even-rhythm` | section 3, uniform sentence length |
| `stock-opener`, `stock-closer` | section 3, formulaic opener and closer |
| `bold-lead-bullets` | section 3, bullet and bold overuse |
| `hedge-stack` | section 3, hedge-everything tone |
| `self-answered-question` | not in our catalogue; the source's README names self-answering questions among its sentence patterns, which is where the idea of this category was noticed. The pattern that finds it is our own. |

Two of the source's five categories were deliberately left out. Its "possible unsupported proof" category
(numbers near nouns such as customers) is the work of the studio's claim check, which holds a figure to a truth
pack; a voice probe has no business guessing at it. Its semicolon count is not in our catalogue and was not
added.

## What differs by design

The source's checker prints a score out of five and fails its exit status on a low one. This probe does
neither, because `human-voice-writing` forbids optimising a text against a detector (HARD RULE 2):

- it reports places (line, heading, paragraph) and categories, and nothing else;
- it holds no score, no total and no pass or fail;
- its exit code is 0 whenever it ran, so no caller can read quality from it;
- it declines text it does not take to be English (`not_run: language`), where the source has no language check.

## Copy check

On 2026-10-12 the probe, its tests, its fixtures, this file and every line this work added to `SKILL.md` and to
the studio runner were compared, word run by word run, with every text file of the source at the commit above
(its checker included, read as bytes by the comparing script and by nothing else). No run of six consecutive
words of prose, of a pattern or of a word list is shared. The only shared runs are Python's own boilerplate:
standard-library `import` lines in alphabetical order and the keyword arguments of `subprocess.run`, both of
which this repository's tests held before the source was looked at.
