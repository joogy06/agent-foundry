---
name: pick-developer
description: Use when reading, understanding, writing, or debugging Pick / MultiValue database applications — the MultiValue products and dialects (Rocket UniVerse, UniData, D3, jBASE, OpenQM, ScarletDME, NEC Reality), the schema-in-the-dictionary data model and the mark hierarchy (item/field/value/sub-value/text marks), Pick/Data/MV BASIC (file I/O, dynamic-array `<a,v,s>` operations, OCONV/ICONV conversions, flow, SUBROUTINE/CALL/COMMON/EXECUTE/CHAIN), DICT items and correlatives (D/I/A/S/X/PH, TRANS/Tfile as the SQL-JOIN substitute), TCL versus the query/report language versus BASIC, and orienting in unfamiliar Pick code. Trigger on - Pick, MultiValue, MV database, UniVerse, UniData, U2, D3, jBASE, OpenQM, ScarletDME, Reality, Pick BASIC, UniBasic, jBC, QMBasic, dynamic array, dictionary item, correlative, conversion code, "understand Pick code", "read this MultiValue program". Part of a legacy-comprehension skill family with cobol-developer and datastage-developer.
---

# Pick / MultiValue Developer Reference

A reading-and-comprehension reference for the Pick / MultiValue database family. Companion to `cobol-developer` and `datastage-developer` in the legacy-comprehension family; pairs with `legacy-code-intel` (which can index Pick BASIC as a symbol graph) and `lineage-extract-static` (data flow through Pick artifacts).

> **Accuracy provenance.** The concrete facts below are tagged **[VERIFIED]** / **[LIKELY]** / **[UNCERTAIN]** exactly as confirmed in the source grounding (multiple sources including tier-1 vendor documentation; two independent web-grounded research arms agreed on every hallucination-prone fact). **Keep the tags when you reason from this file.** A confidently-stated *wrong* Pick fact is worse than an honest "verify this in the actual system" — the MultiValue family is under-represented in model training data, and several details (especially dictionary layout and `LOCATE`/`INS`/`DEL` syntax) genuinely **differ by dialect**. When a tag says the spelling is dialect-dependent, treat it as such; do not smooth it into a single confident answer.

<HARD-RULE>
A `READU` (or `READVU` / `READL`) that takes an update lock with NO matching `WRITE` / `WRITEU` / `RELEASE` on every code path is a lock-leak bug — the item stays locked until the process dies or the lock table fills. When reading Pick BASIC, treat any locked read whose lock is not provably released on all exits (including the ELSE / error branches) as a defect, not a style choice. [VERIFIED]
</HARD-RULE>

<HARD-RULE>
Identify the dialect BEFORE interpreting a dictionary item or the most divergent BASIC verbs. The dictionary attribute layout differs between classic Pick / D3 and the Rocket U2 family (UniVerse / UniData), and `LOCATE`, `INS`, and `DEL` have dialect-varying argument forms. Reading a U2 D-type dictionary item with the classic-Pick "attr-7 = conversion, attr-8 = correlative" rule will misread the schema. Detect first, then decode. [VERIFIED that the layouts differ]
</HARD-RULE>

<HARD-RULE>
Numbers in Pick are stored as variable-length strings, not as a typed DECIMAL/INTEGER. Numeric meaning comes from conversions/correlatives (display scaling) or from BASIC arithmetic at run time — never assume a fixed precision or a typed NULL. A "column" that looks numeric in a report is a presentation convention applied by a conversion code, not a storage type. [VERIFIED]
</HARD-RULE>

<HARD-RULE>
The dictionary is the schema, and it can lie or be incomplete. One physical attribute may be described by several dictionary items (synonyms), an attribute may have NO dictionary item yet still hold data, and a dictionary item may describe a value pulled from ANOTHER file (a correlative / `TRANS`). Never treat the set of dictionary items as a complete or one-to-one column list. Decode each item to learn what a stored attribute *means*; read the data to learn what is actually there. [VERIFIED]
</HARD-RULE>

---

## 1. Products and Dialects (the #1 teaching point)

**One ecosystem, many dialects. The concepts are universal; the exact spellings are dialect-dependent.** Every MultiValue product shares the same core model (dictionary + data, item-ids, the mark hierarchy, dynamic arrays, a compiled BASIC, a TCL shell, an English-like query language). What differs is naming, dictionary layout, and the most advanced verb syntax. **Identify which product you are looking at first** — it changes how you read the dictionary and a few BASIC verbs.

### Current products (2026) [VERIFIED]

| Product | Owner / lineage | BASIC dialect name | Notes |
|---|---|---|---|
| **UniVerse** (U2) | Rocket Software (VMark → Ardent → Informix → IBM → Rocket 2009) | UniVerse BASIC | Current; the U2 family |
| **UniData** (U2) | Rocket Software | UniBasic | Current; the U2 family; dictionary layout differs subtly from UniVerse |
| **D3** + mvBase | Rocket Software (Pick Systems → Raining Data → TigerLogic → Rocket 2014) | Data/BASIC (Pick BASIC) | Current; classic-Pick lineage |
| **jBASE** | Rocket Software (jBASE → Temenos → Zumasys 2015 → Rocket 2021) | jBC | Current; compiles toward native/C |
| **OpenQM** (QM) | Rocket Software | QMBasic | Current; proprietary now; last GPL release was 2.6-6 |
| **ScarletDME** | Open-source (github geneb/ScarletDME) | QMBasic-compatible | Current; open-source fork of the OpenQM GPL line |
| **NEC Reality** | NEC | Data/BASIC | Current — the ORIGINAL commercial Pick (Microdata, 1973); V15.6 released Sep 2025 |

