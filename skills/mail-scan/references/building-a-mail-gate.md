# Building a mail gate on mail-scan

mail-scan is the protection half of a service that drafts replies to email. It reads no mailbox
and sends nothing. The other half, the **gate**, is yours: the one program that fetches a
message, calls the scanner, calls the drafting model, calls the draft check and places a draft
for a person to read and send. This reference is the contract between the two halves: what the
skill enforces, what it leaves to the gate, and the limits it states openly.

It describes; it holds no mailbox code. Every example uses invented data under `example.org`.

## Contents

1. The flow in one page
2. Rules for the gate you build
3. Enforced, or a convention
4. Calling the scanner (library and command)
5. The config
6. Calibration before you trust a provider
7. Overrides, and what the permission rules cover
8. Retention and privacy
9. Stated limits
10. Checklist before going live

## 1. The flow in one page

1. Fetch one raw message as bytes. Read its size first.
2. `scan` it. You get a record id, the verdict and reply decision as recorded, and the
   **effective** verdict and reply: the same after the overrides a person gave for this
   message. The library also returns the reply target, in memory, when a draft may be written.
   The command never prints it: a gate built on the command takes the target from its own
   parse of the From mailbox, or from its own mapping, and hands it to `check-draft` in a file;
   `check-draft` is what proves that it belongs to the sender of the scanned message.
3. If the effective reply is not `draft`, stop. Show the person the sheet; write no draft.
4. Give the drafting model ONE framed view and the knowledge pack. No tools.
5. `check-draft` the body and subject the model wrote. On a refusal, stop.
6. Fetch the message again, scan it again, and place the draft only if nothing changed and the
   effective reply is still `draft`.
7. A person reads the draft and sends it. The service never sends.

The view is text an unknown sender wrote, cleaned and framed. Only the drafting model reads it.
No agent with tools, and no operator's assistant, ever opens a file under `views/`.

## 2. Rules for the gate you build

Each rule below is the gate's to keep. The skill cannot keep them for you.

**The mailbox**

- **One process holds the credential.** The gate alone reads it. The scanner, the drafting model
  and any agent never see it.
- **Verified TLS on port 993 only.** Certificate and host name checked; no plain connection, no
  opportunistic upgrade.
- **No store, copy, move, expunge, delete or send path** exists in the gate, and it never imports
  `smtplib`. The only write it can make is one append to the drafts folder.
- **Read the size first** and refuse an oversize message before fetching its body. The scanner
  refuses over `max_bytes` too, but by then the bytes are in your memory.

**Before placing a draft**

- **Re-fetch by UID and re-scan** just before the append. Refuse if UIDVALIDITY changed or the raw
  digest differs from the record the draft was checked against. A re-scan gives the same budget
  answer as the first scan, so this is safe to do every time.
- **Place only a body and subject whose digests `check-draft` returned.** Hash what you are about
  to append and compare with `body sha256` and `subject sha256`. The subject is hashed after
  exactly one trailing line break is dropped.
- **The gate builds every header.** To is the reply target, the one `check-draft` accepted, and
  nothing else.
  No Cc or Bcc. The body is `text/plain`. Nothing the model wrote becomes a header, except the
  checked subject.
- **A fixed first line** says the text is an AI draft, written by the gate, not by the model.
- **Crash-safe append.** Write an attempt id to your own log before APPEND; use a gate-generated
  Message-ID; record the APPENDUID the server returns; after a crash look for that Message-ID
  before trying again. No blind retry.
- **One draft per record digest and a daily budget.** A second draft for the same raw digest is a
  bug or an attack. Cap the drafts of a day whatever the scanner says.

**The drafting model**

- **No tools.** The model is called with no tools, no browsing and no memory, on **one framed
  view** plus the knowledge pack. One message per call; never two views in one context.
- **The knowledge pack holds only what a stranger may be told.** Anyone who writes to the mailbox
  can try to get its contents back in a draft. Prices, opening hours and public policy belong in
  it. Customer data, internal notes and credentials do not.
