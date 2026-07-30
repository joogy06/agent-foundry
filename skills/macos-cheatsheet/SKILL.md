---
name: macos-cheatsheet
description: Use when working on a Mac and needing the fast answer — console commands for system, files, network, processes, packages, defaults, launchd and logs, the BSD-versus-GNU differences that break Linux muscle memory, essential keyboard shortcuts and the Windows-to-Mac key mapping, and how to inspect and understand an enterprise-managed Mac (MDM enrollment type, supervision, configuration profiles, SIP/FileVault/Gatekeeper state, what IT can and cannot actually see, and what you will be blocked from doing).
disambiguation: macOS — the console, the desktop, and the managed-device layer. Windows shells are windows-cmd / windows-powershell; Linux server administration is ubuntu-server-admin / rhel-server-admin; Active Directory and enterprise SSO are windows-ad-admin / windows-sso; hardening an LLM or app running on the machine is not this skill.
---

# macOS cheat sheet

<!-- REVIEW-BY: 2027-01-31 -->
**Verified 2026-07-29. Current release: macOS 26 "Tahoe", latest 26.6 (27 July 2026).**

**macOS 26 is the final release supporting Intel Macs** — future releases are Apple-silicon only, with
Intel machines receiving security patches rather than features. On a corporate fleet that is a
hardware-refresh deadline, not a footnote.

## 1. What am I on?

```bash
sw_vers                                   # ProductName / ProductVersion / BuildVersion
uname -m                                  # arm64 = Apple silicon · x86_64 = Intel
sysctl -n machdep.cpu.brand_string        # CPU
system_profiler SPHardwareDataType        # model, chip, memory, serial
system_profiler SPSoftwareDataType        # OS, uptime, boot volume
ioreg -l | grep IOPlatformSerialNumber    # serial only
```

**`arm64` vs `x86_64` changes real answers** — Homebrew's prefix, whether Rosetta is involved, which
binaries run natively:

```bash
softwareupdate --install-rosetta          # Intel translation on Apple silicon
arch -x86_64 /bin/zsh                     # force an x86_64 shell
```

## 2. Is this Mac managed? — the question that determines everything else

**Run this first on any corporate machine.** Every "can I…" answer downstream depends on it:

```bash
profiles status -type enrollment
# → Enrolled via DEP: Yes|No
#   MDM enrollment: Yes (User Approved)|Yes|No
```

`Enrolled via DEP: Yes` means **Automated Device Enrollment** — the Mac was claimed by the
organisation in Apple Business Manager before you opened the box. That implies **supervision**, and a
management profile **you cannot remove**.

| Enrollment | Owned by | Removable by you | Control level |
|---|---|---|---|
| **None** | You | n/a | Full |
| **User enrollment** | You (BYOD) | **Yes** | Deliberately light, privacy-preserving |
| **Device enrollment** (manual) | Either | Usually yes | Moderate |
| **ADE / supervised** | The organisation | **No** | Highest — restrictions, silent installs, remote wipe |

### Inspecting the management layer

```bash
sudo profiles list -all                   # every installed configuration profile
sudo profiles list -output /tmp/p.txt     # dump for reading
profiles show -type enrollment            # enrollment detail
sudo profiles renew -type enrollment      # re-pull the enrollment (fixes some drift)

# What the MDM is doing, live and historically
log show --predicate 'subsystem == "com.apple.ManagedClient"' --last 2h
log stream --predicate 'subsystem == "com.apple.ManagedClient"'

# Management agents (Jamf shown; substitute your vendor)
sudo launchctl list | grep -iE 'jamf|intune|kandji|mosyle|fleet'
ls -la /Library/Managed\ Preferences/     # MDM-forced preference domains
jamf policy -verbose                      # force a Jamf check-in, if present
```

**`/Library/Managed Preferences/` is the honest answer to "why can't I change this setting?"** — a
value forced by profile there wins over anything you set, silently and permanently.

