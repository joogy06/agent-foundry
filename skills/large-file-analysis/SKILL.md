---
name: large-file-analysis
description: Use when analyzing large text-based files (CSV, TXT, logs, JSON lines, TSV) that exceed or approach the AI context window — chunked reading strategies, position tracking (line numbers, byte offsets), temp file accumulation for intermediate findings, multi-pass analysis patterns, CSV header preservation across chunks, progressive summarization, grep-first-then-read targeting, and final aggregation before output. Essential for token-limited AI agents (Copilot, Claude Code, Cursor, Windsurf) working with files over 2000 lines.
---

# Large File Analysis — Working Within Token Limits

Methodology for AI agents to analyze text files that don't fit in the context window. Applies to any token-limited agent (Claude Code, GitHub Copilot, Cursor, Windsurf, etc.) processing CSV, TXT, logs, JSONL, TSV, or any line-based data.

<HARD-RULE>
Never attempt to read an entire large file at once. Always check file size first, then plan a chunking strategy. Reading a 50,000-line file into context wastes tokens and may truncate critical data silently.
</HARD-RULE>

<HARD-RULE>
Always write intermediate findings to a temp file — never rely on context memory across chunks. Context compaction will erase earlier chunk findings. The temp file is your persistent memory.
</HARD-RULE>

<HARD-RULE>
Never present findings without a final verification pass. After accumulating results in temp files, re-read the temp file and validate before presenting to the user. Accumulated errors compound across chunks.
</HARD-RULE>

---

## Phase 0: Reconnaissance — Before Reading Anything

Always start with reconnaissance. Never read the file content before understanding its shape.

```bash
# Step 1: File size and line count
wc -l /path/to/file.csv                    # line count
ls -lh /path/to/file.csv                   # human-readable size
file /path/to/file.csv                     # encoding, type detection

# Step 2: Structure sample (first and last lines)
head -5 /path/to/file.csv                  # headers + first rows
tail -5 /path/to/file.csv                  # last rows (check for truncation)

# Step 3: Column count and delimiter detection (CSV/TSV)
head -1 /path/to/file.csv | tr ',' '\n' | wc -l     # comma-delimited columns
head -1 /path/to/file.tsv | tr '\t' '\n' | wc -l    # tab-delimited columns

# Step 4: Unique value sampling (understand data distribution)
cut -d',' -f3 /path/to/file.csv | sort | uniq -c | sort -rn | head -20

# Step 5: Check for patterns that enable targeted reads
grep -c "ERROR" /path/to/file.log          # count matches before reading
grep -n "keyword" /path/to/file.csv | head -20  # line numbers of matches
```

### Decision Matrix: Which Strategy to Use

| File Size | Lines | Strategy |
|---|---|---|
| < 500 lines | Small | Read entire file directly — no chunking needed |
| 500-2000 lines | Medium | Read with offset/limit in 2-3 chunks |
| 2000-10000 lines | Large | Chunked reading with temp file accumulation |
| 10000-100000 lines | Very large | Grep-first targeting + chunked analysis of relevant sections |
| 100000+ lines | Massive | Bash/awk pre-processing to extract, then analyze the extract |

---

## Temp File Setup

Before creating any working files, create a unique session directory:

```bash
ANALYSIS_WORK=$(mktemp -d /tmp/analysis-XXXXXXXXXX)
# e.g., /tmp/analysis-a1b2c3d4e5
```

All temp files go inside `$ANALYSIS_WORK/`. This prevents collisions when multiple analyses run in parallel.

---

## Strategy 1: Chunked Sequential Reading

For files where you need to analyze every line (auditing, validation, transformation).

### Pattern: Read → Process → Accumulate → Next Chunk

```
Chunk Plan for a 15,000-line file (chunk size: 500 lines):
  Chunk  1: lines     1-500   (includes header)
  Chunk  2: lines   501-1000
  Chunk  3: lines  1001-1500
  ...
  Chunk 30: lines 14501-15000

For each chunk:
  1. Read(file, offset=start, limit=500)
  2. Analyze against the task criteria
  3. Append findings to ${ANALYSIS_WORK}/findings.md
  4. Move to next chunk
```

### Implementation (Tool-Based AI Agents)

