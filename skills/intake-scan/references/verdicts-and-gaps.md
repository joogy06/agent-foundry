# Verdicts, gap effects and the record

The authority is `policy.json` beside this skill; `scripts/intake_policy.py` applies it. This
page explains what the tables in that file mean.

## How a verdict is reached

1. Every finding gets its class (block, caution, info) from `policy.json`, by rule id. The class
   a scanner gives its own finding is ignored. An id the reporting scanner does not own in the
   policy is not a finding: it becomes the gap `unknown-rule-id`.
2. Every gap gets an effect (see below).
3. **block** when there is a block-rule hit with no matching exception, or a gap whose effect
   is block. **caution** when there is any other finding or any other gap. **pass** otherwise.

An excepted block-rule hit stays in the record, marked `excepted`, and does not count: a person
already decided on it. Exceptions exist only for units of this repo (`scan --local`,
`baseline`); a fetched target has none, and takes an `override` instead.

What a scanner reports about its own run (a score, a severity label, an exit status) is copied
into the record under `evidence` and is never an input to any of the three steps.

## Gap effects

| Effect in `policy.json` | Meaning | On the verdict |
|---|---|---|
| `scanner` | the scanner's result is absent or cannot be relied on | block when the scanner is required for the target kind, caution when it is optional |
| `coverage` | part of the target was not looked at | caution |
| `block` | the scan itself is incomplete, or a scanner reported something that must never happen | block |

Gaps a reader meets most often:

| Gap | Effect | Why |
|---|---|---|
| `toolchain-missing`, `toolchain-mismatch` | scanner | the pinned scanner is not installed, or is not the pinned build |
| `sandbox-unavailable`, `sandbox-unusable` | scanner | no `bwrap`; third-party scanners are not started |
| `scanner-crashed`, `scanner-timeout`, `scanner-report-unreadable` | scanner | the scanner ran and gave nothing usable |
| `scanner-not-run` | scanner | a scanner the policy lists produced no report |
| `file-not-covered` | coverage | a stored file no scanner beyond the in-house rules inspected (an image, for example) |
| `language-not-analysed` | coverage | an executable file that is not Python |
| `partially-inspected`, `python-file-not-analysed` | coverage | a scanner read a file in part, or skipped it |
| `analyzer-incomplete` | coverage | the scanner finished, and one of its analyzers says it could not evaluate something (a reference to a file the target does not ship, text it could not fully decode). Routine on a large skill; the notes are on the triage sheet |
| `osv-subcheck-not-run` | coverage | SkillSpector's own advisory lookup has no network in the sandbox; the dependency check covers it |
| `deps-advisory-lookup-failed` | coverage | no answer from the advisory service (no network) |
| `vcs-directory-skipped` | coverage | a folder target's own root `.git` (a directory, or the file a work tree or a submodule checkout has there) is not read and not stored |
| `unknown-rule-id` | coverage | a scanner reported an id that is not in our tables. From a scanner that owns block rules (the in-house rules, the dependency check) it blocks instead |
| `model-use-reported`, `findings-suppressed` | block | a scanner said it used a model or dropped findings; neither is ever configured |
| `git-clone-failed`, `archive-rejected`, `target-not-found` and the other acquisition gaps | block | nothing was acquired, so nothing was scanned |
| `scan-incomplete`, `evidence-malformed` | block | the scan stopped part-way |

A gap name the policy does not list is treated as a `scanner` gap, so an unknown gap from a
required scanner blocks.

## The record

`schemas/intake-verdict.v1.json` is the schema, and `intake_policy.validate_record()` applies
it. A record holds: `subject` (kind, source, commit, tree digest, and the unit for a scan in
place), the inventory digest, the rule, policy and tool versions, `isolation`, the findings
(rule id, class, opaque file id, line, scanner), `coverage`, `gaps`, the scanners' own run
facts under `evidence`, counts, and the review history that `override`, `triage` and `adopt`
append to.

Every string in a record is checked against a pattern, so a record holds no file name and no
line of content from the target. The two free-text fields are `subject.source.target` (what the
caller typed) and the reasons a person wrote in `review`.

## Where a record lives

| Scan | Record | Triage sheet |
|---|---|---|
| `scan <target>` | `<quarantine>/<id>/record.json`, copied to `intake/records/<id>.json` by `adopt` | `<quarantine>/<id>/triage.md` |
| `scan --local <unit>`, `baseline` | `intake/records/<id>.json` | `<quarantine>/<id>/triage.md` |

The id of a scan in place is derived from the unit and its tree digest, so scanning an
unchanged unit again rewrites the same record and keeps its review history.
