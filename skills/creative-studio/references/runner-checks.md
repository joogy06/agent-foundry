# What the runner checks, and what each check proves

Read this when a run stops with an outcome you did not expect, when you need to know what a passing row
means before you rely on it, or when you change `scripts/`. `SKILL.md` has the steps; this file has the rules
behind the stops.

## Contents

- Repair rounds
- The claim check
- Rulings
- The capture
- The voice probe
- The verdict record
- Where the runner writes and reads
- What the runner checks about its own record

## Repair rounds

`plan` prints one line: the planned spawns, the spawns of the permitted retries, the repair rounds, and their
total in agent turns. That total is the ceiling.

A repair round is work the runner sends back to an agent outside the plan. Each is recorded in `run.json`
under `repairs` with its kind, and `studio.py repairs --run <run>` lists them.

| Kind | What happened | Who works again |
|---|---|---|
| `capture` | a variant did not capture clean | its maker |
| `recapture` | a piece that was captured clean (or a draft that was checked) is changed and captured or checked again, before or after the verdict is open | its maker, then a critic read where the verdict is open |
| `contract` | `distance` refused a direction contract | its maker |
| `record` | `verdict check` refused the record | the critic |
| `constraints` | `constraints.md` has no heading line `## Heading outline` with a list of headings straight under it | the constraints seat |
| `final-text` | the final text fails a blocking row and no seat is left to ask | whoever edits `final/` |
| `claim-check` | the claim-check seat is needed again in a phase where it already ran | the claim-check seat |

- A run has one repair round per variant: two, or three with the single maker of the first runs.
- A round is at most two agent turns: the agent sent back, and one read that judges again.
- At the cap nothing is sent back. The runner stops with exit 3 `to_user`, and the run record is saved.
- Only the user lifts that stop: `studio.py repairs --run <run> --allow N` (1 to 20 a call, 20 a run in all;
  `repairs_allow_out_of_range`, `repairs_allow_over_the_run_total`).
- `--allow` is refused with `repairs_allow_needs_a_terminal` unless stdin and stdout are both a terminal. The
  refusal prints the full command for the user to run themselves. An agent does not run it: it stops and
  passes that command on.
- This is a speed bump, not authentication. A program can give itself a terminal, and the runner cannot tell
  who typed. So every allowance is recorded with its time (`repairs.allowances` in `run.json`), `repairs`
  lists them, and the hand-over has a line with the rounds used, the extra rounds allowed and when.
- `--budget N` covers repair rounds too. They are cut to what is left of N after the spawns, to none if
  need be: a run planned at exactly its budget stops for the user at the first repair.
- Not counted: the winner's re-make, which resumes an agent the plan already counted. The line says so.

## The claim check

`scripts/studio_claims.py` lists sentences and matches figures. It does not understand a sentence.

**What it reads.** Everything a reader will see: the body, every value of the front block, each line of a
fenced block, everything after a fence that is never closed, the anchor of a `[LINK: anchor -> slot]`, the
text of a Markdown link, and the inside of any bracket that is not a short footnote mark (`[^1]`,
`[^note-2]`), a citation number or a task box. A leading pair of `---` lines is a front block only when every
line between them is `key: value`; otherwise it is body text. HTML comments are not read.

**What it lists.** A sentence, heading, list item, table row or code line that carries a figure, a model name
the pack does not hold, a comparison, a date or a statement tied to "now".

**What it matches by itself.** A literal match needs all of this:

- the sentence says a name of the pack, and some entry lists EVERY name it says (the two spellings of one
  product, or the two products a shared fact is written for);
- every figure and date in it is held by one of those entries, in the same unit and with the same sign;
- where its product has a second figure in the same unit, the figure stands under a word of its own
  condition and no word of the other's (`entry-condition`, below);
- its name is not carried on by a further word (`name-extended`, below);
- it makes no comparison and is not tied to "now";
- it does not bound, negate or round the figure (`never`, `up to`, `at least`, `about`, `under`, `not`).