**Profiles are inspectable, and worth inspecting.** They are the actual policy — VPN, Wi-Fi,
certificates, restrictions, update deferrals, extension allow-lists — and reading them is faster than
asking why something is blocked.

## 3. What IT can and cannot see — the honest version

**The widely-repeated "MDM cannot see your personal data, it's a separate container" answer is about
BYOD/User Enrollment. It does not describe a corporate-owned supervised Mac, and repeating it there
is misleading.** The container model is an iOS/User-Enrollment construct.

| | **User enrollment (BYOD)** | **ADE / supervised, corporate-owned** |
|---|---|---|
| Personal files, photos, messages | **No** — separated by design | **No API for it — but see below** |
| Browsing history | No | No, *via MDM* |
| Installed applications | Managed apps only | **Full inventory** |
| Device identity, OS, compliance, encryption state | Yes | Yes |
| Location | Generally no | Possible via agent |
| **Run arbitrary code as root** | No | **Yes** — Jamf and equivalents run policies as root |
| Remote wipe | Work data only | **Entire device** |
| Screen observation | No | Possible with tooling and consent prompts |

**The distinction that matters: MDM is a protocol with defined limits; a management *agent* is
software running as root.** Almost every corporate Mac has both. MDM alone genuinely cannot read
your documents — but an agent that can execute a script as root can do whatever that script does, and
an EDR product is *designed* to inspect broadly.

**So the accurate statement is: on a corporate-owned managed Mac, assume anything on the device is
potentially visible to the organisation, and read your acceptable-use policy for what they have
committed to.** That is not paranoia; it is the correct default for a machine you do not own.

**Conversely, do not over-claim in the other direction.** On genuine BYOD user enrollment the
privacy separation is real and enforced by the OS. Telling someone their employer reads their
personal messages, when the enrollment type says otherwise, is equally wrong.

**Check which you have before answering anyone's privacy question** — including your own (§2).

### Where enterprise Mac management is heading

**Declarative Device Management (DDM) becomes the standard with the macOS 27 generation**, replacing
command-driven MDM: the server declares a desired state and the device continuously self-corrects
drift. **Legacy MDM software-update mechanisms are being removed in that release** — if you run a
fleet, the migration to DDM-based update enforcement is time-boxed, not optional.

## 4. Security posture — inspect from the console

```bash
csrutil status                            # System Integrity Protection — expect "enabled"
fdesetup status                           # FileVault full-disk encryption
spctl --status                            # Gatekeeper
system_profiler SPConfigurationProfileDataType | head -50
softwareupdate -l                         # available updates
sudo softwareupdate -ia --restart         # install all
```

**On a managed Mac these are usually enforced and not yours to change** — SIP disabled or FileVault
off will typically show as a compliance failure within minutes.

```bash
# Why won't this app open?
xattr -l /Applications/Foo.app            # look for com.apple.quarantine
spctl -a -vvv /Applications/Foo.app       # Gatekeeper assessment + reason
codesign -dv --verbose=4 /Applications/Foo.app   # signing identity, team id
xattr -d com.apple.quarantine ./foo       # remove quarantine — see the warning below
```

**Stripping the quarantine flag disables the check that exists to protect you.** Do it for a binary
you built or genuinely trust, never as a reflex to make a download run — and expect it to be blocked
or logged on a managed machine.

```bash
# Privacy (TCC) permissions — the "app can't access X" class of problem
sudo tccutil reset All com.example.app    # reset one app's grants
tccutil reset Camera                      # reset one category
```

**TCC prompts cannot be granted from the command line** — by design. On a managed Mac, PPPC profiles
pre-grant them; if an app is silently denied and never prompts, that is a profile, not a bug.

## 5. Everyday console

### Files and navigation

