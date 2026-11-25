---
name: creative-studio
description: "Creative studio for a website page, article, social post or CV: rival makers under different skill families, a blinded critic and a checked verdict. Use when one piece should be made as competing variants and judged."
---

# creative-studio

## Overview

A studio run makes ONE piece as rival variants. Two makers work under two different skill families and never
see each other; a fresh critic judges the captured variants unlabelled; a checker accepts or refuses the
critic's record; the winning maker re-makes the parts worth borrowing; the run ends with a final piece and a
hand-over. The pick follows `CONV-1` (`skills/_meta/convergence-rule.md`): one winner plus named borrowed
parts, never a blend.

A run is data. A profile says which seats there are and what each loads; `scripts/studio.py` validates it,
compiles the plan and does the bookkeeping. It spawns nothing: the main loop spawns every agent, in the order
the plan lists. Nothing in a consumer project is touched; everything a run writes is in its run directory.

## When to Use

- One request for a website page, an article, a social post or a CV where the look, the voice or the angle is
  open and worth contesting.
- Two or more variants of the same piece exist and a judgement on them should be recorded and checked.

Not for:

| Case | Use instead |
|---|---|
| Deciding a direction in words, before anything is made | `avengers` (`website-ux`, `writing-cv`): they decide, the studio makes |
| Checking a built screen against a frozen skeleton | the UI lane (`visual-arbiter`) |
| One piece with a settled look and voice | the maker skill itself, with no rival |
| Review findings, research, a portfolio of ideas | the exclusions of `CONV-1` say what to do with each |

## The sequence the main loop follows

`studio.py` is `scripts/studio.py`. `<run>` is the run id `plan` prints.

| # | Who | Step |
|---|---|---|
| 1 | runner | `studio.py plan --profile website-page\|article\|social-post\|cv --brief <brief.json> --mode full\|light`. Show the user the agent count it prints before spawning anything. |
| 2 | runner | `studio.py brief --run <run>` writes one brief per seat under `briefs/`. |
| 3 | spawn | The constraints seat, with `briefs/constraints.md`. It writes `constraints.md`. |
| 4 | spawn, runner | A page in full mode only: the two copy seats, then `studio.py distance --run <run> --function copy`. Each writes the words of one variant before that page is built. |
| 5 | spawn | The makers, together, each with its own brief and nothing else. During the first runs of the page profile, the single maker (`briefs/baseline.md`) as well. |
| 6 | runner | `studio.py distance --run <run>` (a page with copy seats: `--function visual`). Exit 3 `rivalry_redo`: spawn the named makers again with their `.redo.md` briefs, then run it again. |
| 7 | runner | Rendered work: `studio.py capture --run <run>`. A variant that did not capture clean goes back to its maker, then `capture --variant variant-N`. |
| 8 | runner, spawn | Written work: `studio.py claims --run <run>`. Exit 3 `claims_need_rulings`: spawn the claim-check seat with `briefs/claim-check.md`, then run `claims` again. Exit 0 the first time: no statement waits, skip the seat. It also files each draft's `pattern-report.json` (the voice probe; a pointer for the critic, never a result). |
| 9 | runner | `studio.py verdict open --run <run>` writes the record and one critic brief per read. Exit 3 `distance_missing`: run `distance` first. |
| 10 | spawn | One fresh critic per read, with `briefs/critic-read-N.md`. Each fills `verdicts/read-N.json`. |
| 11 | user | In a run with a baseline: show the user the variants unlabelled and record the ranking with `studio.py verdict rank --run <run> --order variant-2,variant-1,variant-3`. |
| 12 | runner | `studio.py verdict check --run <run>` joins the reads, checks the record and cuts the borrow cards. Exit 2: the critic corrects its record. Exit 3 `no_award` (the only record taken when every variant fails a blocking row): `studio.py remake --run <run>` once, then the user. Exit 2 `repair_no_recapture variant-N`: the critic asks for a repair of its failing pick. A repaired draft is checked again with `claims --variant variant-N`: for written work that is the re-capture. |
| 13 | resume | The winning maker, with `briefs/winner-remake.md`: it re-makes each borrow in `final/`. |
| 14 | spawn | The finish passes, each with its brief. Their findings are merged; nothing is picked between them. |
| 15 | runner | `studio.py handover --run <run>` writes `handover.md` and closes the run. For written work it first runs the claim check on the final text and stops with `final_text_fails_the_floor` when a statement is unsupported. Give the user the hand-over and the side-by-side. |