**A second figure in the same unit.** A product often has two: `Widget draws 120 W at low load and 240 W at
full load`, in one entry or in two. `Widget draws 120 W at full load` uses one of them for the wrong
condition, and the characters match. So where the entries a statement rests on hold another figure in the
same unit, the runner looks at the words:

- The condition words of a figure are the words of its clause of the entry's `fact` that the other
  figure's clause does not hold (`low` against `full`). In an entry with several figures the words before
  the first of them are a lead-in all share, and belong to none.
- A figure is matched when its own clause of the statement holds a word of its condition and no word of
  the other figure's. `Widget draws 120 W at low load` is matched, alone or beside the other figure.
- Otherwise the statement waits for a ruling with `entry-condition`: the wrong condition, both figures
  swapped, a bare `Widget draws 120 W`, a table cell, a fact that states two figures in one clause
  (`304 x 137 x 61 mm`).

Write the fact so that each figure has words of its own beside it, and write a draft with those words.

**A minus.** The sign is part of the figure: `-5 C`, `−5 C` (U+2212), `–5 C` and `minus 5 C` are -5 C, which
only an entry that writes `"value": "-5"` holds. A hyphen inside a token is no minus: `ZX-4090`, the range
`5-10`, a date.

**Names.** The words of a pack name may be joined by a space, a hyphen or a slash, whichever the pack
wrote: the pack's `ZX-4090` is the draft's `ZX-4090`, `ZX 4090` and `ZX/4090`. A hyphen or slash joins
only with no space beside it, and an en or em dash never does.

- No other punctuation joins them: `Wi-Fi, 7 antennas` is not the name `Wi-Fi 7`, and its 7 is read as a
  figure. A name does not end inside a decimal (`Wi-Fi 7.1`), and a word of one letter keeps its case
  (`A-40` is not "a 40").
- A longer name of the pack is looked for first: `ZX 4090 Ti` is never taken for `ZX 4090` when the pack
  holds both, and a pack that holds only the longer name gives the shorter one nothing.
- A variant word (ti, super, pro, max, plus, ultra, mini, lite, xt, se, in any case, bracketed or
  emphasised too) or a token of letters and digits (`v2`, `X3D`) straight after a name carries the name
  on: `ZX-4090 Ti`, `ZX-4090 super`, `ZX-4090-Ti`, `ZX-4090 (Ti)`. Unless that is a name of the pack too,
  the statement waits for a ruling with `name-extended`. An ordinary word carries nothing on, capitalised
  or not: `ZX-4090 has`, `ZX-4090 VRAM`, `ZX-4090, which`, `ZX-4090 24 GB`. A variant word used as an
  ordinary one (`ZX-4090 Pro tip:`) is taken for a variant, and waits.

**Units.** A figure is matched with its unit. Two lists are known:

- a fixed list (`W`, `GB`, `dB`, `%`, `ms` and the like), each one run of letters;
- every unit the truth pack writes on any of its figures, read WHOLE and the longest first, whatever it is
  spelled with: `m3/h`, `m³/h` (the same unit), `speed settings`. Case and spacing are folded.

So `620 m3/h` is 620 m3/h and never 620 m, whichever of the two the pack writes. A unit of either list ends
where it ends: one that runs on into a digit, a superscript, or a `/` and a letter is another unit (`m3/h`,
`m/s`, `m²` and `m3/hour` are not `m`). A word neither list holds is not a unit, and the number stands bare:
it matches only an entry that writes the figure with no unit.

**Which entries a statement may rest on.** Only the entries whose `names` list every name of the pack the
statement says. That one rule covers a sentence and a table row alike:

- A statement that says one product rests on that product's entries, and on an entry that names that
  product beside others (a shared fact) for that entry's own figures.
- A statement that says two products rests only on the entries that name both. `Fan A makes 38 dB and
  Fan B makes 29 dB` is therefore never matched from one fan's entry and the other's: it waits for a ruling
  (`several-names`), with the figures the right way round as well as swapped.
- An entry that names two products never lends one product's other entries to the other.
- An entry with NO name supports no statement by itself, in a row or in a sentence. A fact two products
  share is written as one entry that names both; the pack's author says so, never the absence of a field.
  A nameless entry can still be named in a ruling.