**Rocket Software is the dominant owner** (UniVerse + UniData + D3 + jBASE + OpenQM). [VERIFIED]

### Declining / historical [VERIFIED]
- **InterSystems Caché / IRIS MultiValue** — **DEPRECATED in IRIS 2025.1** (present for compatibility, not for new applications). A useful "this branch is winding down" datapoint.
- **Also seen in the wild:** Prime INFORMATION, Revelation / OpenInsight, Ultimate, R83.
- **Community:** the `comp.databases.pick` newsgroup and the `mvdbms` group are long-running MultiValue forums.

### How to tell dialects apart quickly [VERIFIED]
- DICT items use **I-descriptors** and a U2-style layout → **UniVerse / UniData** (U2).
- DICT uses **A/S items** and **attribute-8 correlatives**, `Tfile` joins → **classic Pick / D3 / Reality**.
- Source talks **jBC**, compiles to objects/native → **jBASE**.
- Source talks **QMBasic** → **OpenQM** or **ScarletDME**.

---

## 2. The Data Model (VERIFIED — the conceptual core)

A **file** has two parts: a **DICT** (dictionary — the schema) and a **DATA** part (the records). Records are called **items**, each keyed by an **item-id**. The item-id is conceptually **attribute 0** (`@ID`). [VERIFIED]

- **Schema-less on disk; the DICT is the schema.** Storage is **hashed** by item-id → fast keyed reads with no index required. There are no fixed columns on disk. [VERIFIED]
- **Three levels of nesting** are expressed by **mark characters** — special high-code-point delimiter bytes embedded in the data, in descending code-point order.

### The mark hierarchy [VERIFIED — code points confirmed against NEC Reality decimal+hex]

| Mark | Names | Decimal | Hex | Glyph (common display) | Meaning |
|---|---|---|---|---|---|
| Item / Segment Mark | `@IM` | 255 | `X'FF'` | `^` (often) | Record terminator (separates items in the file) |
| Field / Attribute Mark | `@FM` / `@AM` | 254 | `X'FE'` | `^` | Separates attributes (fields) within an item |
| Value Mark | `@VM` | 253 | `X'FD'` | `]` | Separates values within an attribute (the "multi" in MultiValue) |
| Sub-value Mark | `@SM` | 252 | `X'FC'` | `\` | Separates sub-values within a value |
| Text Mark | `@TM` | 251 | `X'FB'` | (varies) | Sub-divides below sub-value |

Notes that prevent the classic mistakes:
- `@FM` and `@AM` are **the same character (254)** — "field mark" and "attribute mark" are two names for one byte; which name appears depends on dialect/docs. [VERIFIED]
- The **sub-value mark is 252**, NOT the "segment mark". The *segment / item* mark is **255**. Avoid the common misnaming. [VERIFIED]
- Glyphs `^` (254), `]` (253), `\` (252) are the conventional **display** representations — the stored bytes are the high code points above, not the literal ASCII glyphs. (255 and 254 can both surface as `^` depending on the tool; do not rely on the glyph to disambiguate 255 vs 254.)
- **Below 251** the assignments are **[UNCERTAIN]** / platform-specific — do not generalize codes lower than the text mark.

### Dynamic vs dimensioned arrays [VERIFIED]

- **Dynamic array** = a mark-delimited **string**, addressed positionally as `<attribute, value, sub-value>`. No declaration; any string variable can be treated as a dynamic array. This is the everyday MultiValue data structure — a whole record read into one variable is a dynamic array.
- **Dimensioned array** = `DIM X(n)` — a fixed, subscripted array. Bridged to records by:
  - `MATREAD record INTO arr` — read a record's attributes into the dimensioned array (attribute *n* → `arr(n)`).
  - `MATWRITE arr TO record` — write the dimensioned array back as a record.
  - `MATBUILD` (dimensioned → dynamic string) and `MATPARSE` (dynamic string → dimensioned) convert between the two shapes.

### Worked example: one record IS the order + its lines (associations)

The defining MultiValue shape: child rows live *inside* the parent record as parallel multi-valued attributes kept row-aligned by an **association**. One `ORDERS` item, shown with glyphs for the marks:

```
attr 1 (@ID) : ORD1001
attr 2       : C500                      <- customer id (single-valued)
attr 4       : 19518                     <- order date (day-count; OCONV "D2/" -> 06/09/26)
attr 5       : SKU-A ] SKU-B ] SKU-C     <- line SKU      (3 values, ]-delimited)
attr 6       : 2 ] 1 ] 4                 <- line QTY      (3 values, row-aligned with attr 5)
attr 7       : 9.99 ] 19.50 ] 4.25       <- line PRICE    (3 values, row-aligned)
```

Attributes 5, 6, 7 form an **association** (named in the dictionary): the 2nd value of each — `SKU-B`, qty `1`, price `19.50` — is one logical order line. In SQL this would be an `ORDER_LINES` child table joined to `ORDERS`; here it is **one read** of one item. In BASIC:

```basic
      READ REC FROM F.ORD, "ORD1001" THEN
         N = DCOUNT(REC<5>, @VM)          ; * number of line values (= 3)
         FOR L = 1 TO N
            SKU   = REC<5,L>              ; * Lth value of attr 5
            QTY   = REC<6,L>              ; * row-aligned qty
            PRICE = REC<7,L>             ; * row-aligned price
            ...
         NEXT L
      END