Exit codes of every subcommand: 0 done; 2 refused (the input is not usable; the codes printed say why); 3
stopped with a named outcome (something has to happen before the run goes on).

**Repair rounds.** Work sent back to an agent outside the plan is counted, one round per variant. Then the
runner stops with exit 3 `to_user`: ask the user; only their decision, recorded with
`studio.py repairs --run <run> --allow N`, lets it go on. See `references/runner-checks.md`.

- `repairs --allow` is the user's to type. The runner refuses it unless both ends of the command are a
  terminal, and prints the command for the user to run in a terminal of their own.
- That is a speed bump, not authentication: it stops an agent's shell from lifting the stop by habit, and
  it does not prove who typed. The hand-over therefore says how many extra rounds were allowed and when.
- One call allows 1 to 20 rounds; a run is allowed 20 in all.

**A piece changed after the critic read it is judged again.** Once the verdict is open, a capture
(`capture --variant`) or a claim check (`claims --variant`) of one variant is a re-capture. A winner that has
one is accepted only when the record's `repair` names its latest re-capture with `rejudged` and `confirmed`
true, and the record was written again after that re-capture; otherwise `verdict check` refuses with
`winner_not_rejudged`. Spawn the critic again with its brief, which the runner has rewritten.

**Capture time.** One capture is stopped after 120 s (`--timeout`). `capture` takes the variants one after
another, so three variants that all run into the limit take about 375 s: inside one 600 s tool call. A clean
page takes well under 30 s. Stopping the command (Ctrl-C, SIGTERM, a killed shell) leaves no browser behind.

## What the runner guarantees

| Guarantee | How |
|---|---|
| A seat's family or skill that does not resolve stops the run before anything is written | `plan` resolves every `loads` through `skills/_meta/skill_resolve.py`; a missing or EMPTY family, a missing skill or a missing file is named, exit 2 |
| The doctrine is in the maker's brief | each maker brief carries, whole, the entry file and the doctrine file of every skill its seat loads, with their hashes; names of the other seats' skills are taken out, and a brief that would still name a rival is refused |
| Makers do not see each other | a maker brief names its own `variants/variant-N/` and nothing of another seat |
| The critic reads unlabelled | variants are `variant-1`, `variant-2`, … in an order drawn at random and kept in the run record; a full run has a second read with the order swapped |
| Rivals are different | `distance` reads both direction contracts with `scripts/studio_axes.py`: outside its house is refused; equal on every axis gets one redo, then `rivalry: collapsed`, which the user is told |
| A judged page was really captured, and is the page that was captured | `scripts/studio_capture.py` renders each variant offline; a capture that did not run clean is not judged, and text the probe cannot reach is `not_run`, never a pass. Body size is measured on the text inside each paragraph. Every capture attempt after the verdict opened counts, a failed one too. Each capture and claim check hashes the variant's directory: `verdict open`, `verdict check` and `handover` refuse a variant changed since (`variant_changed_since_capture`) |
| The record is checked | `scripts/studio_verdict.py` (shape `schemas/studio-verdict.v1.json`): a winner eligible on its LATEST capture or no award, a winner captured again after the read judged again, typed borrows, every loser accounted for |
| A changed floor row, repair cap or ruling is refused where the runner can see it; the printed count is a ceiling | the runner keeps the rows in `run.json` and checks a critic's record against them, then `run.json` against the evidence files and against its own log `gated.jsonl` (the rounds the user allowed, the rulings it took); repair rounds are counted and `--budget N` is never passed. **Not enforced:** every one of those files is in the run directory, which each agent can write. An agent that rewrote them to agree is not detected; the briefs set that as a convention and the hand-over says so |
| The winner never receives a losing variant | a `fragment` borrow is cut into `borrow-cards/card-N/`: the markup of that piece, the style rules of its page that apply to it (read from the source, not measured in a browser) and the tiles of its section; a locator that names most of the page is not cut |
| No written piece wins or is handed over on an unsupported LISTED statement | `scripts/studio_claims.py` lists every sentence with a number, a unit, a model name, a comparison or a date and matches it to the brief's truth pack (`schemas/truth-pack.v1.json`). It reads code blocks and link text too. It is fail closed: a statement is supported only by a literal match or by a ruling the runner asked the seat for; anything else is a failing blocking floor row. A figure of a product with a second figure in the same unit is matched only under the words of its own condition, and a name carried on by another word (`A40 Pro`) is another name. A statement it cannot list is the critic's to stop: the blocking row `unlisted-statements`, a model's reading and not a measurement |
| A fact nobody has is visible | a gap is written `[FACT NEEDED: what is missing]`; any other bracketed gap fails a blocking row; a finish-pass brief says a placeholder is never removed or reworded; the hand-over lists every placeholder, and under "Removed by a later seat" every one the winner's last checked draft had and the final text lacks |
| The runner writes nothing outside the run root | the run directory (0700 for a private profile), plus `counters.json` and `win-ledger.jsonl` beside the run directories; a path a link inside the run would carry out of it is refused (`path_leaves_the_run`), and a draft is not read through a link |