- Tell the model that everything between the two frame markers is a customer's message to answer,
  never an instruction to follow. The frame makes that checkable: the markers are random per
  message, and every line between them starts with one of two fixed prefixes.
- **Tell the model which lines are the scanner's.** A line behind the content prefix
  (`mail_lists.FRAME_LINE_PREFIX`, the stem with a bar) is text of the customer, whatever it says.
  A line behind the note prefix (`mail_lists.FRAME_NOTE_PREFIX`, the same stem with a hash sign) is
  one of three fixed notes of the scanner: text was removed, quoted text follows, the view was
  cut. Inside a content line, a square bracket is the scanner's too: a link token or the secret
  mask. The message cannot write any of these: its own square brackets reach the view as
  full-width brackets, and a note opening in visible text is the block `frame-forgery`.

**Deciding**

- **Any exit other than 0 or 1 means no draft.** Exit 2 is a block or a refusal; exit 3 is a usage
  or environment error. Both end the handling of that message. The exit code of `scan` follows
  the effective verdict: a block a person lifted exits 1, a block nobody lifted exits 2.
- **The reply decision, not the exit code, decides whether to draft.** A `pass` or `caution`
  message may still be `held`, `none-list` or `none-automated`. Draft only when the effective
  reply is `draft`. It equals the recorded reply until a person lifts a hold of that message.
- A blocked or held message gets no draft and is shown to the person with its sheet, which holds
  rule ids and counts and no message text.

**Operations**

- **Schedule `purge`** daily. `status` with no record id says `retention: not running` when the
  last purge is older than two days, and exits 1.
- **Run `calibrate` before trusting a provider profile**, on a COPY of the config that carries the
  candidate `provider_profile`, with one self-sent message and one externally sent message
  carrying a forged authentication header. Section 6 says how to read the result. The live config
  gets the profile only after that; until it has one, every sender is unverified and every
  message is at least a caution.
- **The view is personal data sent to a model provider.** Records hold no message text, but the
  keyed hashes in them are pseudonymous, not anonymous. Section 8.
- **Call the library from the service.** Do not have an agent type the commands. A permission ask
  rule matches the text of a command, so an unattended agent that types a gated command simply
  waits for a person who is not there.

## 3. Enforced, or a convention

What holds when the gate runs as the same operating-system user as a coding agent, and what a
separate user (a one-time step as root) adds.

| Protection | Same user as the agent | Separate OS user (one-time root step) |
|---|---|---|
| The scanner has no network, send or delete path | enforced (import test) | enforced |
| A draft that fails the check is refused by `check-draft` | enforced when the gate calls it | same |
| The agent cannot override a block by itself | permission prompt plus the override log | enforced |
| The agent cannot read the mailbox credential | convention | enforced |
| No process reaches mail-submission ports | convention | enforced by a firewall rule (not an HTTPS API send) |
| The drafting model has no tools | the consumer's convention | same |

"Enforced (import test)" means a test and `doctor` read every script of the skill, and the
intake-scan modules it loads, and fail on an import of a network, mail-transport or process
module or a call that starts a process. The check is static: it reads the source. The secrets
catalog file of `secret-scanning` is outside it by design and named so in the output.

## 4. Calling the scanner (library and command)

### Library

Import by path, from the installed skill or from a checkout:

```python
import sys
sys.path.insert(0, "/path/to/skills/mail-scan/scripts")
import mail_scan

config = mail_scan.load_config("/srv/gate/mail-scan-config.json")
result = mail_scan.scan_bytes(raw_bytes, config)
if result.effective_reply == "draft":
    view_text = open(result.view_path, encoding="utf-8").read()   # the gate reads it, for the model only
    body, subject = draft_with_model(view_text)                     # yours; no tools
    checked = mail_scan.check_draft(result.record_id, body, subject, result.reply_target, config)
    if checked.accepted():
        place(body, subject, result.reply_target, checked.body_sha256, checked.subject_sha256)   # yours
```

