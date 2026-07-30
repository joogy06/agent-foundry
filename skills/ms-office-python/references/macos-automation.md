# macOS: automating Office, and choosing a route that works on both OSes

<!-- REVIEW-BY: 2027-01-31 -->
**Verified 2026-07-29.** Covers the macOS half of the family's platform story, and the
cross-platform decision that should usually be made *instead of* platform automation.

## 1. The one-line summary

**On Windows, driving installed Office means COM (`pywin32`). On macOS, it means Apple Events —
a different mechanism with different failure modes, not a port of the same thing.** Code that
`Dispatch("Excel.Application")` on Windows has no macOS equivalent to fall back to; the Mac path
goes through AppleScript's Open Scripting Architecture via the `appscript` bridge.

**Most workflows should avoid both.** See §5.

## 2. Route selection — start here

| Route | Windows | macOS | Linux / CI | Needs Office installed |
|---|---|---|---|---|
| **`openpyxl` / `python-docx` / `python-pptx`** | ✅ | ✅ | ✅ | **No** |
| **Microsoft Graph** (`msgraph-sdk`) | ✅ | ✅ | ✅ | No — cloud-side |
| **Office Scripts** (TypeScript, cloud) | ✅ | ✅ | ✅ (web) | No |
| **LibreOffice headless** (`soffice`) | ✅ | ✅ | ✅ | No (needs LibreOffice) |
| **`xlwings`** | ✅ COM | ✅ **appscript** | ❌ | **Yes** |
| **`docx2pdf`** | ✅ COM | ✅ AppleScript | ❌ | **Yes** |
| **`pywin32` COM** | ✅ | ❌ **none** | ❌ | Yes |
| **VBA macros** | ✅ | ⚠️ partial | ❌ | Yes |

**The file-format libraries are the default for a reason: they are the only row that is green
everywhere and needs nothing installed.** Reach past them only for something they genuinely cannot
do — Word-exact pagination, live recalculation of a complex model, macro preservation.

## 3. The macOS automation stack

```bash
# Prerequisite: appscript compiles against Apple's toolchain
xcode-select --install            # Command Line Tools — required to BUILD appscript
python3 -m pip install xlwings    # pulls appscript + psutil on macOS
```

- **`xlwings` on macOS uses AppleScript via `appscript`**, not COM. The Python API is largely the
  same, which is what makes the difference easy to miss until it fails at runtime.
- **`appscript` needs Xcode Command Line Tools to build from source.** On a fresh Mac this is the
  first failure, and its error message is about compilers, not about Office.
- **`python3` on a clean macOS is a stub** that pops the "install command line developer tools"
  dialog. In a script, on a managed Mac, or over SSH, that dialog is a hang rather than a prompt.
  Install the tools deliberately, or use a Homebrew or `uv`-managed Python.

### Apple Events permission — the macOS equivalent of "COM fails on Linux"

**The first time your Python process tries to drive Word or Excel, macOS shows a TCC consent dialog:
*"Terminal wants access to control Microsoft Excel."* Until someone clicks Allow, the call fails.**

- The grant is **per controlling application** — Terminal, iTerm, VS Code and a `launchd` daemon are
  four separate grants. Working in Terminal proves nothing about the same code under CI.
- Review or reset:
  ```bash
  # System Settings → Privacy & Security → Automation
  tccutil reset AppleEvents                      # reset all Apple Events grants
  sudo tccutil reset AppleEvents com.apple.Terminal
  ```
- **There is no headless grant.** A CI runner or a `launchd` job with no logged-in user cannot be
  prompted, so the automation simply does not work there. **This is the macOS mirror of the family's
  standing rule that COM fails on Linux** — detect and route around it rather than discovering it in
  production.
- **On a managed Mac, a PPPC profile can pre-grant it** — and can equally forbid it. If the dialog
  never appears *and* the call fails, that is policy, not a bug (`macos-cheatsheet` §4).

