---
name: ibm-mainframe
description: Use when working with IBM z/OS mainframe systems — JCL (Job Control Language) syntax and patterns, dataset types (sequential/PDS/PDSE/VSAM), IDCAMS utility, DFSORT/ICETOOL, ISPF navigation, TSO/REXX scripting, system utilities (IEBCOPY/IEBGENER/IEFBR14), RACF security basics, GDG (Generation Data Groups), SMS (Storage Management Subsystem), and z/OS fundamentals. Part of the ibm-mainframe skill family.
---

# IBM z/OS Mainframe Fundamentals

For enterprise Python connectors to mainframe systems (Zowe SDK, ibm_db, EBCDIC handling) see: `python-enterprise-connectors`.

<HARD-RULE>
Always specify DISP on every DD statement — omitting DISP defaults to (NEW,DELETE) which loses your data. Explicitly code DISP=(NEW,CATLG,DELETE) for new datasets or DISP=SHR for existing ones.
</HARD-RULE>

<HARD-RULE>
Never submit a job that creates datasets without verifying the SPACE allocation. Under-allocation causes S B37/D37/E37 abends; over-allocation wastes DASD. Always estimate record count, record length, and blocking factor before coding SPACE.
</HARD-RULE>

<HARD-RULE>
Always use COND or IF/THEN/ELSE to control step execution — unconditional execution after failures causes data corruption. A failed step that writes partial data followed by an unconditional step that reads it will propagate bad data downstream.
</HARD-RULE>

<HARD-RULE>
Never delete a VSAM cluster without checking SHAREOPTIONS and verifying no other jobs have it open. Deleting an in-use VSAM cluster causes S213 abends in other jobs and potential data loss. Use LISTCAT to check the cluster status first.
</HARD-RULE>

---

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [datasets-idcams-dfsort.md](datasets-idcams-dfsort.md) | dataset types (sequential, PDS, PDSE, VSAM), IDCAMS utility, and DFSORT/ICETOOL |
| [ispf-rexx-racf-patterns.md](ispf-rexx-racf-patterns.md) | ISPF navigation, TSO/REXX scripting, system utilities, RACF security, SMS storage management, and practical JCL patterns |
| [zos-jcl.md](zos-jcl.md) | z/OS fundamentals, JCL syntax and patterns (JOB, EXEC, DD statements, procedures, conditional execution, GDGs) |

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Submitting JCL without testing with TYPRUN=SCAN | Syntax errors consume job queue slots and waste batch window time before failing | Always validate JCL syntax with TYPRUN=SCAN or JCL checker before production submission |
| Using default SPACE allocation without growth estimates | Under-allocated datasets get B37/D37 abends mid-job; over-allocated wastes DASD across the complex | Calculate space from record length, volume, and growth; use RLSE to return unused space |
| Hardcoding dataset names without high-level qualifier substitution | Jobs break when migrated between LPAR/environments; manual editing of DSNs is error-prone | Use symbolic parameters and system symbols for HLQ; parameterize environment-specific DSNs |
| Not running IDCAMS VERIFY after abnormal job termination | VSAM datasets left in an inconsistent state; subsequent jobs get locked-out or corrupt data | Always run IDCAMS VERIFY on VSAM clusters after abend recovery before restarting dependent jobs |
| Ignoring return codes and condition codes in JCL | COND parameter misuse causes steps to run (or skip) unexpectedly; silent data corruption | Use IF/THEN/ELSE/ENDIF for clear condition handling; check RC after every step in multi-step jobs |

---

## Related Skills

| Topic | Skill |
|---|---|
| Python connectors to z/OS (Zowe SDK, ibm_db, EBCDIC) | `python-enterprise-connectors` |
| DB2 for z/OS administration | `db2-mainframe` |