```
# Step 1: Recon
Bash: wc -l /path/to/data.csv → 15,234 lines
Read: /path/to/data.csv, limit=1 → capture header row

# Step 2: Initialize temp file with header context
Write: ${ANALYSIS_WORK}/findings.md
  ---
  File: /path/to/data.csv
  Total lines: 15,234
  Header: id,name,email,status,created_at
  Task: Find all rows where status is "suspended" and created_at is before 2024-01-01
  ---
  ## Findings

# Step 3: Process chunk by chunk
Read: /path/to/data.csv, offset=1, limit=500
→ analyze, append matches to ${ANALYSIS_WORK}/findings.md

Read: /path/to/data.csv, offset=501, limit=500
→ analyze, append matches to ${ANALYSIS_WORK}/findings.md

# ... continue for all chunks ...

# Step 4: Read temp file, summarize, present to user
Read: ${ANALYSIS_WORK}/findings.md
→ format final answer
```

### Choosing Chunk Size

| Agent Context Window | Recommended Chunk Size | Rationale |
|---|---|---|
| 4K tokens (Copilot) | 50-100 lines | Leaves room for instructions + output |
| 8K tokens | 100-200 lines | Moderate breathing room |
| 32K tokens | 300-500 lines | Comfortable for CSV analysis |
| 128K+ tokens | 500-1000 lines | Can handle wide CSVs |
| 1M tokens (Claude Opus) | 1000-2000 lines | Default Read limit is appropriate |

**Adjust for line width**: A CSV with 50 columns needs smaller chunks than a log with short lines.

---

## Strategy 2: Grep-First Targeting

For files where you're looking for specific patterns, errors, or values. **Far more efficient than sequential reading.**

### Pattern: Search → Locate → Read Surrounding Context

```bash
# Step 1: Find all relevant line numbers
grep -n "ERROR\|CRITICAL\|FATAL" /path/to/app.log > ${ANALYSIS_WORK}/error-lines.txt
wc -l ${ANALYSIS_WORK}/error-lines.txt    # how many matches?

# Step 2: Read only the relevant sections with context
grep -n -B2 -A5 "ERROR" /path/to/app.log > /tmp/error-context.txt

# Step 3: If the grep output itself is large, chunk IT
wc -l /tmp/error-context.txt
# Then read /tmp/error-context.txt in chunks
```

### For CSV: Column-Value Targeting

```bash
# Find rows where column 5 (status) equals "failed"
awk -F',' '$5 == "failed"' /path/to/data.csv > /tmp/failed-rows.csv

# Count before reading
wc -l /tmp/failed-rows.csv

# Add header back
head -1 /path/to/data.csv > /tmp/failed-with-header.csv
cat /tmp/failed-rows.csv >> /tmp/failed-with-header.csv

# Now analyze /tmp/failed-with-header.csv (likely small enough to read directly)
```

### For Logs: Time-Window Targeting

```bash
# Extract logs from a specific time window
grep "2024-03-15T1[4-6]:" /path/to/app.log > /tmp/afternoon-logs.txt

# Or use sed for range extraction
sed -n '/2024-03-15T14:00/,/2024-03-15T17:00/p' /path/to/app.log > /tmp/window.txt
```

---

## Strategy 3: Multi-Pass Analysis

For complex analysis requiring different types of information from the same file.

### Pattern: Multiple Targeted Passes

```
Pass 1 — Structure Discovery:
  Read first 20 lines → understand schema, headers, format
  Read last 10 lines → check completeness, trailing data
  Write structure summary to /tmp/pass1-structure.md

Pass 2 — Statistical Overview:
  Bash: awk/sort/uniq commands for distributions
  Bash: wc, cut, sort for column analysis
  Write stats to /tmp/pass2-stats.md

Pass 3 — Targeted Deep Analysis:
  Grep for anomalies identified in Pass 2
  Read surrounding context for each anomaly
  Write detailed findings to /tmp/pass3-anomalies.md

Pass 4 — Aggregation & Output:
  Read all three temp files
  Synthesize into final report
  Present to user
```

### Example: CSV Data Quality Audit