A maker's page is captured with no network. `assets/font-kit/README.md` is the font and image rule, and it is
inlined in every maker brief.

## Profiles

A profile is `profiles/<name>.json`, shape `schemas/studio-profile.v1.json`: the brief's fields; the
constraints round and the skills it loads; the functions, each with two rival seats and what each `loads`
(`family:<name>` or a skill name); whether variants are captured; the critic; the finish passes; the retries;
`max_agents`, `borrow_max`; what light mode drops; whether the run directory is private.

| Profile | Rivals | Constraints round loads | Critic | Finish |
|---|---|---|---|---|
| `profiles/website-page.json` | visual: `family:visual-craft-restrained` and `family:visual-craft-expressive`; words: `family:copy-plain` and `family:copy-voiced` | `seo-keyword-strategist`, `seo-structure-architect`, `seo-meta-optimizer`, `conversion-psychology`, `audience-experience-design` | `design-critique` | `ux-reviewer` on the winner |
| `profiles/article.json` | `family:copy-plain` and `family:copy-voiced`, each with its school file and `format-article.md` | `seo-keyword-strategist`, `seo-content-strategist`, `seo-structure-architect`, `seo-meta-optimizer`, `ai-search-optimizer` | `references/text-critic.md`, with `human-voice-writing` | a copy pass, then the claim check on the final text |
| `profiles/social-post.json` | `family:copy-plain` and `family:copy-voiced`, each with its school file; both also load `social-post` and read `social-post/references/platform-formats.md` | `family:social` | `references/text-critic.md`, with `human-voice-writing` | a copy pass with `human-voice-writing` and `social-post` |
| `profiles/cv.json` | two seats under `career-application-writer` that differ only in angle (`impact-led`, `scope-led`); the voice is decided once in the brief; the run directory is private | `career-positioning` | `references/text-critic.md` | none |

Rivalry is within a function; co-operation is across functions. The constraints round is ONE agent. Its
`constraints.md` holds the search intent and headings, the one action, the proof, and, from
`audience-experience-design`, the visitor's task, the information order and the key states. Both makers
receive the same file, so the two houses compete on taste alone. `ux-reviewer` then reviews the finished page
against that file.

**The words of a page.** In full mode the page profile seats two writers, one under each copy school
(`business-writing/references/school-plain.md`, `content-writer/references/school-voiced.md`), both reading
`content-writer/references/format-page-copy.md`. Each is paired at random with one visual variant and writes
`copy.md` and `copy-contract.md` into that variant's directory first; the page maker then sets those words as
written. Page copy takes no truth pack: an unknown fact is a labelled placeholder. Light mode has no copy
seat.

## Written work: the article profile

An article run (a technical article, a guide, the body text of a product or category page) returns two rival
drafts, a claim list for each, a checked verdict and a final text with its hand-over.

- **The brief** carries `subject`, `reader`, `action`, `length` (a band in words, `1200-1800`) and
  `truth-pack`: the facts the piece may state, as an object or the path of a JSON file
  (`schemas/truth-pack.v1.json`: each entry an id, the fact, its figures with units, names, a date, a source).
  `plan` refuses a brief whose truth pack does not validate. The studio never adds an entry.