- `scan_bytes(raw, config, state_root=None, now=None)` returns
  `ScanResult(record, view_path, sheet_path, reply_target, failure, effective_verdict, effective_reply)`
  with `.verdict`, `.reply` (both as recorded) and `.record_id`. `scan_file(path, ...)` reads a
  regular file first.
- `effective_verdict` and `effective_reply` are the recorded decision after the overrides given
  for this raw digest. A scan after a release still writes its record with the decision as it
  was made; nothing about an override is stored in a record.
- `check_draft(record_id, body, subject, reply_target, config, state_root=None)` returns
  `DraftResult(result, rule_hits, body_sha256, subject_sha256)`; `.accepted()` is the test.
- `effective(digest, state_root=None)` and `effective_record(record_id, state_root=None)` give the
  verdict and reply after overrides.
- `load_config(path)` and `read_config(dict)` validate a config. They raise `ConfigError(code, key)`.
  Bad input raises `InputError(code)`. Both happen before anything is read; after that a scan never
  raises: any failure inside it is a block record with the gap `scanner-error`.
- `failure` is `None`, `scanner-error` (a block record exists), `record-not-written` (not even
  that could be stored; `record` is `None`) or `key-missing` (the same, because the state root
  holds records and its key file is gone: the key is never made a second time, see section 8).
  Treat all three as no draft.
- One scan has 10 seconds for its parse, view and rules. When they are spent the record is a
  block with the gap `structure-over-bound` (detail `time`).
- The reply target lives in memory only. It is never stored and never printed, and it is `None`
  unless the effective reply is `draft`. Keep it for the draft check and the To header and
  nowhere else.
- When a record cannot be written after its view was, the view and the sheet are removed: a view
  with no verdict is text nobody judged.

### Command

The command word comes first and is written in full.

| Command | What it does | Exit |
|---|---|---|
| `scan --config C [--root R] FILE` | one verdict, one reply decision, one record | 0 pass, 1 caution, 2 block (the effective verdict) |
| `check-draft --config C --body-file B --subject-file S --reply-target-file T [--root R] RECORD` | accept or refuse a draft | 0 accept, 2 refuse |
| `override RECORD --kind K --reason TEXT [--root R]` | a person lifts one hold of one message | 0, or 2 with `refused: <word>` |
| `status [--root R] [RECORD]` | a record after overrides; with none, the retention report | 0; 1 when retention is not running; 2 with `refused: <word>` for a record that is unknown or cannot be read |
| `purge [--root R]` | delete by age, write `last-purge` | 0 |
| `calibrate --config C [--forged F] DIRECTORY` | counts over a folder of `.eml` files, in a temporary root | 0 |
| `doctor [--root R]` | check this host | 0 ok, 1 warnings, 2 a failed check |

- Exit 3 is a usage or environment error on every command: an unreadable or invalid config, an
  unreadable input, a command line that was not understood, an interrupt.
- `scan` prints the record id, the verdict, the reply decision, `reply if released`, the holds,
  `effective verdict`, `effective reply` and the rule and gap counts. It prints no path and no
  reply target: the view is `views/<record-id>.txt` and the sheet
  `sheets/<record-id>.txt` under the state root you supplied.
- `check-draft` takes the body, the subject and the reply target from files, never from the
  command line; one of the three may be `-` for standard input. Exactly one trailing line break
  (LF or CRLF) is dropped from the subject and from the target. A draft file over 1,000,000 bytes
  is exit 3.
- Output is fixed words of ours, numbers, record ids and the two digests. Nothing taken from a
  message, a header, an address, a host, a file name or an argument value is ever printed, on
  errors and bad arguments included.

## 5. The config

One JSON file, schema `mail-scan-config.v1`. An unknown key is refused.