### Office for Mac is sandboxed

Word, Excel and PowerPoint for Mac run in App Sandbox containers under
`~/Library/Containers/com.microsoft.Word/` and siblings.

- **A path your script can read is not necessarily a path Office can open.** Files under
  `~/Downloads`, external volumes or network mounts may require the app's own grant.
- Prefer paths under the user's home that the app has already been given access to, and **pass
  absolute paths** — relative paths resolve against the container, not your working directory.
- Automation-created files may land inside the container rather than where you expected. Verify the
  written path rather than assuming it.

## 4. Format conversion on macOS

```bash
brew install --cask libreoffice
soffice --headless --convert-to pdf --outdir /tmp input.docx
```

- **`docx2pdf` works on macOS** (it drives Word via AppleScript) and therefore inherits everything
  in §3: Word installed, Apple Events granted, a logged-in user.
- **LibreOffice headless is the portable choice** — same command on macOS, Linux and Windows, no
  Office, no consent dialog, works in CI. Fidelity is close but not Word-identical, which matters for
  pagination-sensitive output and rarely otherwise.
- On Apple silicon, `soffice` lives under `/opt/homebrew`; a hard-coded `/usr/local/bin/soffice`
  from an Intel machine silently fails to resolve.

## 5. The cross-platform routes worth preferring

**Microsoft Graph** — already covered by `ms-office-graph-python`. Operates on files in
OneDrive/SharePoint from any OS with no Office installed and no consent dialogs. **If the documents
already live in M365, this is usually the right answer on both platforms.**

**Office Scripts** — TypeScript, stored in OneDrive/SharePoint, runs on Excel for Windows, Mac, web
and through Power Automate. It is the genuinely cross-platform successor to VBA for Excel:

| | VBA | **Office Scripts** |
|---|---|---|
| Platforms | Windows desktop only | Windows · macOS · web |
| Location | Inside the `.xlsm` | Cloud, linked to the workbook |
| Offline | ✅ | ❌ requires connectivity |
| Power Automate | ❌ | ✅ |
| Coverage | Full desktop object model | **Not yet 100% of desktop Excel** |

**The realistic recommendation is hybrid**: Office Scripts for new cross-platform and cloud
automation, VBA retained only for offline or legacy-critical paths. **Do not port working VBA to
Office Scripts on principle** — the object-model coverage gap is real, and the migration earns its
cost only when the workflow actually needs to run on Mac, web or Power Automate.

## 6. Pre-flight for any Office automation

```python
import sys, shutil

def office_automation_route():
    """Return the automation route available here, or None. Never assume."""
    if sys.platform == "win32":
        return "com"                     # pywin32 / xlwings COM — needs Office installed
    if sys.platform == "darwin":
        return "appleevents"             # xlwings via appscript — needs Office + TCC grant + a user
    return None                          # Linux: no live-Office route exists

route = office_automation_route()
if route is None or not shutil.which("soffice"):
    ...  # fall back to openpyxl / python-docx / python-pptx, or Graph
```

**Decide the route explicitly and log it.** The family's recurring failure is a pipeline that works
on one developer's machine and fails elsewhere for a reason the traceback does not name — a missing
COM on Linux, a missing consent grant on a Mac CI runner, a missing Office install anywhere.

## 7. Anti-patterns

- **Assuming `xlwings` works the same way on both platforms** because the Python API matches — COM
  and Apple Events fail differently.
- **Expecting Apple Events automation to work headlessly.** There is no unattended grant.
- **Granting automation in Terminal and assuming CI inherits it.** The grant is per controlling app.
- **Hard-coding `/usr/local` Homebrew paths** on Apple silicon.
- **Relative paths into sandboxed Office apps.**
- **Reaching for live automation** when `openpyxl` / `python-docx` / `python-pptx` or Graph would do.
- **Porting VBA to Office Scripts wholesale** without checking the object-model gap.
- **Treating "works on my Mac" as cross-platform evidence.**