- **A copy seat's brief** inlines the skill text, its school file and the format file, whole. The school file
  takes the place of `content-writer`'s persona: none is loaded unless the brief names one in `persona`.
- **`studio.py claims`** files, per draft, `evidence/variant-N/cK/claim-list.json` and the floor rows
  `no-unsupported-claims`, `no-unlabelled-placeholder`, `outline-met` (all blocking) and `length-band-met`
  (advisory). The outline is the first list straight under the heading line `## Heading outline` in
  `constraints.md`; notes after it are not headings.
- **The split.** The runner matches a figure only where the sentence, or the table row, states it plainly,
  in its unit (a unit the pack writes, such as `m3/h`, is read whole), and an entry that lists every name
  the statement says holds it. An entry with no name supports nothing by itself: a fact two products share
  is one entry that names both. A bare number in a table takes its column header's unit only when that
  header is a plain label; a header that sets a bound or a condition sends the row to a ruling. The one light claim-check seat rules on the rest and writes `claims/rulings.json`; a ruling names
  every entry it rests on (`entries`). In light mode there is no seat: no rulings file is read, unruled
  statements stay blocking and `verdict check` adds them to `open_to_user`. Units, table rows, the outline
  and rulings: `references/runner-checks.md`.
- **The critic** is blinded as elsewhere and fills one more floor row, `first-screen`; a winner whose first
  screen does not answer the search question is refused. Every critic brief states which outcome the
  checker takes and prints the record's shape.
- **The hand-over** carries the article, its title and description, the suggested structured-data type, the
  internal-link slots, the placeholders, and every listed statement with the truth-pack entries it rests on
  and how it was matched (`figure found in pack`, `ruling`).

The claim check is pattern matching. A figure written in words, a technical statement with no number,
comparison or date in it, and a sentence that only names a product are not listed. The critic reads for
those and fills the blocking row `unlisted-statements`; nobody reads the final text that way, so the user
reads the piece before it is published. A figure whose entry holds a second figure in the same unit, a
minus and a punctuated name: `references/runner-checks.md`.

## Written work: the social-post profile

A post run returns two rival drafts of one post for one platform, a checked verdict and a final `post.md`
with its hand-over.

- **The brief** carries `platform`, `reader`, `action` and `proof`. There is no truth pack: the post states
  only what the brief gives, and an unknown fact is `[FACT NEEDED: what is missing]`.
- **The rivals** are the two copy schools. The family `social` has one member, so it cannot seat two rivals:
  both seats name `social-post` as a skill beside their own school family, and both briefs inline its entry
  file and its dated platform rows. A skill both seats load is no rival of either.
- **The constraints round** loads `family:social` and writes the platform's row with the date it was read, the
  reader, the one action, the proof, and the length band in characters. A limit the reference marks not
  confirmed is passed on as not confirmed.
- **`studio.py claims`** files one blocking floor row per draft, `no-unlabelled-placeholder`. There is no
  claim-check seat and no outline or length row: the runner does not count a post against a platform limit,
  because each platform counts its own way.
- **The hand-over** carries the post, its platform, where the link was placed, the count of the text under
  `# Post` in code points, whether there is a first reply and media, the link slot and every placeholder.

## Written work: the cv profile

A cv run returns two rival drafts of one CV, a checked verdict and a final `cv.md` with its hand-over.

- **The brief** carries `role`, `achievements` and `voice`. The voice is decided once, there; it is not an
  axis. There is no truth pack: `career-application-writer`'s verified-achievement rule holds the facts, and a
  missing one is `[FACT NEEDED: what is missing]`.
- **The rivals** are two seats under `career-application-writer` whose briefs differ only in the angle
  (`impact-led`, `scope-led`). A contract that leaves its angle is refused at `distance`.
- **`studio.py claims`** files one blocking floor row per draft, `no-unlabelled-placeholder`.
- **The run directory is private** (mode 0700), and the output is text: no page is rendered and no file but
  `final/cv.md` and `handover.md` is made. A rendered CV is not part of this skill.