```bash
open .                          # reveal cwd in Finder
open -a "Visual Studio Code" f  # open with a named app
open -R /path/to/file           # reveal and select
pbcopy < file.txt               # file → clipboard
pbpaste > out.txt               # clipboard → file
mdfind -name 'report'           # Spotlight from the shell — fast, indexed
mdfind "kMDItemKind == 'PDF'"
ditto -V src/ dst/              # correct recursive copy (keeps resource forks/ACLs)
hdiutil attach image.dmg        # mount a dmg
du -sh * | sort -h              # sizes, largest last
```

**`mdfind` beats `find` for anything indexed** — it queries Spotlight rather than walking the tree.

### Network

```bash
ipconfig getifaddr en0                    # current IP, no parsing
networksetup -listallnetworkservices      # interfaces by friendly name
networksetup -getdnsservers Wi-Fi
scutil --dns                              # full resolver state
sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder   # flush DNS (both needed)
lsof -i -P | grep LISTEN                  # what is listening
nettop -m tcp                             # live per-process traffic
sudo tcpdump -i en0 -n port 443
```

**On a managed Mac, expect a VPN profile, forced DNS, and possibly a TLS-inspecting proxy.** A
mystery certificate error is usually that, and `security find-certificate -a -c "<CA name>"` will
show whether the corporate root is installed.

### Processes, power, disks

```bash
top -o cpu                                # -o mem for memory
ps aux | grep -i name
sudo fs_usage -w -f filesys | grep foo    # what is touching the disk
caffeinate -d                             # keep the display awake for this shell
pmset -g assertions                       # what is preventing sleep
diskutil list
diskutil info /                           # APFS container detail
df -h
```

### launchd — the macOS service manager

```bash
launchctl list                            # user agents
sudo launchctl list                       # system daemons
launchctl print gui/$(id -u)/com.example.agent
launchctl bootout gui/$(id -u)/com.example.agent   # stop+unload (modern)
```

| Path | Scope |
|---|---|
| `~/Library/LaunchAgents` | Your user, on login |
| `/Library/LaunchAgents` | All users, on login |
| `/Library/LaunchDaemons` | System, on boot, as root |

**`launchctl load/unload` is legacy**; `bootstrap`/`bootout` are current. Both appear everywhere
online, which is why the old ones fail confusingly on recent macOS.

### `defaults` — the preferences database

```bash
defaults read com.apple.finder
defaults write com.apple.finder AppleShowAllFiles -bool true && killall Finder
defaults delete com.apple.finder AppleShowAllFiles
defaults domains | tr ',' '\n'
```

**A `defaults write` that appears to do nothing is usually being overridden by a managed
preference** (§2) — or needs the owning app restarted.

### Packages

```bash
/opt/homebrew/bin/brew --version    # Apple silicon prefix
/usr/local/bin/brew --version       # Intel prefix
brew install --cask firefox
brew list --versions ; brew outdated ; brew upgrade
brew bundle dump --file=~/Brewfile  # capture; `brew bundle` to restore
softwareupdate --list-full-installers   # full macOS installers
```

**The prefix differs by architecture**, which is why a copied `PATH` from an Intel Mac silently fails
on Apple silicon. **`brew bundle dump` is the fastest machine-rebuild insurance there is.**

### Logs

```bash
log show --last 30m --predicate 'eventMessage CONTAINS "error"'
log stream --level debug --predicate 'process == "Safari"'
log show --style syslog --last 1h
```

**macOS has no `/var/log/syslog`.** The unified log is queried, not tailed — and `log show` without a
predicate returns an unusable volume.

### Screenshots and misc

```bash
screencapture -x shot.png       # silent full screen
screencapture -i -c             # interactive → clipboard
say "build finished"
uptime ; sw_vers ; whoami ; id
```

## 6. BSD, not GNU — where Linux habits break

**macOS ships the BSD userland.** These are the ones that actually cost time:

