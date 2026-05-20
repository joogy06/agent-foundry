#!/usr/bin/env python3
"""bootstrap-environment.py — Full Claude Code environment setup.

Idempotent orchestrator that completes a fresh-machine Claude Code install
beyond what `install.py` covers. Re-runnable safely; each step skips work
that's already done unless `--force` is passed.

Steps (in order):
  1. Run install.py        — skills / agents / commands placement
  2. Place CLAUDE.md       — global instructions
  3. AGENTS.md symlink     — Copilot reads this
  4. Place pa-server/      — MCP server source for the pa agent
  5. settings.json hooks   — SessionStart scan_hard_rules + forge_reminder
  6. policy-limits.json    — enterprise hard-cap defaults (mode 0600)
  7. claude-observe bin    — symlink convenience for process-observation
  8. Codex skill symlinks  — ~/.codex/skills/* parity (if codex installed)
  9. Gemini model pin      — ~/.gemini/settings.json (if file exists)
 10. Next-step summary     — /setup skill, pre-push hooks, MCP wiring

Usage:
    python3 bootstrap-environment.py                       # full bootstrap
    python3 bootstrap-environment.py --dry-run             # preview only
    python3 bootstrap-environment.py --skip-install        # skip step 1
    python3 bootstrap-environment.py --skip-codex          # skip step 8
    python3 bootstrap-environment.py --skip-gemini         # skip step 9
    python3 bootstrap-environment.py --force               # overwrite existing
    python3 bootstrap-environment.py --claude-home /custom # alt config dir

Exit codes: 0 OK, 1 fatal error, 2 partial (some steps skipped/failed).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# REPO_ROOT auto-detection:
# - When bundled at agent-foundry/ root: __file__'s parent has CLAUDE.md, pa-server/, skills/.
# - When run from skill_factory/installer/ in dev: those siblings live in the parent dir.
_HERE = Path(__file__).resolve().parent
if (_HERE / "CLAUDE.md").exists() or (_HERE / "skills").exists():
    REPO_ROOT = _HERE                         # bundled mode
elif (_HERE.parent / "CLAUDE.md").exists() or (_HERE.parent / "skills").exists():
    REPO_ROOT = _HERE.parent                  # dev mode (script lives in installer/)
else:
    REPO_ROOT = _HERE                         # fall back; steps will warn cleanly

# Canonical SessionStart hook entries that bootstrap ensures are present.
# Bootstrap MERGES these into existing settings.json; it does NOT remove
# user-added hooks (e.g. mobile notifications, Stop hooks, etc.).
CANONICAL_SESSION_START_HOOKS = [
    {
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": "python3 ~/.claude/skills/_meta/scan_hard_rules.py --hook",
            "timeout": 10,
        }],
    },
    {
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": "python3 ~/.claude/skills/_meta/forge_reminder_hook.py --hook",
            "timeout": 10,
        }],
    },
]

POLICY_LIMITS_DEFAULT = {
    "restrictions": {
        "allow_remote_control":            {"allowed": False},
        "allow_quick_web_setup":           {"allowed": False},
        "enforce_web_search_mcp_isolation": {"allowed": False},
    },
}

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

class Out:
    def __init__(self, dry_run: bool):
        self.dry_run = dry_run
        self.steps_ok = 0
        self.steps_skipped = 0
        self.steps_failed = 0

    def banner(self, msg):
        print()
        print("=" * 60)
        print(msg)
        print("=" * 60)

    def step(self, n, name):
        print()
        print(f"--- Step {n}: {name} {'(DRY RUN)' if self.dry_run else ''}")

    def info(self, msg):  print(f"  -> {msg}")
    def ok(self, msg):    print(f"  [OK] {msg}");      self.steps_ok += 1
    def skip(self, msg):  print(f"  [SKIP] {msg}");    self.steps_skipped += 1
    def fail(self, msg):  print(f"  [FAIL] {msg}", file=sys.stderr); self.steps_failed += 1
    def warn(self, msg):  print(f"  ! {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Bootstrap steps
# ---------------------------------------------------------------------------

class Bootstrap:
    def __init__(self, claude_home: Path, dry_run: bool, force: bool,
                 install_args: list[str]):
        self.claude_home = claude_home.expanduser().resolve()
        self.dry_run = dry_run
        self.force = force
        self.install_args = install_args
        self.out = Out(dry_run)

    # ----- step 1 -----------------------------------------------------------

    def step_1_install_skills(self):
        self.out.step(1, "skills / agents / commands placement (install.py)")
        installer = REPO_ROOT / "install.py"
        if not installer.exists():
            self.out.fail(f"install.py not found at {installer}")
            return
        cmd = [sys.executable, str(installer), "--noninteractive",
               "--target", "claude", "--claude-home", str(self.claude_home),
               *self.install_args]
        self.out.info(f"running: {' '.join(cmd)}")
        if self.dry_run:
            self.out.skip("--dry-run: install.py not invoked")
            return
        rc = subprocess.call(cmd)
        if rc == 0:
            self.out.ok("install.py completed")
        else:
            self.out.fail(f"install.py exit code {rc}")

    # ----- step 2 -----------------------------------------------------------

    def step_2_place_claude_md(self):
        self.out.step(2, "place ~/.claude/CLAUDE.md")
        src = REPO_ROOT / "CLAUDE.md"
        dst = self.claude_home / "CLAUDE.md"
        if not src.exists():
            self.out.warn(f"source not in repo: {src} — skipping")
            self.out.steps_skipped += 1
            return
        if dst.exists() and not self.force:
            try:
                if dst.read_text(encoding="utf-8") == src.read_text(encoding="utf-8"):
                    self.out.skip("CLAUDE.md already at canonical content")
                    return
            except (OSError, UnicodeDecodeError):
                pass
            self.out.skip(f"CLAUDE.md exists with different content — pass --force to overwrite ({dst})")
            return
        if self.dry_run:
            self.out.skip(f"would copy {src} -> {dst}")
            return
        self.claude_home.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        self.out.ok(f"copied -> {dst}")

    # ----- step 3 -----------------------------------------------------------

    def step_3_symlink_agents_md(self):
        self.out.step(3, "symlink ~/.claude/AGENTS.md -> CLAUDE.md")
        target = self.claude_home / "CLAUDE.md"
        link = self.claude_home / "AGENTS.md"
        if not target.exists():
            self.out.warn("CLAUDE.md missing — run step 2 first")
            self.out.steps_skipped += 1
            return
        if link.is_symlink() and link.resolve() == target.resolve():
            self.out.skip("AGENTS.md symlink already correct")
            return
        if self.dry_run:
            self.out.skip(f"would symlink {link} -> {target}")
            return
        try:
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(target)
            self.out.ok(f"symlinked {link} -> {target}")
        except OSError as e:
            # On Windows non-admin / no Developer Mode: fall back to copy.
            try:
                shutil.copy2(target, link)
                self.out.warn("symlink failed; copied AGENTS.md instead (drift risk if CLAUDE.md edits)")
                self.out.ok(f"copied -> {link}")
            except OSError as e2:
                self.out.fail(f"could not place AGENTS.md: {e2}")

    # ----- step 4 -----------------------------------------------------------

    def step_4_place_pa_server(self):
        self.out.step(4, "place ~/.claude/pa-server/")
        src_dir = REPO_ROOT / "pa-server"
        dst_dir = self.claude_home / "pa-server"
        if not src_dir.exists():
            self.out.warn(f"source not in repo: {src_dir} — skipping")
            self.out.steps_skipped += 1
            return
        if dst_dir.exists() and not self.force:
            # Idempotent: hash-compare the main file
            src_main = src_dir / "pa_server.py"
            dst_main = dst_dir / "pa_server.py"
            if src_main.exists() and dst_main.exists():
                try:
                    if src_main.read_bytes() == dst_main.read_bytes():
                        self.out.skip("pa-server/ already at canonical content")
                        return
                except OSError:
                    pass
            self.out.skip(f"pa-server/ exists with different content — pass --force to overwrite ({dst_dir})")
            return
        if self.dry_run:
            self.out.skip(f"would mirror {src_dir} -> {dst_dir}")
            return
        dst_dir.mkdir(parents=True, exist_ok=True)
        copied = 0
        for src_file in src_dir.rglob("*"):
            if any(p in src_file.parts for p in ("__pycache__",)):
                continue
            if not src_file.is_file():
                continue
            rel = src_file.relative_to(src_dir)
            dst_file = dst_dir / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            copied += 1
        self.out.ok(f"placed {copied} file(s) into {dst_dir}")

    # ----- step 5 -----------------------------------------------------------

    def step_5_settings_hooks(self):
        self.out.step(5, "merge SessionStart hooks into ~/.claude/settings.json")
        path = self.claude_home / "settings.json"
        settings = {}
        if path.exists():
            try:
                settings = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                self.out.fail(f"could not parse {path}: {e} — fix manually before re-running")
                return

        hooks = settings.setdefault("hooks", {})
        ss = hooks.setdefault("SessionStart", [])

        # Canonicalize: a hook is "already present" if its first hooks[0].command matches.
        existing_cmds = set()
        for entry in ss:
            for h in entry.get("hooks", []):
                cmd = h.get("command")
                if cmd:
                    existing_cmds.add(cmd)

        added = []
        for new_entry in CANONICAL_SESSION_START_HOOKS:
            new_cmd = new_entry["hooks"][0]["command"]
            if new_cmd in existing_cmds:
                continue
            added.append(new_cmd)
            ss.append(new_entry)

        if not added:
            self.out.skip("required SessionStart hooks already present")
            return

        if self.dry_run:
            for cmd in added:
                self.out.skip(f"would add hook: {cmd}")
            return

        self.claude_home.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup = path.with_suffix(".json.bak")
            shutil.copy2(path, backup)
            self.out.info(f"backup -> {backup}")
        path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        for cmd in added:
            self.out.info(f"added hook: {cmd}")
        self.out.ok(f"settings.json updated ({len(added)} new hook(s))")

    # ----- step 6 -----------------------------------------------------------

    def step_6_policy_limits(self):
        self.out.step(6, "place ~/.claude/policy-limits.json (skip if exists)")
        path = self.claude_home / "policy-limits.json"
        if path.exists() and not self.force:
            self.out.skip("policy-limits.json already present — leaving in place")
            return
        if self.dry_run:
            self.out.skip(f"would write defaults to {path}")
            return
        self.claude_home.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(POLICY_LIMITS_DEFAULT, indent=2), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass  # Windows doesn't honor POSIX mode bits
        self.out.ok(f"wrote {path} (mode 0600)")

    # ----- step 7 -----------------------------------------------------------

    def step_7_claude_observe_bin(self):
        self.out.step(7, "symlink ~/.claude/bin/claude-observe")
        target = self.claude_home / "skills" / "process-observation" / "scripts" / "write.py"
        bin_dir = self.claude_home / "bin"
        link = bin_dir / "claude-observe"
        if not target.exists():
            self.out.warn(f"target not present: {target} — install step 1 first")
            self.out.steps_skipped += 1
            return
        if link.is_symlink() and link.resolve() == target.resolve():
            self.out.skip("claude-observe symlink already correct")
            return
        if self.dry_run:
            self.out.skip(f"would symlink {link} -> {target}")
            return
        bin_dir.mkdir(parents=True, exist_ok=True)
        try:
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(target)
            self.out.ok(f"symlinked {link} -> {target}")
        except OSError as e:
            self.out.warn(f"symlink failed (likely Windows without Developer Mode): {e}")
            self.out.steps_skipped += 1

    # ----- step 8 -----------------------------------------------------------

    def step_8_codex_symlinks(self):
        self.out.step(8, "mirror skills to ~/.codex/skills/ (if codex installed)")
        if shutil.which("codex") is None:
            self.out.skip("codex CLI not on PATH — skipping")
            return
        skills_src = self.claude_home / "skills"
        codex_skills = Path.home() / ".codex" / "skills"
        if not skills_src.exists():
            self.out.warn(f"{skills_src} missing — run step 1 first")
            self.out.steps_skipped += 1
            return
        if self.dry_run:
            count = sum(1 for d in skills_src.iterdir() if d.is_dir())
            self.out.skip(f"would symlink {count} skill(s) into {codex_skills}")
            return
        codex_skills.mkdir(parents=True, exist_ok=True)
        added = 0
        excluded = 0
        for skill in skills_src.iterdir():
            if not skill.is_dir():
                continue
            # Sentinel: a skill that contains .no-codex-symlink at its root is
            # deliberately excluded from Codex mirroring. See
            # ~/.claude/skills/affordance-advisor/.no-codex-symlink for the
            # contamination rationale.
            if (skill / ".no-codex-symlink").exists():
                excluded += 1
                # Ensure any prior symlink is removed so the exclusion is honoured
                # on subsequent runs after the sentinel was added.
                stale = codex_skills / skill.name
                if stale.is_symlink() or stale.exists():
                    try:
                        stale.unlink()
                    except OSError:
                        pass
                continue
            link = codex_skills / skill.name
            if link.is_symlink() and link.resolve() == skill.resolve():
                continue
            try:
                if link.exists() or link.is_symlink():
                    link.unlink()
                link.symlink_to(skill.resolve())
                added += 1
            except OSError:
                continue
        total = sum(1 for _ in codex_skills.iterdir())
        suffix = f" (excluded by .no-codex-symlink: {excluded})" if excluded else ""
        self.out.ok(f"ensured {added} new Codex symlink(s); total: {total}{suffix}")

    # ----- step 9 -----------------------------------------------------------

    def step_9_gemini_settings(self):
        self.out.step(9, "pin Gemini model in ~/.gemini/settings.json")
        path = Path.home() / ".gemini" / "settings.json"
        if not path.exists():
            self.out.skip("~/.gemini/settings.json not present — install gemini-cli first")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            self.out.warn(f"could not parse {path}: {e}")
            return
        model = data.setdefault("model", {})
        target_name = "gemini-3.1-pro-preview"
        needs_write = False
        if model.get("name") != target_name:
            model["name"] = target_name
            needs_write = True
        if model.get("default") != target_name:
            model["default"] = target_name
            needs_write = True
        if model.get("fallback") != target_name:
            model["fallback"] = target_name
            needs_write = True
        if not needs_write:
            self.out.skip(f"Gemini model already pinned to {target_name}")
            return
        if self.dry_run:
            self.out.skip(f"would pin model.name/default/fallback = {target_name}")
            return
        backup = path.with_suffix(".json.bak")
        shutil.copy2(path, backup)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self.out.info(f"backup -> {backup}")
        self.out.ok(f"pinned to {target_name}")

    # ----- step 10 ----------------------------------------------------------

    def step_10_next_steps(self):
        self.out.step(10, "next steps")
        msgs = [
            "Recommended:",
            "  1. Review ~/.claude/settings.json permissions — defaults are conservative.",
            "     Run `/setup` inside Claude Code to upgrade to autonomous mode.",
            "  2. Wire pre-push secrets-scan hooks in your working repos:",
            "       bash scripts/install-pre-push-hook.sh <repo>      (POSIX)",
            "       pwsh -NoProfile -NonInteractive -File \\",
            "         scripts\\install-pre-push-hook.ps1 -TargetRepo <repo>   (Windows)",
            "  3. If using Codex CLI: ensure project dirs are trusted in ~/.codex/config.toml",
            "     (add `[projects.\"/path/to/dir\"]` entries — Codex won't run headless without).",
            "  4. If using gemini-cli: confirm the model pin with `gemini --version`.",
            "",
            "Re-run this script any time — every step is idempotent.",
        ]
        for m in msgs:
            print(m)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(
        description="Full Claude Code environment bootstrap.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="See bootstrap-environment.py docstring for the full step list.",
    )
    p.add_argument("--claude-home", default=str(Path.home() / ".claude"),
                   help="Claude config root (default: ~/.claude)")
    p.add_argument("--dry-run", action="store_true",
                   help="Preview changes without writing.")
    p.add_argument("--force", action="store_true",
                   help="Overwrite existing CLAUDE.md / pa-server / policy-limits.")
    p.add_argument("--skip-install", action="store_true",
                   help="Skip step 1 (install.py).")
    p.add_argument("--skip-codex", action="store_true",
                   help="Skip step 8 (Codex symlinks).")
    p.add_argument("--skip-gemini", action="store_true",
                   help="Skip step 9 (Gemini model pin).")
    p.add_argument("--install-arg", action="append", default=[],
                   help="Pass-through arg to install.py (repeatable).")
    args = p.parse_args()

    boot = Bootstrap(
        claude_home=Path(args.claude_home),
        dry_run=args.dry_run,
        force=args.force,
        install_args=args.install_arg,
    )

    boot.out.banner(
        f"Claude Code environment bootstrap\n"
        f"  repo:        {REPO_ROOT}\n"
        f"  claude_home: {boot.claude_home}\n"
        f"  mode:        {'dry-run' if args.dry_run else 'apply'}"
    )

    if not args.skip_install:
        boot.step_1_install_skills()
    boot.step_2_place_claude_md()
    boot.step_3_symlink_agents_md()
    boot.step_4_place_pa_server()
    boot.step_5_settings_hooks()
    boot.step_6_policy_limits()
    boot.step_7_claude_observe_bin()
    if not args.skip_codex:
        boot.step_8_codex_symlinks()
    if not args.skip_gemini:
        boot.step_9_gemini_settings()
    boot.step_10_next_steps()

    boot.out.banner(
        f"Summary: {boot.out.steps_ok} ok / "
        f"{boot.out.steps_skipped} skipped / {boot.out.steps_failed} failed"
    )
    if boot.out.steps_failed > 0:
        return 1
    if boot.out.steps_skipped > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