```bash
# Pass 1: Structure
head -1 data.csv                                    # headers
wc -l data.csv                                      # row count
awk -F',' '{print NF}' data.csv | sort | uniq -c    # column count consistency

# Pass 2: Completeness (find empty fields)
awk -F',' '{for(i=1;i<=NF;i++) if($i=="") print NR":"i}' data.csv | head -50 > /tmp/empty-fields.txt

# Pass 3: Duplicates
cut -d',' -f1 data.csv | sort | uniq -d > /tmp/duplicate-ids.txt

# Pass 4: Value ranges
cut -d',' -f5 data.csv | sort | uniq -c | sort -rn > /tmp/status-distribution.txt

# Pass 5: Date validation
cut -d',' -f6 data.csv | grep -v "^[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}" > /tmp/bad-dates.txt
```

---

## Strategy 4: Bash Pre-Processing Pipeline

For massive files (100K+ lines), let bash do the heavy lifting before the AI reads anything.

### Pattern: Transform → Reduce → Analyze

```bash
# Extract, transform, and reduce to manageable size
awk -F',' '
  NR==1 {print; next}
  $5 == "error" || $7 > 1000 {print}
' /path/to/huge.csv > /tmp/relevant-subset.csv

wc -l /tmp/relevant-subset.csv   # verify it's manageable now
# Now read /tmp/relevant-subset.csv normally
```

### Common Pre-Processing Recipes

```bash
# Top N by a column (e.g., top 100 by revenue, column 8)
head -1 data.csv > /tmp/top100.csv
tail -n +2 data.csv | sort -t',' -k8 -rn | head -100 >> /tmp/top100.csv

# Deduplicate by key column (column 1)
head -1 data.csv > /tmp/deduped.csv
tail -n +2 data.csv | sort -t',' -k1,1 -u >> /tmp/deduped.csv

# Sample every Nth row (e.g., every 10th row for a representative sample)
head -1 data.csv > /tmp/sample.csv
awk 'NR % 10 == 0' data.csv >> /tmp/sample.csv

# Group and count
echo "status,count" > /tmp/summary.csv
tail -n +2 data.csv | cut -d',' -f5 | sort | uniq -c | \
  awk '{print $2","$1}' | sort -t',' -k2 -rn >> /tmp/summary.csv

# Filter by date range
head -1 data.csv > /tmp/q1-2024.csv
awk -F',' '$6 >= "2024-01-01" && $6 <= "2024-03-31"' data.csv >> /tmp/q1-2024.csv

# Join two CSVs on a key (simple, for small lookup tables)
# Use awk or the `join` command after sorting both files
```

---

## Temp File Patterns

### Structured Findings File

```markdown
<!-- ${ANALYSIS_WORK}/findings.md -->
---
file: /path/to/source.csv
task: Identify duplicate customer records
total_lines: 45,231
chunks_processed: 0/91
started: 2024-03-15T14:30:00
---

## Progress
- [ ] Chunk 1-500
- [ ] Chunk 501-1000
...

## Findings

### Finding 1 (lines 234, 8901)
- Duplicate customer_id: CUST-4421
- Name variant: "John Smith" vs "J. Smith"
- Recommendation: Merge, keep line 234 (more complete)

### Finding 2 (lines 1205, 1206)
- Duplicate email: john@example.com
- Different customer_ids: CUST-1205, CUST-1206
- Recommendation: Investigate, possible fraud
```

### Append-Only Log Pattern

```bash
# For each chunk, append findings (never overwrite)
echo "## Chunk $CHUNK_NUM (lines $START-$END)" >> /tmp/findings.md
echo "- Found 3 anomalies" >> /tmp/findings.md
echo "  - Line $LINE: $DESCRIPTION" >> /tmp/findings.md
echo "" >> /tmp/findings.md
```

### Progress Tracking File

```markdown
<!-- /tmp/analysis-progress.md -->
# Analysis Progress
- File: data.csv (15,234 lines)
- Chunk size: 500
- Total chunks: 31

## Completed Chunks
| Chunk | Lines | Findings | Notes |
|---|---|---|---|
| 1 | 1-500 | 2 anomalies | Header parsed |
| 2 | 501-1000 | 0 | Clean section |
| 3 | 1001-1500 | 1 anomaly | Null in required field |

## Running Totals
- Total anomalies: 3
- Null fields: 1
- Duplicates: 0
- Format errors: 2
```