- Write every spelling of a product on each of its entries: a sentence that uses two spellings is matched
  only against the entries that list both.

**Table rows.** Each row under the header is one listed statement; its figures are read cell by cell and
matched by the rule above. It is supported when every figure matches; one figure no such entry holds leaves
it unsupported. A row that names no product waits for a ruling like a sentence does.

- A cell that is a bare number takes the unit of its column header only when the header is a plain label
  for that unit: it carries exactly one unit the pack uses (`Speed settings`, `Noise (dB)`), no other
  header of the table carries the same unit, and the header holds no figure, date, name, comparison,
  bound, negation or rounding word. A header with no unit of the pack, or with two, gives none and the
  number stays bare.
- A header that carries a unit and is not plain sends the row to a ruling (`column-condition`). `Lowest
  speed (dB)` beside `Top speed (dB)` is the case: the runner cannot tell which condition a figure stands
  under, so it does not match `52 | 29` against a product that has both figures.
- A bound, a negation or a rounding word in a column header (`Never above (dB)`, `Up to`, `At least`)
  counts for every figure in that column, whether the cell has a unit of its own or not: the row is
  unsupported with `qualifier`, as the same words would make a sentence.
- The header row is read like any other row, and every figure in it is listed: a rating, a count or a year
  written into a header is a statement a reader sees. One thing there is a label and no figure: the number
  of headers that only count their columns (`Speed 1 | Speed 2 | Speed 3`: the same words, the numbers
  running on by one, two cells at least, no product named).
- What a row match does not check: for a cell that carries its own unit, the condition its column header
  states (`29 dB` under `Top speed`) is not read, exactly as a condition in a sentence is not.

Everything else waits for a ruling and is unsupported until one is taken. A bare number from 1900 to 2099 is
a date only after a date word (`in`, `since`, `during`, `from`, `until`, `by`, `before`, `after`) or beside a
month, and never when a unit follows it: `scores 2024 points` and `costs £2025` are figures.

**What it does not list.** A figure written in words; a technical statement with no number, comparison or
date; a sentence that only names a product of the pack. The critic reads for those, and so does the user.

**Placeholders after the verdict.** A finish-pass brief says a labelled placeholder stays exactly as
written: it is never removed, reworded or replaced by a sentence saying the fact is not given. `handover`
compares the labelled placeholders of the final text with those of the winner's last checked draft (its
latest `claim-list.json`), by their words. Each one the final text lacks is listed in the hand-over under
`Removed by a later seat`, and `handover` prints their count. It is a report and blocks nothing: the user
looks the fact up.

**What a match proves.** `figure found in pack` in the hand-over means the characters matched under that
name. It is not a judgement of the sentence. `ruling` means the claim-check seat, a model, ruled it
supported by the entries it named. Neither is a person's check against the source.

**The outline.** `outline-met` reads the FIRST list straight under the heading line `## Heading outline` of
`constraints.md`; the section's number may stand before the words (`## 3. Heading outline`).

- A line straight under an item that is no item itself and is not set in is the rest of that item (a
  wrapped line) and is joined to it. A line set in under an item is a note; an item set in by two columns
  or more is a sub-item. Neither names a heading.
- The list ends at a heading, a rule line, or text after a blank line that is not set in. A list after
  other text, and a list under a sub-heading of the section, are notes and name no heading of the piece.
- The outline is never cut short in silence. An item whose indent differs from the list's by one column,
  or that is set in less than the list, cannot be placed: there is no outline, and `claims` stops with
  `constraints_outline_missing`.
- Where the heading line stands twice, the first one with a list straight under it counts.
- Text or a sub-heading where the list belongs is no outline: `claims` stops with
  `constraints_outline_missing` and the constraints seat is sent back. The runner does not guess which
  later list was meant.
- The constraints brief gives the seat the heading line and says the list holds only the headings.

## Rulings

