# Checker usage

```bash
python3 scripts/pc_check.py build.json [--use-case aaa-1440p] [--band 1200-2000] [--final] \
    [--bands caller-bands.json] [--psu-catalog 550,650,750,850,1000,1200]
python3 scripts/pc_check.py page.json --publish-gate [--today YYYY-MM-DD] [--max-price-age-days 7]
python3 scripts/pc_check.py - --context-gate --use-case <id> --band <id> --workload "<text>"
python3 scripts/refresh_awacy.py   # refresh the Linux anti-cheat snapshot (30/60-day guard)
```

| Mode | Use it for | Exit codes |
|---|---|---|
| check (default) | Drafting and diagnosis. A missing input is WARN "cannot check", naming the fields | 0 no HARD, 2 HARD, 3 bad input |
| `--final` | Anything a customer will see. Unknown fields are rejected; a HARD check that could not run makes the result **incomplete** | 0, 2 HARD, 3 incomplete or bad input |
| `--publish-gate` | An `our-pick.v1` page: re-checks its build in `--final`, recomputes the VAT-inclusive total, checks price date, band, required fields and claims evidence | 0 publishable, 2 blocked, 3 bad input |

- **Input:** `schemas/build.v1.json`: component records projected from the caller's database. Numbers must be finite; `ram.module_capacity_gb` is per module.
- **Output:** `schemas/findings.v1.json`: `findings[]` of `{id, severity, message, source}`, `incomplete[]`, `recommended_psu_w` and `psu_sizing`; plus `publish_blockers[]` from the gate.
- **Missing data is never a pass.** Standard library only; tests: `python3 -m unittest discover -s tests`.

Severities: **HARD** the build cannot work; **WARN** it works but worse, or a check could not run; **INFO** page context.

Other flags: `--today` (the date the staleness and price-age checks use; default: the system date), `--awacy FILE` (override the anti-cheat snapshot), `--rules FILE`.

## Reading findings

1. HARD: the build cannot ship; change the later part in the dependency order unless the earlier part is the error.
2. WARN "cannot check": fetch the missing field; promise nothing. Under `--final` it blocks when the rule is HARD.
3. WARN with a measured loss: state the loss and its conditions.
4. INFO: page context (bracket, EXPO profile, iGPU class).

## OS builds (SteamOS / Linux)

Set `os` (`windows` | `steamos` | `linux`) and, for Linux, `distro`, `kernel`, `mesa`, `secure_boot`, `wifi.chip`; for SteamOS, `dual_boot`, `branding`, `valve_licence`; for the buyer, `buyer.games[]` and `buyer.wants[]`. With `os` absent (Windows) no OS rule runs. `buyer.games` is checked against `data/awacy-snapshot.json` (a trimmed Are We Anti-Cheat Yet copy, refreshed by `scripts/refresh_awacy.py`); a Denied or Broken title is HARD.