```

The hazard: if the parallel attributes ever fall **out of alignment** (a value added to attr 5 but not attr 6), `REC<6,L>` returns an empty string for that line — a silent data bug. Row-aligned multi-values are an invariant the code must preserve, and a reader should watch for code that appends to one leg of an association but not the others.

---

## 3. The Language: Pick / Data / MV BASIC

The compiled procedural language. The **name varies by product**: **UniVerse BASIC** (UniVerse), **UniBasic** (UniData), **jBC** (jBASE), **QMBasic** (OpenQM / ScarletDME), **Data/BASIC** or **Pick BASIC** (classic / D3 / Reality). It keeps the `BASIC` keyword for compilation, and a cataloged program is invoked as a TCL verb (`CATALOG`). The constructs below are conceptually shared across all of them. [VERIFIED]

### File I/O [VERIFIED]

```basic
      * Open a file (DICT or DATA) to a file variable
      OPEN "CUSTOMERS" TO F.CUST ELSE STOP 201, "CUSTOMERS"

      * Read a whole item (record) into a dynamic array
      READ REC FROM F.CUST, ID THEN
         ...                       ; * THEN = item found
      END ELSE
         ...                       ; * ELSE = item missing
      END

      * Read with an update lock (intend to write back)
      READU REC FROM F.CUST, ID THEN ... END ELSE ... END
      READL REC FROM F.CUST, ID ...        ; * shared (read) lock
      READV X FROM F.CUST, ID, 3 THEN ...  ; * read ONE attribute (attr 3)
      MATREAD ARR FROM F.CUST, ID THEN ... ; * read into a dimensioned array

      * Write
      WRITE  REC ON F.CUST, ID             ; * write + release lock
      WRITEU REC ON F.CUST, ID             ; * write but KEEP the lock
      WRITEV X ON F.CUST, ID, 3            ; * write ONE attribute
      MATWRITE ARR ON F.CUST, ID           ; * write a dimensioned array

      DELETE F.CUST, ID                    ; * delete an item
      RELEASE F.CUST, ID                   ; * release a held lock (no write)
```

- `READ`/`READU`/`READL` use **`THEN` / `ELSE`**; the **`ELSE` branch means the item was not found**. Confusing `ELSE` with an error is a frequent misreading — it is the normal "record missing" path. [VERIFIED]
- The **`U` suffix takes an update lock**, the **`L` suffix a shared lock**. See the lock-leak HARD-RULE above. [VERIFIED]

### Selection and the canonical loop [VERIFIED]

```basic
      SELECT F.CUST TO CUST.LIST          ; * build an active select-list
      *  SSELECT  = SELECT with a sort

      LOOP
         READNEXT ID FROM CUST.LIST ELSE EXIT   ; * ELSE = end of list
         READ REC FROM F.CUST, ID THEN
            GOSUB PROCESS.ITEM
         END
      REPEAT
```

This `SELECT → LOOP / READNEXT … ELSE EXIT / READ … / REPEAT` is the **"for each record matching a query"** idiom — recognizing it is most of reading Pick BASIC. `READNEXT … ELSE` means **end of the list**, not an error. A select-list can also be produced by the query language (a `SELECT`/`SSELECT` sentence at TCL) and consumed by the very next BASIC program's `READNEXT`. [VERIFIED]

### Dynamic-array operations (`<a,v,s>` and the function forms)

| Operation | Bracket form | Function form | Notes |
|---|---|---|---|
| Extract | `X = REC<a,v,s>` | `X = EXTRACT(REC,a,v,s)` | Read attribute *a* / value *v* / sub-value *s* [VERIFIED] |
| Replace | `REC<a,v,s> = Y` | `REC = REPLACE(REC,a,v,s,Y)` | Set in place [VERIFIED] |
| Append a field | `REC<-1> = Y` | — | Idiom: append a new attribute without leaving a spurious empty field [VERIFIED] |
| Count | `N = DCOUNT(REC,@FM)` | — | Count attributes (or values with `@VM`) [VERIFIED] |
| Sequential enum | `REMOVE X FROM REC SETTING P` | — | Efficient walk of successive elements; `P` flags the mark crossed [VERIFIED] |
| Locate | `LOCATE(...)` | `LOCATE ...` | Find a value's position. **Most dialect-divergent syntax — flag it** [LIKELY] |
| Insert / delete element | `INS X BEFORE REC<...>` / `DEL REC<...>` | — | Insert/delete a dynamic-array element. **Dialect-varying** [LIKELY] |
| Find | `FIND X IN REC SETTING ...` | — | Locate by value across the array [VERIFIED conceptually] |

> **Dialect warning [LIKELY].** `LOCATE` is the **single most dialect-divergent** verb — classic Pick, UniVerse, and UniData each have a different argument order and `BY` clause. `INS` and `DEL` likewise vary. When you see `LOCATE` / `INS` / `DEL`, note the dialect and verify the exact form against that platform's manual rather than assuming. The `<a,v,s>`, `EXTRACT`, `REPLACE`, `<-1>`, `DCOUNT`, and `REMOVE … SETTING` forms are stable across dialects.

```basic
      ORD.LINES = REC<5>                  ; * attribute 5 (^-delimited group)
      SECOND.SKU = REC<5,2>               ; * 2nd value (]-delimited) of attr 5
      FIRST.SUB  = REC<5,2,1>             ; * 1st sub-value (\-delimited)
      REC<-1>    = NEW.NOTE               ; * append a new attribute
      N.LINES    = DCOUNT(REC<5>, @VM)    ; * how many order lines