- Rulings count only in a run whose plan has the claim-check seat. In light mode the file is not read.
- The runner asks: `claims` writes `briefs/claim-check.md` with the statements nobody was asked about yet
  and stops with `claims_need_rulings`.
- The seat writes `claims/rulings.json`. The next `claims` (or `handover`) takes it: the rulings on the
  statements that were asked about go into `run.json`, the rest are dropped, and the file is moved to
  `claims/rulings.taken-N.json`.
- A ruling names the entries it rests on: several in `entries` (a list of ids), or one in `entry`. A
  comparison rests on two. It counts only when it says `supported`, names at least one entry, and EVERY
  entry it names is in the pack: one id the pack does not hold takes the whole ruling down. The hand-over
  lists every entry of a ruling with where it comes from.
- What the seat is told (`briefs/claim-check.md`): a comparison is supported when it follows from the
  figures of the entries named, like against like, and says nothing stronger (29 dB against 38 dB at the
  same speed supports "quieter at its lowest speed", not "the quietest fan" or "much quieter"); a
  preference or a fit with no fact of its own is supported when the comparison it rests on follows from
  named entries; one fact the entries do not hold makes the whole statement unsupported; unsure is
  unsupported.
- What this rests on: the seat is a model. The runner checks that the ids exist and that the ruling is for
  a statement it asked about; it does not check that the comparison follows.
- A rulings file that is there when the runner has asked for nothing is refused
  (`rulings_file_nobody_asked_for`). Remove it; it suppresses nothing.
- A file that is not JSON or not shaped like rulings is refused by name (`rulings_unreadable`,
  `rulings_malformed`): `entry` that is not one id, `entries` that is not a list of ids. The seat writes it
  again.
- A ruling belongs to one sentence. Its id is a hash of the sentence with only case and spacing folded,
  so a ruling on `5 C` never carries to `-5 C`.
- The id of a table row is a hash of the row AND of the header cells it stands under. `Fan | 29 | 52` under
  `Low speed | High speed` and under `High speed | Low speed` are two statements: a ruling on one does not
  carry to the other, and the row is asked about again when a header above it changes.
- A statement the seat left out stays unsupported and is not asked about again.
- A re-make round starts with no rulings.

## The capture

- The probe walks the document, every open shadow root in it (nested ones too) and every frame of the
  page, and takes the worst value it finds.
- `contrast-text` is `not_run` when the probe reached no text element. `body-size` is `not_run` when it
  measured no running body text. Both are `not_run` when a frame of the page went unmeasured. `not_run`
  on a blocking row keeps the variant from winning. The warnings `text-not-measured-at-<width>`,
  `body-text-not-measured-at-<width>` and `frame-not-measured-at-<width>` say which.
- A paragraph's size is the size of the text a reader sees in it, not of the element that holds it: the
  probe measures the visible text runs inside each paragraph, descendants included, and takes the smallest
  size that MORE than a fifth of the paragraph's characters are set in or under. So
  `<p style="font-size:16px"><span style="font-size:8px">…</span></p>` is 8 px and fails, and so does a
  paragraph cut into many small runs; one small phrase, a few footnote marks or a line of fine print in
  a paragraph fails nothing. No tag is left out: a paragraph set whole in `small` or `sub` is measured.
- `body-size` is measured on the paragraph-like runs of the page. A page that has text and no such run
  (headings, links, short list items) is measured on its other text instead: outside navigation, header,
  footer, tables, forms and buttons where there is any, else on all of it. The warning
  `body-size-from-other-text-at-<width>` says so. The row then fails only when text below the threshold was
  found, and is `not_run` only when no text was reached at all.
- It cannot read a closed shadow root, text drawn in an image, an `<svg>` or a `<canvas>`. A page whose
  words are all there is blocked. Words in an `<svg>` or a `<canvas>` beside readable text go unmeasured: the
  critic has the tiles.
- A closed shadow root that holds text beside readable text is reported and not measured: each one counts in
  the advisory row `contrast-unmeasured`, which the critic reads, with the warning
  `closed-shadow-root-not-measured-at-<width>`. The other rows are those of the text that was reached.