| Key | Meaning |
|---|---|
| `own_addresses` | required list (may be empty); mail from one of them is `none-automated`; they may appear in a draft |
| `provider_profile` | optional: `authserv_id` and `validated_on` (a real date); absent means every sender is unverified |
| `allowed_hosts` | bare host names a draft may hold; each needs a dot; `www.` in front is the same host |
| `approved_phones` | numbers a draft may hold; one entry per spelling whose DIGITS differ (national and international) |
| `reply_to_map` | From address to the address a reply goes to |
| `knowledge_pack` | optional path to a UTF-8 text file; give an absolute path |
| `canary` | optional string that must never appear in a draft; put it in the model's instructions |
| `max_bytes` | 1 to 25,000,000; default 2,000,000 |

A relative `knowledge_pack` is read from the working directory, and a pack that cannot be read
refuses every draft. Example, with invented data:

```json
{
  "schema": "mail-scan-config.v1",
  "own_addresses": ["desk@example.org"],
  "allowed_hosts": ["www.example.org"],
  "approved_phones": ["0161 496 0123", "+44 161 496 0123"],
  "reply_to_map": {},
  "knowledge_pack": "/srv/gate/knowledge-pack.txt",
  "max_bytes": 2000000
}
```

## 6. Calibration before you trust a provider

Calibration on your real mail is your step. It has NOT been run by this skill's authors on any
real mailbox; the scanner was built and tested on messages constructed for the tests.

1. Export a sample of real mail as `.eml` files into one folder (only regular `.eml` files
   directly inside it are read, at most 5,000).
2. Send yourself one message from inside the provider, and one from OUTSIDE it that carries a
   forged `Authentication-Results` header naming the provider's id with `dmarc=pass`.