---

## CSV-Specific Patterns

### Header Preservation Across Chunks

<HARD-RULE>
When chunking CSV files, always capture the header row separately and reference it for every chunk. Without the header, column data is uninterpretable.
</HARD-RULE>

```
# Step 1: Capture and store header
Read: data.csv, limit=1 → "id,name,email,status,amount,date"
Store in temp file or keep as reference variable

# Step 2: For each chunk, prepend header context
"Analyzing chunk 3 (lines 1001-1500) of data.csv
Columns: id(1), name(2), email(3), status(4), amount(5), date(6)
[chunk data follows]"
```

### Wide CSV Handling (Many Columns)

```bash
# If CSV has 100+ columns, identify relevant columns first
head -1 data.csv | tr ',' '\n' | nl    # numbered column list

# Then extract only needed columns
cut -d',' -f1,5,12,45 data.csv > /tmp/relevant-columns.csv
# Now analyze the slimmer file
```

### CSV with Quoted Fields (Commas Inside Values)

```bash
# Use Python for proper CSV parsing when fields contain commas
python3 -c "
import csv, sys
with open('data.csv') as f:
    reader = csv.reader(f)
    header = next(reader)
    print(f'Columns ({len(header)}): {header}')
    for i, row in enumerate(reader, 2):
        if len(row) != len(header):
            print(f'Line {i}: expected {len(header)} cols, got {len(row)}')
" > /tmp/csv-validation.txt
```

---

## Plain Text File Patterns

Large unstructured text files (documentation, books, transcripts, exports, reports, code dumps) require different strategies than columnar data.

### Reconnaissance

```bash
# Basic shape
wc -l -w -c document.txt                  # lines, words, bytes
file document.txt                          # encoding detection
head -30 document.txt                      # understand structure/format
tail -10 document.txt                      # check for truncation

# Detect structure hints
grep -c "^#\|^=\|^Chapter\|^Section" document.txt   # heading-like lines
grep -n "^$" document.txt | wc -l                     # blank line count (paragraph breaks)
grep -nc "^\s*$" document.txt                          # empty/whitespace-only lines
```

### Chunking Strategy: Semantic vs Fixed

**Fixed-size chunking** (simple, predictable):
```
# Read 500 lines at a time
Read: document.txt, offset=1, limit=500
Read: document.txt, offset=501, limit=500
...
```

**Semantic chunking** (preserves meaning — preferred for analysis):
```bash
# Find natural break points (headings, blank lines, section markers)
grep -n "^#\|^Chapter\|^Section\|^---\|^===" document.txt > /tmp/section-breaks.txt

# Example output:
#   1:# Introduction
#   45:# Background
#   120:## Key Findings
#   230:# Methodology
#   ...

# Now read section by section using the line numbers as boundaries
Read: document.txt, offset=1, limit=44      # Introduction
Read: document.txt, offset=45, limit=75     # Background
Read: document.txt, offset=120, limit=110   # Key Findings
```

### Paragraph-Based Chunking

```bash
# Split text into paragraphs (separated by blank lines) and number them
awk 'BEGIN{p=1} /^$/{p++; next} {print p"\t"$0}' document.txt > /tmp/paragraphs.txt

# Count paragraphs
awk 'BEGIN{p=1} /^$/{p++} END{print p}' document.txt

# Extract paragraph N
awk -v n=15 'BEGIN{p=1} /^$/{p++; next} p==n{print}' document.txt
```

### Search and Summarize Pattern

For tasks like "find all mentions of X" or "summarize the key points about Y":

```bash
# Step 1: Find all relevant lines with context
grep -n -i -C3 "keyword\|related term\|synonym" document.txt > /tmp/keyword-hits.txt
wc -l /tmp/keyword-hits.txt

# Step 2: If hits are manageable (<200 lines), read directly
# If hits are large, chunk the hits file itself

# Step 3: For each hit cluster, note the finding
# Write to /tmp/findings.md:
#   Line 234-238: Discusses keyword in context of...
#   Line 1205-1210: Contradicts earlier point at line 234...
```

### Multi-Document Comparison

