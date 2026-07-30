# VS Code across macOS, Windows and Linux

<!-- REVIEW-BY: 2027-01-31 -->
**Verified 2026-07-29.** What differs per platform when running the foundry-lab arm in VS Code with
GitHub Copilot.

## 1. What is portable, and what is not

**Portable — no per-platform work needed:**

- **Skills.** `~/.claude/skills/` is auto-discovered; there is no bridge and no path to configure.
- **Everything `install.py` places**: `AGENTS.md`, `.vscode/tasks.json`, `.vscode/mcp.json`,
  `.github/agents/*.agent.md`, `.github/prompts/*.prompt.md`. All workspace-relative.
- **Copilot itself.** Identical behaviour on all three; only the keybindings differ.
- **`.agent.md` frontmatter** — `model:`, `tools:`, `agents:`, `handoffs:` are platform-independent.

**Not portable — the three things to get right:**

1. The **user-settings directory** (§2)
2. The **`code` CLI**, which is not on `PATH` by default on macOS (§3)
3. The **Python interpreter name** in tasks (§4)

## 2. User-level configuration paths

| | Path |
|---|---|
| **macOS** | `~/Library/Application Support/Code/User/` |
| **Windows** | `%APPDATA%\Code\User\` |
| **Linux** | `~/.config/Code/User/` |
| **Remote/SSH** | `~/.vscode-server/data/User/` |

Profiles live under `<User>/profiles/<profile-id>/` on every platform.

**`vs-code/scripts/detect_models.py` already resolves all four** — it is the reference implementation
for anything else that needs to find VS Code's configuration.

**Insiders substitutes `Code - Insiders` for `Code`.** A script that finds nothing on a machine
where VS Code plainly works is usually looking in the stable directory on an Insiders install.

## 3. The `code` CLI

**On macOS the `code` command is NOT installed by default** — the Windows installer offers to add it
to `PATH`, and most Linux packages do it automatically, but the Mac app does not.

> Command Palette (`⇧⌘P`) → **Shell Command: Install 'code' command in PATH**

Then restart the terminal so the new `PATH` takes effect. Without this, every `code .` in
documentation, scripts and READMEs fails on a Mac with `command not found` — which reads as a broken
instruction rather than a one-time setup step.

```bash
# Verify, and the manual fallback if the palette command is unavailable (e.g. locked-down Mac)
code --version
ls -l "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
```

Useful either way:

```bash
code --profile "foundry" .        # open with a named profile
code --list-extensions
code --status
```

## 4. Tasks and the Python interpreter

`tasks.json` uses per-platform overrides, because the interpreter is not called the same thing
everywhere:

```jsonc
"command": "python3",          // macOS + Linux
"windows": { "command": "py" } // Windows launcher
```

**On Windows `python3` is frequently absent** (and may resolve to a Microsoft Store stub that opens
the Store instead of running anything). `py`, the official launcher, is the reliable name.

**On a clean macOS, `/usr/bin/python3` is a stub** that triggers the "install command line developer
tools" dialog on first use. In an automatic `folderOpen` task that surfaces as a hang or a silent
failure, not a prompt. Either install the Command Line Tools deliberately:

```bash
xcode-select --install
```

or point tasks at a real interpreter (Homebrew, `uv`, pyenv) via `${command:python.interpreterPath}`.

## 5. Keyboard

| Action | macOS | Windows / Linux |
|---|---|---|
| Command Palette | `⇧⌘P` | `Ctrl+Shift+P` |
| Quick Open | `⌘P` | `Ctrl+P` |
| Copilot inline chat | `⌘I` | `Ctrl+I` |
| Accept suggestion | `Tab` | `Tab` |
| Toggle terminal | `⌃\`` | `` Ctrl+` `` |
| Settings (JSON) | `⌘,` then the JSON toggle | `Ctrl+,` |

**`⌘` replaces `Ctrl` for nearly everything**, but the integrated terminal keeps `⌃C`/`⌃D` as
control codes — which is why `⌘C` copies while `⌃C` interrupts, in the same panel.

## 6. macOS-specific friction worth knowing

- **Gatekeeper on first launch.** A VS Code copied rather than installed may be quarantined; `xattr -l`
  on the app bundle shows it (`macos-cheatsheet` §4).
- **Managed Macs may block extension installation** or force an extension allow-list via MDM. An
  extension that "won't install" with no useful error is usually policy — check
  `/Library/Managed Preferences/`.
- **Full Disk Access.** VS Code, or the terminal it spawns, may need it to read protected locations.
  System Settings → Privacy & Security → Full Disk Access.
- **Case-insensitive filesystem by default.** `import ./Utils` resolving locally and failing in Linux
  CI is a macOS-authored bug, and one of the most common cross-platform breakages.
- **Apple silicon Homebrew prefix is `/opt/homebrew`**, so a `PATH` or `settings.json` copied from an
  Intel Mac silently resolves nothing.

## 7. Anti-patterns

- **Documenting `code .`** without saying it needs installing on macOS first.
- **Hard-coding `~/.config/Code/User`** as *the* settings path.
- **Assuming `python3` exists on Windows**, or that it is real on a fresh Mac.
- **Copying `PATH` settings between Intel and Apple silicon Macs.**
- **Treating a blocked extension as a bug** on a managed Mac instead of reading the profile.
- **Testing cross-platform behaviour only on a case-insensitive filesystem.**