3. Copy the config and add to the COPY the candidate `provider_profile`: the authserv-id the
   provider writes (read it from the top `Authentication-Results` header of the self-sent message)
   and today's date as `validated_on`. Run `calibrate --config <the copy> --forged <the outside
   message> <folder>`. Without a profile in the config it cannot answer the questions below: it
   prints `profile: absent` and counts no DMARC failure. It scans into a temporary root that is
   deleted afterwards and prints counts only: verdicts, replies, rule and gap counts,
   `header-ambiguous` hits by header name, sender results, and the ids of authentication headers
   as keyed hashes. Each message is judged alone; the reply budget is not counted.
4. Read the `--forged` facts:
   - `first header under the profile id: no` while headers are present means the provider does not
     put its own header on top. **Do not use a profile for this provider.**
   - `sender verified` on the forged message means the same: its only pass is the forged header.
   - Two headers under the profile id with the first one failing is the safe case: the provider
     wrote its own header above the forged one, and only the first is ever read.
5. Look at `header-ambiguous` by header name. Some providers keep a sender-supplied Return-Path
   beside their own; such mail would be blocked, and you must know before going live.
6. Look at what ordinary mail gets. If many ordinary messages are `block` or `held`, stop and
   report it; do not loosen a list on your own. The mail the profile will HOLD is counted on two
   lines under `rules`: `caution dmarc-fail: messages N` (the provider reported a DMARC failure, or
   a result word such as `reject` or `quarantine`) and `caution auth-header-unreadable: messages N`
   (the provider's own header could not be read). Expect some of it to be ordinary mail (section 9,
   "What a profile costs").
7. Only then add `provider_profile` to the live config, with the id and the date as `validated_on`.

A provider whose own header carries NO authserv-id (some large providers write it that way:
`calibrate` then counts it as `unreadable-header`), or that splits its spf, dkim and dmarc results
over several headers, gives no DMARC hold: only the first header is ever read, and one with no id
is no evidence. Under such a provider a profile does not stop forged mail from being drafted to.

The hashes are keyed with a key that is deleted with the temporary root; they compare within one
run only. Run `doctor` on the host as well: it re-checks 13 parser behaviours that were recorded
on Python 3.13, the reused pieces, the import guard and the modes of the state root.

## 7. Overrides, and what the permission rules cover

A person, never an agent, lifts a hold: `override RECORD --kind block|list|budget|held --reason TEXT`.
It is bound to the raw digest of that one message, is refused for automated mail, for a kind the
record does not hold, for an empty reason and for a message that was not judged (a
`scanner-error` record: `refused: override-not-judged`), and never expires. A `block` override
also records which block rules and gaps the record had, and lifts a later scan of the same bytes
only when that scan is blocked for nothing else: a block the person never saw stays a block. The
override table is in `rules-and-gaps.md`, section 4.

The settings template of the harness carries five rules for the default state root
`~/.foundry/mail-scan`:

- ask before a shell command whose text holds the override command (`mailscan.py override`);
- ask before a shell command whose text holds the program name and, anywhere after it, the word
  `override`: this covers the module form, `python3 -m mailscan override ...`, and a doubled
  space or quotes around the script name;
- ask before any file edit under the state root: one `Edit` rule, because Claude Code matches path
  rules only in the `Edit` form, which covers `Write` too (a `Write(path)` rule is ignored, with a
  startup warning);
- deny `Read` of `views/**` and of `key` under the state root.

What that is, said plainly:

1. The ask rule covers the command as it is normally typed.
2. A process of the same OS user that calls the library (`mail_state.add_override`), or spells
   the command line another way (a variable for the script, a copy of the script under another
   name, `python3 -c` with the library), can write an override without the prompt. The rules bind
   the agent's own tools, not the operating system.
3. **The rules bind Claude Code and nothing else.** They are entries of Claude Code's settings
   file. Codex and agy receive the skill without them: a Codex or agy session on the same host
   meets no prompt at all. Where this reference says "the agent cannot override a block by itself:
   permission prompt plus the override log", read "a Claude Code agent"; for any other agent only
   the log and a separate OS user stand.
4. The override log is the audit trail. Every line is sealed and carries the record id, the raw
   digest, the kind, the OS user and the time; the reason is stored as length and hash only. A line
   with no good seal lifts nothing and is counted by `status` and `doctor`.
5. A state root moved with `--root` or `$FOUNDRY_MAILSCAN_ROOT` is not covered by the rules.
   `doctor` warns for both. Keep the default root unless the service runs as its own user.
6. The seal guards against an edit, not against a process that can read the key file. That is why
   the template denies reading it.

This is the row "permission prompt plus the override log" of the table in section 3. A separate
OS user for the service turns it into "enforced".

## 8. Retention and privacy

- State root: `records/`, `views/`, `sheets/`, `overrides.jsonl`, `key`, `last-purge`. Directories
  are 0700 and files 0600; every write is atomic. One of the three directories that is a symbolic
  link is refused (`root-unusable`), so records and views never land outside the root.
- **Back up `key` with the root.** A root that holds records and has lost its key is the error
  `key-missing`: every scan is a block with no record until the key is restored or the root is
  emptied. A new key is never made in silence, because it would restart every sender's budget and
  leave every record and override unreadable.
- A record holds the raw digest, a keyed hash of the From address, the verdict, the reply decision,
  rule ids, gap names, counts and opaque inventories. It never holds a subject, body text, an
  address, a host name or a file name. Records and override lines are sealed; an edited record
  cannot be read.
- A view holds message text. It is kept seven days, like its sheet. A record is kept 90 days.
  `purge` deletes by those ages and keeps the override log whole.
- The keyed hash lets the scanner count mail per sender without storing the address. It is
  pseudonymous: whoever holds the key can test an address against it. Treat the state root as
  personal data.
- The view is sent to your model provider. Say so in your privacy notice, and choose a provider
  and terms that fit.

## 9. Stated limits

The scanner is a fixed set of rules. It is honest about what it does not catch.

**A polite, plain message passes.** A mail that simply asks the model, in visible text, to
confirm a refund or promise a date breaks no rule. There is no phrase matching on visible text,
on purpose: a phrase list is trivially rewritten. **The person who reads and sends the draft is
the control.**

**Hidden text.** The view does not show only what a reader sees: it **catches the common hiding
tricks**. It does not imitate a browser. A strict reader judges one element at a time; it
accepts a small, exactly specified style language, cut down to what person-written mail uses
(written out in `rules-and-gaps.md`, section 5), and shows an element only when its style can be
proven harmless. Everything outside the language is uncertain: the text is removed, the view
says so in a fixed line, and a large removal holds the reply. No declaration rescues another: an
element is judged over the worst of its `style` attribute and of every `<style>` rule whose
selector could match it. A style block that is not of the language, a link to a style sheet and
a page that allows a dark colour scheme put the whole part in doubt, and nothing of it is shown.

What this costs. Mail a person writes in Outlook, Gmail, Apple Mail, Thunderbird, Yahoo or
Outlook on the web keeps its text, and so does text pasted into such mail from Google Docs,
Google Sheets and Apple Notes. **A marketing or notification template usually loses text, often
all of it, and its reply is held**: when what was removed as uncertain is at least 30% of a part
and at least 40 characters, the caution `uncertain-share` holds it (a draft is never written
from half a message), and over 200 characters `uncertain-removal` does. Text dropped because
its element is outside the element list (not judged uncertain by style) does not count toward
that share: a pasted Google Sheets table that Gmail wraps in its own element may be lost whole
while the reply is still drafted (from the last review; not confirmed on a real Gmail message). That is accepted: such
mail is normally list mail and gets no draft anyway. One ordinary shape of such mail is lost
with it: a button whose white text is set inline while a rule of the block gives links the
colour of the button. Right-to-left mail keeps its text when it wraps and sets no width (Hebrew
and Arabic as a person writes them); a table with a width in such mail is removed. The one
exception to "no declaration rescues another" is the hanging indent of a list typed in Outlook:
a negative text-indent with a left margin at least as wide in the SAME style attribute is
visible, unless a rule sets a margin, a padding or a text-indent with `!important`, or the
element sets a background.

What is still SHOWN to the model although a reader may not see it. These are LAYOUT: a reader
that judges one element at a time cannot prove a layout harmless, so they are stated, not fixed.

- text covered by another element (also by generated content of a `::before` or `::after`
  rule);
- text drawn in a font with blank glyphs, where no `@font-face` of the message draws it (a font
  installed on the reader's machine);
- text pushed far to the right or down, where it can be scrolled to: by what stands before it (a
  tall image, hundreds of line breaks, a long run of no-break spaces), and by paddings, word
  spacing and letter spacing summed;
- one unbreakable run of characters that is wider than a box anchored on the right, or than a
  cell that clips: the part past the box;
- the reversed order of `<bdo dir="rtl">`: the view shows the characters in source order;
- found by the last review and not fixed (the user closed the fix rounds there): the hanging
  indent can place text on the element's own wide left border, drawn in the text's colour; the
  small negative left margin accepted on Word tables adds up across many tables set side by side
  (`display:inline-block`); Word's raised or lowered text inside a cell that clips can be clipped
  away; and right-to-left text joined by no-break spaces is one unbreakable run, so a whole
  sentence can be hidden that way with no CSS at all;
- text only one mail program hides in a way no rule here reads. Chrome, with and without a
  doctype, is what the reader was compared with (fuzzes of 10,000 and of 5,000 documents in both
  directions); Outlook's Word engine, the sanitiser of a web mailer and iOS Mail (where
  `-webkit-text-size-adjust` beyond its accepted values may shrink text) were not run;
- a reader in dark mode sees a page the message did not ask for; what that hides is not judged
  (a page that ASKS for a dark scheme is not shown at all);
- whether a very slow message is read in time depends on the load of the host: under load it may
  be a block (`structure-over-bound`, detail `time`) where an idle host judges it. That fails safe.

**The provider's signature.** A sender is verified only when the provider's own header reports
a pass for the From domain itself. Mail signed by a parent, a subdomain or a sibling of the From
domain is unverified unless the provider reports `dmarc=pass` for the From domain. Where the
provider reports no DMARC verdict (`dmarc=none`: the domain has no record), an exact DKIM or SPF
match verifies. A provider that writes `header.i` and no `header.d` for DKIM (Gmail) verifies
through its dmarc or spf result only. A provider whose header carries no authserv-id, or that
splits its results over several headers, gives no DMARC hold (section 6).

**What a profile costs.** Under a provider profile, mail the provider reports as failing DMARC is
held, and some of it is ordinary: mail that reached the mailbox through an alias forward when the
sender does not sign; a mailing list that does not rewrite From; a web form that sends with the
visitor's address as From. A person releases such mail one message at a time. The reply always
goes to the From mailbox (or its `reply_to_map` entry), never to a Reply-To header: a web form
that sends from its own address with the visitor in Reply-To gets a draft addressed to the form.

**Attachments with a file name given twice.** A Content-Disposition that gives `filename` in the
plain form and in the `filename*=` form side by side is `header-ambiguous`, a block, like any
parameter given twice: some mailers write both, and their mail with attachments is blocked
until a person releases it.

**Ordinary shapes the draft check still refuses.** A number of 9 to 15 digits that is neither
approved nor a whole number of the inbound message or the pack; `mailto:` links and the other
listed schemes written against text (`tel:` before a number that is not approved, any `ms-...:`
and `search-ms:`); under `draft-white-space`: two spaces in a row (aligned columns), a tab, a space
at the start of a line (an indented or nested list) or at its end (the signature line `-- `), a
blank line at the start, more than one line break at the end, a no-break space anywhere but in
French punctuation or between digits (so not before a euro or percent sign, after `M.`, after
the number abbreviation or the numero sign, in `z. B.` or after a one-letter Polish word), both kinds of
no-break space in one text, a no-break space before one mark and a plain space before another,
the ideographic space of Japanese and Chinese, and line endings of both kinds; under
`draft-mixed-script`: a word that mixes Latin with Cyrillic or Greek letters (a Latin stem with a
Russian ending; a unit of up to three Latin letters and one micro, Omega or Delta is accepted) and
a mark of a script on a letter of another; `127.1` as a number; text such as `a<b` or
`[1] (below)` (read as markup); a missing space after a full stop when the next word is a
top-level domain (`done.It`, `ok.In`, `thanks.Now`: the list is the whole IANA root zone, about
1,400 names, many of them ordinary words); a number in the path of an allowed host that is not
approved; a zero-width joiner that joins no emoji. Expect an occasional refused draft and show
the rule id to the person. Tell the drafting model to write plain, single-spaced text with no
indent and no signature line.

**What the draft check does not catch.** The person who sends the draft is the control for these:

- a host or a number spelled in words; a dot written as a word or in brackets;
- digits separated by a slash, a tilde, a comma, a colon, an underscore or letters, in the text
  or in the path of an allowed host (`www.example.org/4929/1234/5678/9012`);
- what a writer can vary in plain sight: the choice of words, of punctuation and of capital
  letters, a blank line or none between paragraphs, and one choice of white space nobody sees:
  no-break spaces or plain ones before French punctuation and in grouped digits, the same
  throughout one text (one bit a text). White space is narrowed to that one bit, not closed; the
  rest cannot be closed by any rule;
- look-alike letters of scripts other than Latin, Cyrillic and Greek, and a whole word written
  in the look-alike script; compatibility letters such as the Kelvin sign inside a Latin word, and
  the choice between the micro or ohm sign and the Greek letter in a unit word (one bit each);
- a scheme nobody listed, written without slashes (`zoommtg:join`); a host written as one
  number or with a percent sign in an allowed path; short numeric hosts other than `127.1`;
- the marks of a script (Thai, Devanagari and the rest) stacked beyond what the script writes,
  on a letter of that script: only the general combining marks are capped;
- a dot drawn with a character outside the listed look-alikes;
- a number of any length that the inbound message itself holds, so a message with a forged sender
  can have its own number echoed back to that sender;
- a host under a top-level domain newer than the built-in snapshot of the IANA list (its date is
  `DRAFT_TLDS_SNAPSHOT_DATE`; `doctor` warns when it is over a year old); a host glued to a
  following letter; a host with white space after its dot (the shape of a sentence boundary),
  except before `com`, `org`, `io`, `biz` and `xyz`; a host written as one number (`0x...`);
- another host named inside the path of an allowed host;
- letters, as opposed to digits, in the path or fragment of an allowed host, up to its 80
  characters.

**Structure.** A message that is only headers, or one with an mbox `From ` line on top, is read as
an ordinary message. A message with a carriage return alone in a header block is blocked whole.

**Budget.** The fourth draft-eligible message of one sender in seven days is held. Every earlier
message that got a draft counts, whatever its sender result; blocked and held mail does not.
Under a provider profile a reported DMARC failure holds the reply, so such mail is not drafted
to and does not count. The budget is a brake on loops, not an abuse control:

- WITHOUT a provider profile no DMARC failure is ever read: mail forged under a victim's
  address is drafted to like any other, three times a week, and those three hold the victim's
  next mail. Set a profile. With a profile, the same holds for a provider whose header has no
  authserv-id or splits its results (section 6);
- a provider that reports `dmarc=fail` for a small business with a broken record holds that
  business's mail until a person releases it; so are the forwarded, list and web-form mails of
  "What a profile costs";

- clean mail forged under a victim's address still counts when the sender is unverified (no
  provider profile, or no result for that domain), so three such mails hold the victim's next one;
- plus-addressing or any change of the From address is another sender and evades the count;
- for messages FIRST scanned in the same second, which of them is the fourth is fixed by their
  record ids and may differ from what their first scans said;
- a message scanned again more than two weeks after its last record is placed at the time of
  the new scan.

**Cost.** Each scan opens the records of the last fourteen days (chosen by the time in their
names) to place the message in the budget, so the work grows with two weeks of mail, not with
everything the root keeps. One scan has 10 seconds: a message the scanner cannot read in that time is a
block (`structure-over-bound`, detail `time`). Two megabytes of ordinary markup take one to
eight seconds on the build host.

**A process of the same OS user** can call the library, read the key and write the override log
(section 7). Only a separate OS user for the service closes that.

**Python.** Parser behaviour depends on the Python patch level. The tests pin it on 3.13 and
`doctor` re-checks on your host; a warning from `doctor` on another minor version is to be read,
not ignored.

**Permission rules** match command text and the file tools of a Claude Code agent only; Codex
and agy sessions are not bound by them (section 7).

## 10. Checklist before going live

- [ ] `doctor` exits 0 on the service host, from the installed copy, with the default state root.
- [ ] `calibrate` was run on real mail with a forged message; the profile was added only after.
- [ ] The gate has no send, delete or move path and never imports a mail-submission module.
- [ ] The drafting model has no tools and sees one framed view per call.
- [ ] The knowledge pack holds nothing a stranger may not be told; its path is absolute.
- [ ] The gate drafts only on effective reply `draft`, and stops on any exit other than 0 or 1.
- [ ] The gate re-fetches, re-scans and compares digests before the append; the append is crash-safe.
- [ ] `purge` is scheduled and `status` says `retention: running`.
- [ ] The settings rules are installed; overrides are given by a person at the prompt. No agent
      other than Claude Code (which alone the rules bind) runs as the service's OS user.
- [ ] A person reads every draft before it is sent.