```

### Conversions: OCONV / ICONV [VERIFIED]

- `OCONV(data, code)` converts **internal → external (display)**.
- `ICONV(data, code)` converts **external (display) → internal (storage)**. They are inverses.
- **Dates** are stored as an **integer day count since the epoch 31 Dec 1967** — so **day 1 = 1 Jan 1968**. A stored value like `19000` is days since that epoch, displayed via a `D`-family conversion. [VERIFIED]

```basic
      DISP.DATE = OCONV(REC<7>, "D2/")    ; * internal day-count -> "06/09/26"
      INT.DATE  = ICONV("06/09/2026", "D")  ; * display date -> internal day count
      MONEY     = OCONV(REC<9>, "MR2,$")  ; * scaled integer -> "$1,234.56"
```

### Flow control [VERIFIED]

```basic
      IF COND THEN ... END ELSE ... END

      BEGIN CASE                          ; * the MultiValue switch
         CASE STATUS = "A" ; GOSUB ACTIVE
         CASE STATUS = "C" ; GOSUB CLOSED
         CASE 1           ; GOSUB OTHER   ; * CASE 1 = default
      END CASE

      GOSUB SUBLABEL                      ; * internal call; RETURN comes back
      ...
   SUBLABEL:
      ...
      RETURN

      LOOP ... WHILE COND DO ... REPEAT   ; * pre/post-test loop
      FOR I = 1 TO N ... NEXT I
