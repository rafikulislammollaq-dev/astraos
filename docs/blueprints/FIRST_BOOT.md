# First boot: "What are you coming from?"

Blueprint, October 2026. Status: **proposed.** Nothing in this document is implemented,
and no built image has offered anything like it. The roadmap stage is
[Stage 5](../ROADMAP.md), "Come as you are".

## The promise

The first five minutes on an installed system feel like a home, not a workshop.
One question, one confirmation screen, and the computer already fits: the layout
a person knows, their files and bookmarks where they expect them, and not a
single demand to learn something first. Skippable, offline, reversible.

## How it works

### The question

The installed system's first login asks one question, with six answers, then one
confirmation screen:

> **What are you coming from?**
> Windows · macOS · A phone (Android or iPhone) · Linux, familiar (Mint, Ubuntu,
> Debian) · Linux, power user (Arch, Fedora, Kali, openSUSE) · Just show me around

The confirmation screen lists exactly what is about to happen ("[Edit] [Set it
up]"). No account, no network, no second questionnaire; the flow is skippable
with one click and works entirely offline. The answer only sets defaults —
everything it chooses can be changed later from one settings panel, because it
is a preset, not a commitment.

### A layout that already fits

| Answer | Layout | Shortcuts |
|---|---|---|
| Windows | one bottom panel, menu button, task buttons | Super opens the menu; Win+E, Win+D, Alt+Tab behave as expected |
| macOS | top bar and a dock | Command-like bindings where X11 allows them; a true global menu bar is *not faked* |
| A phone (Android or iPhone) | app-grid launcher, large targets, dock as home; the on-screen keyboard enables itself on touchscreens | back/recents-style gestures only where they are reliable |
| Linux, familiar | the classic double panel; nothing surprising | unchanged |
| Linux, power user | terminal on Super+Enter, workspace keybindings, and an *offer* to install i3 — opt-in, with a plain list of what changes | tiling is optional; power does not mean tiling |
| Just show me around | the AstraOS default | |

These are profiles, not modes: nothing is hidden or unavailable in any of them,
and switching later is one panel. The "modes" idea of separate OS personalities
is deliberately not implemented — five personalities would mean five systems to
test and secure; profiles plus Packs answer the same wish without the test
matrix.

### Your things — copied, never moved

Every import is a **copy**; the source stays untouched and is mounted read-only.
Each item is listed with its size before anything happens, and a report records
what was copied and what was skipped.

- **Windows**: user folders (Documents, Desktop, Pictures, Music, Videos) from
  detected Windows partitions; browser bookmarks from Chrome, Edge or Firefox
  profiles (imported once the matching browser is installed); the wallpaper;
  the keyboard layout if it can be determined.
- **macOS**: HFS+ partitions can be read. **APFS cannot be read by Linux today,
  and the screen says exactly that** instead of failing later.
- **A phone**: photos and files over USB (MTP) now; automatic over-Wi-Fi backup
  arrives with Astra Link (Stage 5), not in the first version. The phone pairing
  page is browser-based, so iPhones reach it too, within Apple's limits.
- **Linux**: documents from another home folder; a *dotfiles repository URL*
  field for people who keep their configs in git; config copying shows the list
  of files it would overwrite first.

### The assistant, asked once

The same screen offers the local assistant — **unselected by default** — saying
exactly what it would download, how large it is, and that it runs offline (the
model is never in the ISO). Declining changes nothing else.

### Design rules (binding)

1. **One question, one confirmation.** Every additional question is a person
   lost.
2. **Copy, never move; read, never write** the source system.
3. **Skippable and reversible.** Skip means the AstraOS default; every choice
   reappears in one panel later.
4. **Offline.** No account, no network requirement; imports read local files.
5. **Honest labels.** "Works / works with caveats / not yet" comes from tests;
   an unavailable capability is named before it is needed, not discovered
   after.
6. **The answer is never telemetry.** What someone picked stays on the machine.

## Honest boundaries

- **No password import.** Browsers keep passwords in OS-encrypted stores;
  moving them silently is exactly the kind of magic this project refuses. The
  screen points to the user's own password manager for a deliberate
  export/import, and "we moved your passwords" is never printed because that
  never happens.
- No browser tab or session transfer unless the person deliberately copies a
  whole browser profile; the guide will show how. It is never silent.
- No Android-app streaming on the desktop. Waydroid and its relatives are real
  but partial; if this ever ships it is an opt-in experiment with an honest
  label, never a promise in the first-boot flow.
- Nothing here is claimed on physical hardware before it runs there; virtual
  machine results are labeled virtual machine results.

## How this gets proven

- A VM integration test (when the stage starts): install to a VM disk in CI,
  attach a small synthetic Windows fixture disk (files plus a browser profile),
  run the flow headlessly, then assert: the import report exists, the files
  exist in the new home, the fixture disk's checksums are unchanged, the
  desktop settings match the chosen profile, and no network traffic occurred
  during the flow.
- Screenshots of each layout and the confirmation screen join the boot
  self-test artifacts in CI.
- A reversal test: change every choice afterwards in the settings panel and
  assert the system returns to a defined state.

## Why this is the front door

Every later promise — Guard approvals, the research assistant, Astra Link,
Packs — is easier to trust for someone whose first five minutes already felt
like home. The roadmap holds the schedule; this document holds the design.