- Text over a raster image is counted in the advisory row `contrast-unmeasured`, as before.

### No browser outlives a capture

- When a capture ends, however it ends, the wrapper kills node and the process tree of the browser it
  started (found by that capture's own temporary profile directory) and removes the profile. A page that
  never finishes ends as `gap: timeout` with nothing left running.
- A wrapper stopped by SIGTERM or SIGHUP (an outer `timeout`, a closed shell) does the same before it
  exits with 128 + the signal. It writes no evidence file: a stopped capture claims nothing.
- A wrapper killed outright (SIGKILL) runs nothing. node watches for that: the wrapper holds node's stdin
  open for as long as it lives, and node kills the browser, removes the profile and exits when that stdin
  ends or its parent process changes.
- Chrome is started on a pipe, not a socket, so a Chrome whose node was killed too exits by itself.
- One capture is limited to 120 s. `studio.py capture` runs the variants one after another: at worst
  3 x (120 s + 5 s for the reap) = 375 s for three variants, inside one 600 s tool call.

## The voice probe

For every written draft, `claims` calls `human-voice-writing/scripts/pattern_probe.py` and files
`pattern-report.json` beside the claim list. The report lists places (line, heading, paragraph) and the
category of a machine-writing pattern seen there.

- No value of it enters a floor row, the evidence set or the verdict record, and its exit code is not read.
- A probe that is missing, slow or broken gives `not_run` with the reason, and the run goes on unchanged.
- English only: another language is recorded as `not_run: language`.
- It is never a score. Do not rank drafts by it, report a count from it, or have a draft edited until it is
  empty: `human-voice-writing` forbids optimising a text against a detector.

## The verdict record

- A variant is eligible when its LATEST capture passes every blocking row. A variant that passed first and
  fails after a re-capture cannot win as it stands; it needs a further repair and a passing re-capture.
- Once the verdict is open, EVERY capture attempt of a variant is its latest capture, clean or not. One
  that timed out or failed goes into the record as a re-capture with its rows `not_run` (with no row at
  all when it left no evidence file), so the variant is not eligible, and a verdict that was already
  accepted is open again: `handover` stops with `verdict_not_accepted` until the piece is captured clean
  and judged. The hand-over's variant table says `did not run clean` beside such a capture.
- **The verdict is of the piece that was captured.** Every capture and every claim check files one hash
  over the variant's directory (every file, by path and bytes; a link as the link it is), taken before the
  piece is read. `verdict open`, `verdict check` and `handover` refuse with
  `variant_changed_since_capture <variant>` when a file of a variant was changed, added or removed since
  its latest capture: for the winner, and for a loser too, since a borrow card is cut from its source.
  A variant directory that holds a symbolic link is not captured or claim-checked at all
  (`variant_holds_a_link`): what a link points at can change with the directory unchanged.
  It uses no repair round and changes nothing. The answer is `capture --variant` (or `claims --variant`),
  which is a re-capture the critic judges; putting the file back as it was also answers it.
- **Two floor rows are the text critic's**, as one `tells` entry per variant with the row id as its `axis`
  (`scripts/studio_verdict.py`, `CRITIC_ROWS`): `first-screen` where the profile asks for it, and
  `unlisted-statements` in a run with a truth pack. The second exists because the claim check lists by
  pattern: a statement of fact with no figure, date or comparison in it is on no list, and the critic is
  the only reader of the whole draft. A variant with no single entry for a row is refused
  (`first_screen_row_missing`, `unlisted_statements_row_missing`), and so is a winner whose entry does not
  hold (`winner_fails_first_screen`, `winner_states_an_unlisted_fact`). It is a model's reading of the
  draft it judged, not a measurement, and nobody reads the final text that way: the hand-over says both.
- When NO variant is eligible, the only record taken is `no_award` with `all_fail_blocking`. A winner named
  there is refused with `no_award_required`, marked `selected_for_repair` or not. The run then has its one
  re-make round.
- `selected_for_repair` with no re-capture of that winner is refused with `repair_no_recapture`. Where
  another variant is eligible, that refusal is how a critic's request to repair a failing pick is carried
  out: the orchestrator sends the variant back to its maker, has it captured or checked again, and the
  critic reads again. The runner repairs nothing by itself. It uses two repair rounds (the refused record
  is one, the re-capture another), and the critic brief says so, so that a critic weighs the request.
- `repair` is filled only once a re-capture of the winner exists: its LATEST number, `rejudged` and
  `confirmed` true.
- Every critic brief has a section the runner writes, "Which outcome the checker takes": it says which
  variants pass their blocking rows as the rows stand (worked out from the same rows the brief prints),
  gives these rules line by line, and prints the critic part of the record in its exact shape, once with a
  winner and once with no award. The shapes carry stand-ins and no variant id. Both critic references
  (`references/text-critic.md`, `design-critique/references/critic-brief.md`) state the same rule.
- The same section prints one borrow card of each kind (`fragment`, `system`, `move`) in the exact shape
  the checker takes for the run's kind of work. For written work a `move` has `evidence_region.text` (a
  heading and a paragraph number) and nothing else; for a page it has `evidence_region.evidence` (a tile
  path the brief prints) and may add `area`. `anchor.in` is listed with the values that kind of work allows.