```

- `BEGIN CASE … END CASE` is the **switch**; `CASE 1` (always true) is the **default** branch. [VERIFIED]
- `GOSUB label … RETURN` is an **internal** subroutine (within the same program); the target is a **label**. [VERIFIED]

### Modular / inter-program structure [VERIFIED]

| Construct | Meaning |
|---|---|
| `SUBROUTINE NAME(args) … RETURN` | An **external** callable module (separate program). |
| `CALL NAME(args)` | Call an external `SUBROUTINE`. |
| `CALL @VAR(args)` | **Indirect** call — target named by a variable (resolve at run time; treat as dynamic). |
| `COMMON [/name/] vars` | Shared memory across `CALL`s (named or unnamed common block). |
| `EXECUTE "tcl" [CAPTURING var] [RETURNING var]` / `PERFORM "tcl"` | Run a **TCL / query sentence** from BASIC; read the quoted string as the shell/query language. |
| `CHAIN "tcl"` | **Terminate** this program and start a new one — **no return**. |
| `ENTER NAME` | Transfer to another program, **no return** [LIKELY]. |

- `EXECUTE`/`PERFORM` embeds the **TCL / query layer inside BASIC** — the quoted argument is a shell or query sentence, not BASIC. Read it as such when tracing. [VERIFIED]
- `CHAIN` leaves the current program for a new one and does not come back; `COMMON` is how state survives a `CALL` (or a `CHAIN`, by configuration). [VERIFIED]

---

## 4. Dictionaries and Correlatives (hallucination-prone — detect dialect first)

The DICT defines how stored attributes are interpreted and displayed. **The layout differs between classic Pick / D3 and the U2 family — read the actual dictionary after identifying the dialect.** [VERIFIED that they differ]

### Dictionary item types [VERIFIED]

| Type | Meaning |
|---|---|
| `D` | **Data descriptor** — points at a stored attribute by its position number. |
| `I` | **I-descriptor** — interpretive / **computed** field; the U2 family's modern correlative (an expression evaluated at query time). |
| `A` / `S` | Classic-Pick **attribute / synonym** definitions (kept for compatibility). |
| `V` | **Virtual** attribute [LIKELY]. |
| `X` | **Control / metadata** item — ignored as a data field. |
| `PH` | **Phrase** — a saved query fragment (a named bundle of column/selection tokens). |

**Migration rule [VERIFIED]:** a classic `A`/`S` item that carries an attribute-8 **correlative** becomes a U2 **I-descriptor**; an `A`/`S` with no correlative becomes a plain `D`.

### Classic Pick / D3 attribute-definition layout

The classic dictionary item is itself a record whose attributes mean: [attrs 1,2,7,8 VERIFIED; 3,9,10 LIKELY]

| Attr | Meaning |
|---|---|
| 1 | **Type** (`D` / `A` / `S` / `X`) |
| 2 | **AMC** — the attribute number it points at (`0` = item-id) |
| 3 | Column heading [LIKELY] |
| 7 | **CONVERSION** code (display conversion) |
| 8 | **CORRELATIVE** (extract / compute / sort — including a `Tfile` join) |
| 9 | Justification (`L`/`R`/`T`/`U`) [LIKELY] |
| 10 | Width [LIKELY] |

### U2 (UniVerse / UniData) D-type layout — DIFFERENT

> ⚠ **Do NOT hard-code "attr-7 = conversion, attr-8 = correlative" for all MultiValue — that is classic-Pick / D3.** In U2 the **conversion is field 3** and computation lives in an **I-descriptor**, not an attribute-8 correlative. UniVerse and UniData also differ from each other in the later fields — read the real dictionary. [fields 1-4 VERIFIED; 5-7 LIKELY]

| Field | Meaning |
|---|---|
| 1 | `D` |
| 2 | Attribute / location number |
| 3 | **CONVERSION** |
| 4 | Heading |
| 5 | Association [LIKELY] |
| 6 | Format (width + justification, e.g. `10R`) [LIKELY] |
| 7 | `S` / `M` (single- or multi-valued) [LIKELY] |

### Conversion codes (used in attr-7 classic / field-3 U2) [VERIFIED]

| Code | Meaning |
|---|---|
| `D` family (`D2/`, `D4-`, …) | **Dates** (stored as day-count since 31 Dec 1967) |
| `MT` | Time |
| `MD` / `MR` / `ML` *n* | Mask decimal / right / left (e.g. `MR2` = money, 2 decimal places) |
| `MC` masks (`MCU`/`MCL`/`MCN`/`MCA`/`MCT`) | Case / character-class masks |
| `G` (`Gm*n`) | Group extract — pull the *n*th group around delimiter *m* [LIKELY] |
| `T` / `Tfile` | Translate (file lookup) |

### Correlatives (classic, attribute 8) [VERIFIED]

| Form | Meaning |
|---|---|
| `Tfile; …` / `TRANS(file, key, attr, ctrl)` | **FILE TRANSLATE** — look the key up in another file and pull an attribute. **This is the MultiValue substitute for a SQL JOIN.** |
| `A; …` | Arithmetic (algebraic expression over attributes) |
| `C; …` | Concatenation |
| `F; …` | Reverse-Polish (RPN) function |

**`TRANS()` / `Tfile` is the join.** When a dictionary item's correlative (classic) or I-descriptor (U2) calls `TRANS`, that "column" is actually **pulled from another file per row** — exactly what a SQL `JOIN` would do. Recognizing it tells you which other file the report secretly depends on. [VERIFIED]

### Worked example: decoding a dictionary item

A dictionary item is itself a record. Reading it attribute-by-attribute recovers what a stored data attribute *means*. Two examples — the **same logical field in two dialects** — to make the layout split concrete.

**Classic Pick / D3 `DICT ORDERS` item `ORD.DATE`** (the dict item's own attributes, by number):

```
attr 1: D          <- type: a data descriptor (points at a stored attribute)
attr 2: 4          <- AMC: points at data attribute 4
attr 3: Order Date <- column heading
attr 7: D2/        <- CONVERSION: a date, displayed MM/DD/YY  (so attr 4 is a day-count)
attr 8:            <- CORRELATIVE: empty (no compute / no join here)
attr 9: R          <- justification: right
attr 10: 8         <- width: 8
```

Read: *data attribute 4 of an `ORDERS` item is a date stored as a day-count since 31-Dec-1967, shown as `MM/DD/YY`.* Now a `TRANS` correlative version — `CUST.NAME` that pulls from another file:

```
attr 1: A          <- a classic attribute-definition item
attr 2: 2          <- points at data attribute 2 (the customer id)
attr 8: TCUSTOMERS;X;1;1   <- CORRELATIVE: Tfile join into CUSTOMERS, return attr 1
```

Read: *the `CUST.NAME` "column" is not stored on the order at all — it is the customer **id** in attribute 2, used to look up attribute 1 (name) in the `CUSTOMERS` file. That `Tfile` correlative is your JOIN.*

**The SAME `ORD.DATE` field in U2 (UniVerse / UniData)** — note conversion has moved to **field 3** and there is no attribute-8 correlative:

```
field 1: D          <- type
field 2: 4          <- attribute/location number (still attribute 4)
field 3: D2/        <- CONVERSION (U2 puts it HERE, not in attr 7)
field 4: Order Date <- heading
field 6: 8R         <- format: width 8, right-justified
field 7: S          <- single-valued
```

And the U2 equivalent of a computed/joined column is an **I-descriptor** (type `I`), whose field 2 holds an *expression* (e.g. `TRANS("CUSTOMERS", @RECORD<2>, 1, "X")`) rather than a stored attribute number. **This is exactly the layout split the dialect HARD-RULE warns about** — applying the classic "attr-7/attr-8" rule to this U2 item would read the wrong fields entirely.

---

## 5. Three Layers: TCL vs Query Language vs BASIC (don't conflate)

MultiValue has **three distinct language layers**. A frequent comprehension error is treating them as one. [VERIFIED]

### TCL — the shell [VERIFIED]
**Terminal Control Language** is the command shell. Verbs are resolved through the **Master Dictionary (MD)** or **VOC** file (customizable; a **cataloged BASIC program becomes a TCL verb**). Common verbs:

```
LIST  SORT  SELECT  SSELECT          ; * run a query / build a select-list
ED / AE                              ; * editor
BASIC <file> <prog>                  ; * compile a BASIC program
CATALOG <file> <prog>                ; * make a compiled program callable as a verb
RUN <file> <prog>                    ; * run a program
COPY  CREATE.FILE  CLEAR.FILE        ; * file management
LOGTO  WHO                           ; * account / session
```

### Query / report language — non-procedural, DICT-driven [VERIFIED]
English-like, **driven by the dictionary**. **Same idea, different product names:** UniVerse = **RetrieVe**; UniData = **UniQuery**; classic Pick / D3 / Reality = **ACCESS** (a.k.a. **ENGLISH**). A sentence is: `verb file [WITH selection] [BY sort] [columns] [modifiers]`.

```
LIST CUSTOMERS WITH STATE = "CA" BY NAME NAME ADDRESS BALANCE
```

`SELECT` / `SSELECT` issued here **feed BASIC's `READNEXT`** — a query builds the list, BASIC walks it.

### BASIC — compiled procedural
Covered in §3. Connected to the other two layers via `EXECUTE`/`PERFORM` (run a TCL/query sentence from BASIC) and via select-lists (query `SELECT` → BASIC `READNEXT`).

### PROC and paragraphs [VERIFIED]
- **PROC** = the classic Pick **command-macro** language (stored in MD/VOC; a PROC item starts `PQ`/`PQN`). Glue that scripts TCL.
- **Paragraph** = a **UniVerse stored sentence sequence** in the VOC — shell-alias-like (a named series of TCL/query sentences).

> **Distinction to hold in mind:** TCL = the shell and its verbs; the query language = non-procedural DICT-driven reporting; BASIC = compiled procedural code. They interlock (BASIC ↔ TCL via `EXECUTE`; query `SELECT` → BASIC `READNEXT`; PROC/paragraph glue TCL sentences) but they are not the same language.

### Inspecting items and dictionaries from TCL

When you have access to a live system (or a transcript of one), these TCL sentences are how you *see* what the data and schema actually are — invaluable for grounding a comprehension pass in reality rather than guessing:

```
LIST CUSTOMERS                       ; * report all items using the dictionary's default columns
LIST DICT CUSTOMERS                  ; * report the DICTIONARY items (the schema itself)
SORT CUSTOMERS BY NAME NAME BALANCE  ; * sorted report of chosen columns
COUNT CUSTOMERS WITH STATE = "CA"    ; * how many items match
ED CUSTOMERS ORD1001  (or AE)        ; * open one item in the editor to see raw attributes
```

- `LIST DICT <file>` dumps the **dictionary** — the fastest way to recover the schema (types, conversions, correlatives) without reading source. [LIKELY — verb spelling stable across dialects; modifiers vary]
- Opening a single item in the editor (`ED` / `AE`) shows its **raw attribute lines** — each editor line is one attribute, so value-marks and sub-value marks appear inline; this is how you confirm an association's row-alignment by eye.
- The conversion/correlative columns from `LIST DICT` tell you which attributes are dates (day-counts), which are scaled money, and which are secretly `TRANS` joins into other files — i.e. the same decode the comprehension checklist (§7 step 4) performs from source.

> When no live system is available, the **source dictionary definitions** (the `DICT` file's items, often kept under version control alongside the BASIC) are the schema of record — read them the same way.

---

## 6. Idioms and Gotchas vs SQL / COBOL (VERIFIED conceptually)

If you are coming from SQL or COBOL, these are the conceptual mismatches that cause misreadings:

| MultiValue reality | SQL / COBOL expectation it breaks |
|---|---|
| **Schema lives in the DICT, not the data.** Many dict items can describe one physical attribute; an attribute with no dict item still holds data; "columns" are a reporting convention. | A table's columns are fixed and authoritative. |
| **No real tables, no fixed columns, no typed NULLs** — everything is a variable-length string; the model is **NF² (non-first-normal-form)** by design. | First-normal-form rows with typed columns. |
| **MultiValues replace child / junction tables.** Order lines live as value-marked entries *inside* the order item, kept row-aligned by an **association**; one read returns the whole order. | A separate `ORDER_LINES` table joined to `ORDERS`. |
| **Correlatives / `TRANS()` replace JOINs** — a per-column lookup into another file. | A `JOIN` clause in the query. |
| **Item-id-centric access** — hashed, fast by key. "All where X" = build a select-list, then `READNEXT` loop. No default optimizer; U2 secondary indexes are **explicit**. | A query planner picks indexes automatically. |
| **`@`-system variables** carry context. | Session/context is implicit or in bind variables. |
| **Case-sensitivity:** data, item-ids, and BASIC are generally **case-SENSITIVE**; TCL verbs are conventionally uppercase; this is **platform-configurable** (flag it). | Often case-insensitive identifiers. |
| **Numbers are strings**; numeric intent via conversions/correlatives (`MR`/`MD` scaling) or BASIC arithmetic — **no DECIMAL type**. | Typed numeric columns with fixed precision. |

### `@`-system variables [VERIFIED for @ID/@RECORD/marks; @USERNO/@WHO/@DATE/@TIME LIKELY, names vary]
- `@ID` — the current item-id.
- `@RECORD` — the **whole current record** as a dynamic array (used inside I-descriptors to reference other attributes of the same item).
- `@FM` / `@AM` / `@VM` / `@SM` / `@TM` — the mark characters (254 / 254 / 253 / 252 / 251).
- `@USERNO` / `@WHO` / `@DATE` / `@TIME` — session/user context [LIKELY; names vary by dialect].

---

## 7. Orienting in Unfamiliar Pick Code (the comprehension checklist)

A repeatable procedure for a model (or a human) dropped into a strange MultiValue program. This is the payload of this skill.

1. **Identify the dialect first** — it changes the dictionary layout and a few verbs:
   - DICT with **I-descriptors** + U2-style layout → **UniVerse / UniData** (U2).
   - **`Tfile` / attribute-8 correlatives / `A`-`S` items** → **classic Pick / D3 / Reality**.
   - **jBC** source → **jBASE**; **QMBasic** source → **OpenQM / ScarletDME**.

2. **Find the entry point.** A `PROGRAM name` or the first executable line is a top-level program. A `SUBROUTINE name(args)` is a **called module** — find its callers via the VOC / PROC / paragraphs that invoke it (or via `CALL` sites in other programs).

3. **Trace inter-program flow:**
   - `CALL` (and `CALL @VAR`) → an external `SUBROUTINE` (indirect calls are dynamic — resolve at run time).
   - `EXECUTE` / `PERFORM` → a **TCL / query sentence**; read the quoted string as the shell/query language, not BASIC.
   - `CHAIN` → leaves this program for a new one (no return).
   - `ENTER` → transfer, no return [LIKELY].
   - `COMMON` → shared state that survives the call.

4. **Decode the DICT to recover the schema.** For each dictionary item, read:
   - the **attribute number** (which stored position it points at),
   - the **type** (`D` stored / `I` computed / `X` control / `PH` phrase),
   - the **conversion** (`D2/` ⇒ the attribute is a date stored as a day-count; `MR2` ⇒ scaled money),
   - the **correlative / `TRANS`** (⇒ this "column" is pulled from another file = your join).
   This tells you **what `REC<n>` actually means**.

5. **Read `<a,v,s>`:** `REC<3>` = attribute 3 (`^`-delimited); `REC<3,2>` = the 2nd value (`]`-delimited) of attr 3; `REC<3,2,1>` = the 1st sub-value (`\`-delimited); `REC<-1> = x` appends a new attribute. **Parallel multi-valued attributes that move together are an association** = row-aligned line items (the substitute for a child table).

6. **Recognize the `SELECT` / `READNEXT` loop** = "for each record matching a query." `READNEXT … ELSE` = **end of list**; `READ … THEN/ELSE` = **found / missing** (the `ELSE` is the not-found path, not an error).

7. **Watch locking.** `READU` (lock) … `WRITE`/`WRITEU`/`RELEASE`. A `READU` with **no matching** `WRITE`/`RELEASE` on every path is a **lock-leak bug** (see the HARD-RULE). Trace each locked read to its release on all branches, including error/`ELSE` paths.

### Worked micro-example

```basic
      OPEN "ORDERS" TO F.ORD ELSE STOP 201, "ORDERS"
      OPEN "DICT", "ORDERS" TO D.ORD ELSE NULL
      SELECT F.ORD TO ORD.LIST
      LOOP
         READNEXT OID FROM ORD.LIST ELSE EXIT       ; * (6) end of list
         READU REC FROM F.ORD, OID ELSE CONTINUE    ; * (7) lock taken; ELSE = missing
            CUST   = REC<2>                          ; * (5) attr 2 = customer id
            ODATE  = OCONV(REC<4>, "D2/")            ; * (4) attr 4 is a date (day-count)
            LINES  = DCOUNT(REC<5>, @VM)             ; * (5) value-marked order lines
            CNAME  = TRANS("CUSTOMERS", CUST, 1, "X"); * (4) TRANS = the JOIN to CUSTOMERS
            REC<9> = "PROCESSED"
         WRITE REC ON F.ORD, OID                     ; * (7) lock released here
      REPEAT