When comparing two or more large text files:

```bash
# Quick diff overview
diff --brief file1.txt file2.txt           # just says if different
diff file1.txt file2.txt | head -50        # first differences
diff file1.txt file2.txt | wc -l           # how many diff lines

# Side-by-side comparison of specific sections
diff <(sed -n '100,200p' file1.txt) <(sed -n '100,200p' file2.txt)

# Find lines unique to each file
comm -23 <(sort file1.txt) <(sort file2.txt) > /tmp/only-in-file1.txt
comm -13 <(sort file1.txt) <(sort file2.txt) > /tmp/only-in-file2.txt
```

### Word/Phrase Frequency Analysis

```bash
# Top 50 words (excluding common stop words)
tr '[:upper:]' '[:lower:]' < document.txt | \
  tr -cs '[:alpha:]' '\n' | \
  grep -vwFf <(printf '%s\n' the a an is are was were be been being \
    have has had do does did will would shall should may might can could \
    of in to for on with at by from as into about between through after \
    and or but not no nor so yet both either neither that this it its) | \
  sort | uniq -c | sort -rn | head -50 > /tmp/word-freq.txt

# Find repeated phrases (bigrams)
awk '{for(i=1;i<NF;i++) print tolower($i)" "tolower($(i+1))}' document.txt | \
  sort | uniq -c | sort -rn | head -30 > /tmp/bigrams.txt

# Sentence count estimate
grep -c '[.!?]' document.txt
```

### Large Code Dumps / Source Files

```bash
# Find function/class definitions
grep -n "^def \|^class \|^function \|^const \|^export " source.txt > /tmp/definitions.txt

# Find TODO/FIXME/HACK markers
grep -n "TODO\|FIXME\|HACK\|XXX\|WARN" source.txt > /tmp/markers.txt

# Count by file type if it's a concatenated dump
grep -c "^--- " dump.txt                   # diff-style separators
grep -n "^// File:\|^# File:" dump.txt     # file markers
```

---

## Log File Patterns

### Structured Log Analysis

```bash
# Count log levels
grep -c "ERROR" app.log
grep -c "WARN" app.log
grep -c "INFO" app.log

# Error frequency over time (hourly buckets)
grep "ERROR" app.log | cut -d' ' -f1 | cut -dT -f1-2 | cut -d: -f1 | \
  sort | uniq -c > /tmp/error-frequency.txt

# Top error messages
grep "ERROR" app.log | sed 's/.*ERROR //' | sort | uniq -c | \
  sort -rn | head -20 > /tmp/top-errors.txt

# Stack traces (multi-line — find start, grab context)
grep -n "Exception\|Traceback" app.log > /tmp/exception-lines.txt
```

### Access Log Analysis

```bash
# Top IPs
awk '{print $1}' access.log | sort | uniq -c | sort -rn | head -20

# HTTP status codes distribution
awk '{print $9}' access.log | sort | uniq -c | sort -rn

# Slow requests (response time in last field, > 5 seconds)
awk '$NF > 5.0 {print}' access.log > /tmp/slow-requests.txt

# 404 errors
awk '$9 == 404 {print $7}' access.log | sort | uniq -c | sort -rn | head -20
```

---

## JSONL (JSON Lines) Patterns

```bash
# Count records
wc -l data.jsonl

# Extract a specific field distribution
jq -r '.status' data.jsonl | sort | uniq -c | sort -rn

# Filter records to a subset
jq -c 'select(.status == "error")' data.jsonl > /tmp/errors.jsonl

# Extract specific fields to CSV for easier analysis
jq -r '[.id, .name, .status, .timestamp] | @csv' data.jsonl > /tmp/extract.csv
```

---

## Agent-Specific Implementation Notes

### Chunked Reading (offset/limit)

> **Tool mapping:** Claude Code uses `Read(offset=, limit=)`. Codex/Copilot use `sed -n 'start,endp'` or `head`/`tail`.

