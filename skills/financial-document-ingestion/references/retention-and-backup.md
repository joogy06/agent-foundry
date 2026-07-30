# Retention and backup — the records are the evidence

The document store is not a convenience. It is the evidence behind every filed return, and it has to
survive for years. **Losing it does not lose files; it loses the ability to defend a filed figure.**

## 1. How long

| Record | Keep |
|---|---|
| Company records supporting the CT return | **6 years** from the end of the accounting period |
| VAT records | **6 years** |
| Payroll records | **3 years** minimum; longer in practice, and pension records longer still |
| Statutory registers and filed accounts | **Permanently** |

Longer if an enquiry is open, if the period was late-filed, or if the records relate to an asset
still held — **a capital allowance claim needs the original purchase invoice for as long as the
asset is on the register**, which can far exceed six years.

**When in doubt, keep it.** Storage is cheap; reconstructing a destroyed record is not possible.

## 2. What "backed up" actually means

A copy is not a backup until it has been **restored**. The rule that survives contact with reality:

> **3 copies · 2 media · 1 off-site · and at least one restore actually tested.**

- **3 copies** — the working store plus two others.
- **2 media/locations** — one drive failing must not take both.
- **1 off-site** — fire, theft and flood take everything in one building. A cloud sync counts.
- **Tested** — an untested backup is a belief. Restore a real document and open it.

**Sync is not backup.** A synced folder faithfully replicates a deletion or a ransomware encryption
to every copy within minutes. **Keep versioned or immutable history** so yesterday's state is
recoverable, and prefer a provider whose versioning cannot be turned off by the same credentials the
app uses.

## 3. What must be backed up

Everything needed to reconstruct and defend the position:

- `documents/` — the originals, in their original format
- `index.json` — **without it the store is a folder of unlabelled PDFs**, since the index carries the
  hash, period, type and `posted_ref` linkage
- The books themselves (accounting file, database, or exported ledger)
- `business-profile.json` and the obligation tracker
- Filed returns and their submission receipts
- The rates reference in force when each return was prepared

**That last one is easy to miss and matters.** Defending a two-year-old computation means showing
which rates were applied and why — the reference as it stood then, not as it stands now.

## 4. Verification, not faith

- **Hash on arrival, verify on restore.** The index already holds `sha256` per document; a restore
  is proved by re-hashing, not by the files appearing.
- **Check the count**, not just that the folder exists.
- **Test a real restore at least annually** — pick a random document from three years ago and open
  it. Year-end is a natural moment.
- **Watch for silent corruption.** Old media and cloud sync both bit-rot quietly; the hash is what
  detects it.

## 5. Failure modes worth naming

- **Sync-as-backup** — a deletion propagates everywhere before anyone notices.
- **Backing up documents but not the index** — the store becomes unusable.
- **Credentials with delete rights on the backup**, so the same compromise takes both.
- **Never testing a restore**, discovering at an enquiry that the archive was empty for two years.
- **Retention by folder size** — pruning "old" files that are inside the statutory window.
- **Assuming the accounting SaaS is the archive.** A subscription lapse, a closed account or a
  provider change can end access. **Export and hold your own copy.**
- **Original formats replaced by derived ones** — a CSV you generated is a convenience copy; the PDF
  invoice is the evidence.

## 6. Practical shape for a small company

Working store on the machine that does the work · a versioned cloud copy with history retained
beyond the deletion window · a periodic offline or separately-credentialed copy the app cannot reach
· an annual restore test recorded with its date and what was checked.

**Record when the restore test was done.** An untested backup and a tested one look identical right
up to the moment it matters.