- A re-capture is complete when it carries every blocking row of the first capture, by row id and width.
- A winner that has any re-capture was changed after the verdict opened. It is accepted only when `repair`
  names its LATEST re-capture with `rejudged` and `confirmed` true, whatever its first capture said
  (`winner_not_rejudged`). The runner also keeps the hash of `read-1.json` as it stood at that re-capture: a
  record that is still that file was not written after it, and is refused with the same code. A re-capture
  of a losing variant asks nothing.
- What this rests on: the critic's own statement in its record. It stops a judgement made before a repair
  from being accepted for the repaired piece; it does not prove that a critic looked.
- A re-make round starts with the piece's rivalry `unchecked`: `verdict open` stops with `distance_missing`
  until `distance` has compared the new contracts.
- With a winner, at least one rubric row favours it, and `favours` names a variant of the record.
- `verdict open` stops with `distance_missing` until `distance` has compared the contracts.
- In a baseline run nothing about the record is read, written or said before the user's ranking. A
  re-make round sets the earlier ranking aside and asks again.
- A read file that is not JSON or is missing is refused by name (`not_json`, `unreadable`).
- **A round's verdict is opened once.** `verdict open` asked again, while the verdict is open, held,
  refused or accepted, writes nothing and resets nothing, and says so: the read files stay as the critics
  filled them, the re-captures stay in the record, and a verdict that was shown stays shown, so
  `verdict rank` after it is still refused (`ranking_after_verdict_shown`). A new judgement of a changed
  piece is a re-capture (a repair round); a new round is `remake`.
- **Every read is a whole record.** Only the PICK of a later read is joined to read 1, but each later read
  is checked alone as well, as the record it would be if every read had picked as it did: a file that
  holds a pick and nothing judged, or that breaks a rule of its own, is refused with the code and
  `read-N` (`missing_field read-2`, `winner_ineligible read-2`). One thing is read 1's by design: after a
  re-capture only read 1 is written again, so where a later read names the same winner, what read 1 says
  of the repair (`selected_for_repair`, `repair`) stands for it too.
- **A borrow card is named the way its kind of work can be cut**, and says `why`: for a page a `fragment`
  has `locator.markup` and a `move` has `evidence_region.evidence` (never `text`); for written work both
  hold `text` and nothing else. The other form is refused (`borrow_locator`, `borrow_move`), where it used
  to pass and give a card with nothing beside it.

## Where the runner writes and reads

- Every file of a run is written whole: a new temporary file beside it, then a rename. The temporary file
  is created new and never through a link (`O_EXCL`, `O_NOFOLLOW`); a link left under its name is removed.
- A path spelled inside the run whose directory, with links followed, is outside it is refused before
  anything is written: `path_leaves_the_run <the first directory of the path>`. A linked `evidence/`,
  `borrow-cards/` or `final/` is the case.