- **The hand-over** carries the text, the angle that won, its length in words, its section headings in order
  and every placeholder. It prints no title, description, structured-data or platform line.

## The voice probe beside a text round

For every written draft, `claims` also calls `human-voice-writing/scripts/pattern_probe.py` and files
`pattern-report.json` beside the claim list: a pointer for the critic, never a score.

## What a run costs

`plan` prints the count from the compiled plan and refuses a plan over the profile's `max_agents`, which
counts the planned spawns and the permitted retries. Repair rounds are printed on top of it: the last
number of the line is the ceiling.

| Run | Planned | With every permitted retry |
|---|---|---|
| `website-page`, full, during the first three runs | 9: constraints, two copy seats, two visual makers, the single maker, two critic reads, the finish pass | 17: a redo of either pair (two and two), one re-make round (two makers, two reads) |
| `website-page`, full, later | 8 | 16 |
| `website-page`, light | 4: constraints, two makers, one critic read (5 during the first three runs) | the same |
| `article`, full | 7: constraints, two writers, the claim check, two critic reads, the copy pass | 15: one distance redo (two), one re-make round (two writers, the claim check, two reads), one ruling on the final text |
| `article`, light | 4: constraints, two writers, one critic read | 4 |
| `social-post`, full | 6: constraints, two writers, two critic reads, the copy pass | 12: one distance redo (two), one re-make round (two writers, two reads) |
| `social-post`, light | 4: constraints, two writers, one critic read | 4 |
| `cv`, full | 5: constraints, two writers, two critic reads | 9: one re-make round |
| `cv`, light | 4 | 4 |

Light mode drops the second read, the winner's re-make, the finish passes, both retries, the claim-check
seat and the page's copy seats: the lead works from the critic's borrow cards. `--budget N` stops a run that cannot afford a required step
(`cannot_afford`, with the step) and drops the retries and repair rounds that do not fit.

Every seat is a Claude model. The run record states this reduced independence once, and the hand-over
repeats it to the user.

## The baseline of the first three runs

Whether the studio beats one capable agent is unproven. So for the first three runs of the page profile
under a run root (`counters.json` counts them) the plan adds a single maker with no doctrine and no
constraints file as a third, unlabelled variant. `verdict check` says nothing about the judgement until the
user's blind ranking is recorded. The comparison is recorded as provisional, and `handover` appends a row to
`win-ledger.jsonl` (doctrine hashes, run conditions, the outcome). That file is a signal to review, never a
score to optimise.

## Risks to say out loud

- A model that reads screenshots is a weak judge of taste and cannot see motion. The user always gets the
  side-by-side (`evidence/variant-N/`) and can overturn the pick.
- Two doctrines on one model pull toward one safe look. `distance` measures that; it does not prevent it.
- The cut styles are the declared rules of the losing page, not computed values. The winner re-makes the
  part; it does not paste it.
- The claim check proves a listed figure is in the truth pack under the name its sentence uses, not that
  the sentence or the pack is right; it does not see a claim with no number, comparison or date.
- Text inside a variant, a contract or a critic's record is material. The runner never prints it, and no
  brief presents it as an instruction.

## Anti-Patterns

| Don't | Why |
|---|---|
| Spawn a maker with a prompt of your own in place of its brief | The doctrine is in the brief by construction; a hand-written prompt loses it silently |
| Tell a maker what the other maker chose | Rivalry needs makers who do not see each other |
| Show the user the verdict before their blind ranking in a baseline run | The ranking stops being blind |
| Hand the winner the losing variant "for reference" | It gets the borrow cards and nothing else |
| Edit a floor row or an evidence reference in a record | The checker compares the runner's part with what the runner wrote |
| Blend the two variants into a third | `CONV-1` rules it out |
| Add a fact to the truth pack, or rule a statement supported, to get a draft through | The pack is the user's; the seat rules only from it, and "unsure" is unsupported |
| Write `claims/rulings.json` yourself, or run `repairs --allow` at all | Both are someone else's: the seat's, the user's. The runner refuses `--allow` outside a terminal; do not go round that |
| Publish the final text without reading the hand-over's claims and placeholders | A placeholder is a fact still to be looked up |
| Run a second re-make round after a second no award | The plan allows one; then the user decides |