| Task | Linux (GNU) | **macOS (BSD)** |
|---|---|---|
| In-place sed | `sed -i 's/a/b/' f` | **`sed -i '' 's/a/b/' f`** — the empty arg is mandatory |
| File size | `stat -c %s f` | `stat -f %z f` |
| Date arithmetic | `date -d '+1 day'` | `date -v +1d` |
| Absolute path | `readlink -f p` | `realpath p` |
| Base64 decode | `base64 -d` | `base64 -D` |
| Sort by size | `du -sh * \| sort -h` | same, but BSD `sort -h` is present — check first |

```bash
brew install coreutils gnu-sed grep findutils   # GNU tools as g-prefixed: gsed, gstat, ggrep
```

**A shell script that works on Ubuntu and fails on a Mac is `sed -i` about half the time.** If a
script must run on both, use `gsed`, or avoid in-place editing entirely.

**Also:** the default shell is **zsh**, not bash (`~/.zshrc`, not `~/.bashrc`); `/bin/bash` is an old
3.2 for licensing reasons, so `brew install bash` if you need modern bash features; and the
filesystem is **case-insensitive by default**, which is why `import ./Utils` works locally and breaks
in CI.

## 7. Keyboard — the ones worth memorising

| | |
|---|---|
| `⌘ Space` | Spotlight — launch anything, calculate, convert |
| `⌘ Tab` / `⌘ \`` | Switch app / switch window **within** an app |
| `⌘ ⇧ 4` / `⌘ ⇧ 5` | Screenshot region / capture-and-record panel |
| `⌘ ⇧ .` | **Toggle hidden files in Finder** and in open/save dialogs |
| `⌘ ⌥ Esc` | Force quit |
| `⌃ ⌘ Space` | Emoji and symbol picker |
| `⌘ ⇧ G` | Go to folder (Finder) — type a path |
| `⌘ ⌥ D` | Toggle the Dock |
| `⌃ ⌘ Q` | Lock screen |
| `⌘ ,` | Preferences — **in every well-behaved app** |

**Windows → Mac mapping:** `Ctrl` → **`⌘`** for nearly every editing shortcut (copy, paste, save,
quit); `Alt` → `⌥`; `Home`/`End` → `⌘ ←` / `⌘ →`; Delete-forward → `fn ⌫`; `PrtScn` → `⌘ ⇧ 4`. The
`Ctrl` key still exists and is mostly for terminal control codes — `⌃C` still interrupts.

**In Terminal, enable "Use Option as Meta key"** or `⌥B` / `⌥F` word-movement does nothing.

## 8. On a managed Mac, expect to be blocked from

- Installing unsigned or non-notarised apps · disabling SIP, FileVault or Gatekeeper
- Deferring or skipping OS updates past the configured window
- Removing the management profile · changing forced network, DNS, VPN or proxy settings
- Local admin rights — often time-boxed and self-service rather than permanent
- Loading kernel or system extensions not on the allow-list

**Work with it rather than around it.** Circumvention on a supervised machine is usually detected,
frequently logged, and is a disciplinary matter rather than a technical one. **The productive move is
to read the profile, identify the exact restriction, and ask IT for a scoped exception** — a request
naming the payload and the business reason gets a far better response than "my Mac is broken".

## 9. Anti-patterns

- **Answering a privacy question without checking the enrollment type.** BYOD and supervised
  corporate ownership have genuinely different answers, in both directions.
- **Repeating the "separate container, they can't see anything" line** about a corporate-owned Mac.
- **Forgetting the management agent** when reasoning about what MDM can do — root is root.
- **Stripping `com.apple.quarantine`** reflexively to make a download run.
- **Disabling SIP** to solve a problem that has a supported solution.
- **`sed -i 's/…'`** in a script that has to run on macOS.
- **Assuming `/usr/local` is Homebrew's prefix** on Apple silicon.
- **`launchctl load`** on a recent macOS, then debugging the wrong error.
- **Hunting for `/var/log/syslog`** instead of querying the unified log.
- **Fighting a setting that a managed preference is forcing**, instead of reading the profile.
- **Assuming case-sensitivity** because it worked locally.