- A draft the claim check would read through a link, in a variant or in `final/`, is refused:
  `draft_leaves_its_directory`. The rendered path has the same rule in `scripts/studio_capture.py`
  (`index.html` and the output directory).
- The other files an agent writes and the runner reads are read through no link either: a read file,
  `constraints.md`, `claims/rulings.json` (`read_through_a_link <the first part of the path>`). A linked
  `claims/` would otherwise have its rulings read, and renamed, outside the run.
- This closes the ways a link put inside a run sent the runner's own writes and reads elsewhere. It is not
  a sandbox: an agent of the run writes with the same rights as the runner.

## What the runner checks about its own record

Nothing of a run is out of an agent's reach: the run directory is one directory, and every agent of the run
writes there with the runner's own rights. The runner keeps its own copy of what it measured and decided,
apart from the files a seat is told to write, and compares before it relies on either.

| Thing | Where the runner keeps it | What happens to an edit of the seat's copy |
|---|---|---|
| The skeleton: floor rows, read orders, evidence references | `run.json` (`skeleton`) | `verdicts/skeleton.json` is put back; a read file whose runner part differs is refused (`runner_part_altered`) |
| An evidence file | its hash, in `run.json` when it is filed | `evidence_changed_since_filed`: it is not judged |
| Rulings | `run.json` (`rulings.accepted`) | a later file is refused unless the runner asked |
| The truth pack, the doctrine files | their hashes, taken at `plan` | `truth_pack_changed_since_plan`, `doctrine_changed_since_plan` |

`run.json` is itself checked against files beside it, by `verdict check` and `handover` (and wherever the
value is used):

| In `run.json` | Checked against | Refusal |
|---|---|---|
| The floor rows of the skeleton, first capture and re-captures | the evidence file of the capture the verdict was opened on and of every capture filed after it; for written work each evidence file against its own `claim-list.json`, with the counts taken from the listed claims | `skeleton_differs_from_evidence <variant>`, `evidence_differs_from_claim_list <variant>` |
| The repair cap and `allowed_by_user` | no more than the planned rounds (`plan.json`) plus the rounds `gated.jsonl` shows as allowed | `repairs_cap_altered` |
| The repair rounds used | no fewer than the `repair-round` lines of `gated.jsonl` | `repairs_used_altered` |
| The accepted rulings | each one is a ruling `gated.jsonl` shows as taken | `rulings_altered` |
| A capture entry | capture n of a variant is under `evidence/<that variant>/c<n>`, and carries the hash of the piece | `capture_entry_altered <variant>` |

`gated.jsonl` is the runner's log of what only it decides. A line is appended, never rewritten, by four
steps and no other: `repairs --allow` (from a terminal), the runner taking a rulings file it asked for, the
start of a re-make round (its rulings end), and the save of a repair round. None of these refusals uses a
repair round: a record that differs is not a critic's mistake to correct.

- The three decisions are logged BEFORE `run.json` is saved, a repair round AFTER. So a runner that dies
  between the two leaves a line with nothing behind it, never a state with no line, and such a line stops
  nothing: `run.json` may say less than the log, never more.
- A run with the mark `record_checks` in `run.json` (written at `plan`) and no log has been allowed nothing
  and has taken no ruling. A cap or a ruling in it is refused.
- A run without the mark was started by an earlier runner. It is not held to a log, and none is written
  for it later either (an allowance, a ruling and a re-make round go into `run.json` only): its cap and
  rulings are taken as `run.json` has them, a capture entry may lack the hash, and the hand-over says in
  bold that they were not checked. Removing the mark makes a run look like that; the hand-over line is
  what shows it.

**What stays a convention.** All of it is in the run directory, and every agent of a run can write there.
These checks catch an edit of one file, and of two or three that were not all made to agree. They do not
stop an agent that rewrites `run.json`, the evidence files, their hashes and `gated.jsonl` consistently.
A line appended to `gated.jsonl` by an agent reads like one of the runner's. The briefs tell each seat
which files are its own; the runner does not enforce it, and the hand-over says so.