```bash
# Read lines 1-500 of a file
sed -n '1,500p' /path/to/file.csv          # shell
# Read(file_path="/path/to/file.csv", offset=1, limit=500)  # Claude Code

# Read lines 501-1000
sed -n '501,1000p' /path/to/file.csv       # shell
# Read(file_path="/path/to/file.csv", offset=501, limit=500)  # Claude Code

# Search for targeted content (faster than sequential read)
grep -n "ERROR" /path/to/file.log | head -50  # shell
# Grep(pattern="ERROR", path="/path/to/file.log", output_mode="content", head_limit=50)  # Claude Code

# Pre-process to reduce data
awk -F',' '$5=="failed"' data.csv > /tmp/failed.csv && wc -l /tmp/failed.csv
```

### GitHub Copilot / VS Code Agents (4-8K Context)

With severely limited context windows:
1. **Always grep first** — never read sequentially in a 4K window
2. **Pre-process to <50 lines** before bringing into context
3. **Use bash one-liners** for aggregation instead of reading raw data
4. **One finding per chunk** — write each finding immediately, don't accumulate in context

### Cursor / Windsurf (32-128K Context)

1. Can handle 300-500 line chunks comfortably
2. Use multi-pass for complex analysis
3. Temp files still essential for findings that span many chunks

---

## Long-Context Second-Model Delegation

For files that are very large but still need holistic analysis (not just grep-targeted), delegate to a second model with a large context window via the Antigravity CLI (stdin closed AND `--sandbox` — both mandatory for these read-only analysis calls, see `antigravity-cli` skill):

```bash
timeout 600 agy --sandbox -p "Analyze this file for <patterns>: $(cat /path/to/chunk)" < /dev/null
```

Use it to:
- Analyze chunks of 5,000-10,000 lines at once for pattern detection
- Summarize entire large files when sequential chunking loses cross-section patterns
- Cross-validate findings from Claude's chunked analysis against a single-pass second-model view

This is optional and complements (not replaces) the chunked strategies above. See `codex-orchestration` for the full delegation patterns. (The old `mcp__gemini-cli__ask-gemini` route is gone; gemini CLI retired 2026-06-18.)

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Reading entire file at once | Truncation, token waste, context pollution | Chunked reading with temp files |
| Relying on context memory across chunks | Compaction erases earlier findings | Write to temp file after each chunk |
| Reading without recon first | Wrong chunk size, missed structure | Always run wc, head, file first |
| Sequential read when searching | Wastes tokens on irrelevant lines | Grep-first targeting |
| Forgetting CSV header on chunk 2+ | Columns become uninterpretable | Capture header separately, reference per chunk |
| Analyzing raw data instead of pre-processing | Overwhelming the context window | Bash reduce first, analyze the reduction |
| Not tracking position | Can't reference findings to source | Always track line numbers |
| Accumulating all findings in context | Context fills up, earlier data lost | Append to temp file, read at end |
| Presenting without verification | Errors compound across chunks | Final pass: read temp file, verify |
| Using same temp file name across tasks | Stale data from previous analysis | Use task-specific temp file names |

---

## Complete Workflow Template

```
1. RECON
   bash: wc -l, ls -lh, file, head -5, tail -3
   → Capture: line count, size, encoding, headers, structure

2. PLAN
   Choose strategy based on file size and task:
   - Sequential chunking (full scan needed)
   - Grep-first targeting (searching for patterns)
   - Bash pre-processing (massive files, need reduction)
   Determine chunk size based on agent context window
   Create temp file with analysis metadata

3. EXECUTE
   For each chunk / grep result / pre-processed extract:
   a. Read the data
   b. Analyze against task criteria
   c. Append findings to temp file (with line numbers!)
   d. Update progress in temp file

4. AGGREGATE
   Read the temp findings file
   Consolidate, deduplicate, sort findings
   Calculate summary statistics

5. VERIFY
   Spot-check 2-3 findings against source (re-read those specific lines)
   Confirm counts are consistent
   Flag any uncertainties

6. PRESENT
   Structured output with:
   - Summary statistics
   - Key findings (with line number references)
   - Methodology note (chunks processed, strategy used)
   - Caveats or limitations

7. CLEANUP
   Remove temp files (or note their location for user reference)
```

---

## Related Skills

| Topic | Skill |
|---|---|
| Python data processing (Polars, Dask) | `python-parallelism` |
| Database queries for large datasets | `python-data-engineer` |
| MCP server for custom file tools | `mcp-server-creator` |