```

Reading it with the checklist: a select-list over `ORDERS` (6), a locked update read whose lock is released by the `WRITE` on the success path (7) — but note the `ELSE CONTINUE` path takes **no lock** so there is nothing to leak there; attribute 2 is the customer id and attribute 4 is a **date stored as a day-count** decoded by `OCONV "D2/"` (4); attribute 5 holds **value-marked order lines** counted with `DCOUNT(…, @VM)` (5); and `TRANS("CUSTOMERS", …)` is the **join** that pulls the customer name from another file (4). The dialect would be inferred from the surrounding dictionary (I-descriptors → U2; `Tfile`/A-S → classic) (1).

---

## 8. Anti-Patterns (reading and writing)

| Anti-Pattern | Why it fails | Correct approach |
|---|---|---|
| Reading a **U2 dictionary** with the **classic-Pick** "attr-7 = conversion, attr-8 = correlative" rule | U2 puts conversion in **field 3** and computation in an **I-descriptor**; you misread which attribute is the date/money and miss the joins | Identify the dialect first; in U2 read field 3 for conversion and look for I-descriptors; read the actual dictionary |
| Assuming `LOCATE` / `INS` / `DEL` have one fixed syntax | These are the **most dialect-divergent** verbs; classic Pick, UniVerse, and UniData differ in argument order and clauses | Note the dialect; verify the exact form in that platform's manual; do not assume |
| Treating a `READ … ELSE` branch as an error path | `ELSE` on `READ`/`READNEXT` is the normal **not-found / end-of-list** path, not an exception | Read `ELSE` as "item missing" (`READ`) or "end of list" (`READNEXT`) |
| Ignoring `READU` lock balance | A locked read with no `WRITE`/`RELEASE` on every path **leaks the lock** until the process dies | Trace each `READU`/`READL` to a `WRITE`/`WRITEU`/`RELEASE` on **all** branches incl. error/`ELSE` |
| Assuming a fixed schema from the data, or that DICT items are one-to-one with attributes | The DICT is the schema (not the data); attributes can have no dict item, and several synonyms can describe one attribute | Decode the DICT to learn meaning; read the data to learn contents; expect synonyms and undocumented attributes |
| Reading `EXECUTE "…"` / `PERFORM "…"` as BASIC | The quoted argument is a **TCL / query** sentence, not BASIC | Parse the quoted string as the shell/query language; follow it into the query layer |
| Expecting a query optimizer to pick indexes | MultiValue access is item-id-hashed; "all where X" needs a select-list; U2 secondary indexes are **explicit** | Look for `SELECT`/`SSELECT` building lists and for explicitly-built indexes |
| Treating numeric-looking columns as typed numbers | Numbers are **strings**; precision/format comes from conversions (`MR`/`MD`) or BASIC math, with no DECIMAL type | Read the conversion code to learn the intended scale; do not assume a fixed precision or a typed NULL |

---

## 9. Quick Reference

```
DATA MODEL    file = DICT + DATA ; record = item ; key = item-id (@ID = attr 0)
MARKS         @IM 255 ^  | @FM/@AM 254 ^  | @VM 253 ]  | @SM 252 \  | @TM 251
DYNAMIC ARR   REC<a>        attribute (^)        REC<a,v>   value (])
              REC<a,v,s>    sub-value (\)        REC<-1>=x  append a field
              DCOUNT(REC,@FM) count attrs ; REMOVE x FROM REC SETTING p (walk)
FILE I/O      OPEN..TO..ELSE ; READ/READU(lock)/READL/READV(1 attr)/MATREAD..THEN..ELSE
              WRITE/WRITEU(keep lock)/WRITEV/MATWRITE ; DELETE ; RELEASE
SELECT LOOP   SELECT f TO list ; LOOP / READNEXT id ELSE EXIT / READ rec FROM f,id / REPEAT
CONVERSIONS   OCONV(internal->display) ICONV(display->internal) ; dates = days since 31-Dec-1967
FLOW          IF..THEN..END..ELSE ; BEGIN CASE..CASE..END CASE (CASE 1 = default)
              GOSUB label..RETURN ; LOOP..WHILE/UNTIL..REPEAT ; FOR..NEXT
MODULAR       SUBROUTINE/CALL ; CALL @var (indirect) ; COMMON ; EXECUTE/PERFORM "tcl"
              CHAIN "tcl" (no return) ; ENTER (no return, LIKELY)
DICT TYPES    D stored | I computed(U2) | A/S classic | V virtual | X control | PH phrase
DICT LAYOUT   classic/D3: attr1 type, 2 AMC, 7 conv, 8 correlative   [DETECT DIALECT]
              U2 D-type:  field1 D, 2 attr#, 3 conv, 4 heading       [DIFFERENT]
JOIN          TRANS(file,key,attr,ctrl) / Tfile correlative = the SQL-JOIN substitute
LAYERS        TCL (shell/verbs) | query lang (RetrieVe/UniQuery/ACCESS) | BASIC (compiled)
DIALECTS      U2=UniVerse(UniVerse BASIC)+UniData(UniBasic) | D3/Reality(Pick BASIC)
              jBASE(jBC) | OpenQM/ScarletDME(QMBasic)
LOCKS         READU..WRITE/WRITEU/RELEASE ; READU with no release on a path = lock-leak bug
```

---

## Related Skills

| Skill | When to use |
|---|---|
| `cobol-developer` | The other legacy procedural-language comprehension reference (COBOL on the mainframe) |
| `datastage-developer` | DataStage ETL — the third member of the legacy-comprehension family |
| `legacy-code-intel` | Build a persistent symbol graph / navigator over Pick BASIC (and COBOL / DSX / ETL) |
| `lineage-extract-static` | Extract data/process lineage across Pick artifacts (OpenLineage output) |
| `python-enterprise-connectors` | Connect Python to enterprise data sources (when bridging Pick data out) |

---

## Provenance and confidence

Every concrete claim above is tagged from the source grounding (two independent web-grounded research arms, cross-checked):
- **[VERIFIED]** — multiple sources including a tier-1 vendor source; both independent grounding arms agreed. Examples: the mark code points (255/254/253/252/251), `OCONV`/`ICONV` direction, the 31-Dec-1967 date epoch, dictionary types, `TRANS`/`Tfile` as the JOIN substitute, the three-layer language split.
- **[LIKELY]** — two sources or one tier-1; high confidence but verify in the target system. Examples: classic-Pick attrs 3/9/10, U2 fields 5-7, `ENTER`, `V`-type dict items, `@USERNO`/`@WHO` names.
- **[UNCERTAIN]** — flagged; do NOT generalize (e.g. mark codes below 251).

The two genuinely **dialect-dependent** divergences are surfaced explicitly rather than smoothed over: the **classic-Pick vs U2 dictionary layout** (§4, conversion is attr-7 classic vs field-3 U2; computation is an attr-8 correlative classic vs an I-descriptor U2) and the **`LOCATE` / `INS` / `DEL` syntax** (§3). When in doubt on either, read the actual dictionary / consult that platform's manual.
