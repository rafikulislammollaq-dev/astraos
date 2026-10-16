# One store, one launcher

Blueprint, October 2026. Status: **proposed.** Nothing here is implemented, and
no built image offers anything like it. The roadmap stage is Stage 5; what
exists today is in [`../../README.md`](../../README.md).

## The promise

A person searches once and installs anything — a Linux program, a Flatpak, a
Windows program through Wine, a web app — without ever having to learn "is
this compatible?". Whatever runs, runs sandboxed, can be removed cleanly, and
never hides where it came from.

## How it works

One search front over four sources, which stay independently updateable:

1. **Debian packages** — the system's own, through the existing APT stack.
2. **Flatpak** — already configured against Flathub system-wide in the image.
3. **Windows programs through Wine** — Wine and winetricks already ship; each
   program gets its own prefix and is managed like any other installed item.
4. **Web apps** — a URL wrapped in a window with its own launcher icon.

Every result is a card that states plainly: the source, the size, the
permissions it asks for, its license, and a support label — **works / works
with caveats / not yet**. The label is not editorial: it comes from CI, which
installs, launches and screenshots a growing list of popular applications on
every build, per source.

The origin badge never disappears: you never *have* to think about where a
program came from, but you can always *see* it. Hiding provenance is a
cloud-store pattern; showing it is the point.

Android applications are a separate, honest story: an "experiments" shelf,
opt-in, labeled — see [PHONE_LINK.md](PHONE_LINK.md).

## Honest boundaries

- Wine runs many Windows programs well and many others badly; the store says
  which is which, from tests, not hope. "It just runs" is never printed
  without the CI run behind it.
- The store does not bundle proprietary applications behind anyone's back;
  where a vendor ships its own repository or Flatpak, the store points to it
  and says exactly what is happening.
- Sandboxing is per-application but not absolute: Flatpak permissions and
  Guard policy reduce reach; they do not turn a program into a different
  program.
- Removal means removal: no leftover prefixes, registry fragments or tray
  agents — a test asserts an uninstalled application leaves nothing behind.

## How this gets proven

- A CI matrix job: for a defined list of popular applications per source,
  install, launch headless where possible, screenshot the rest, update the
  label table, and fail the label when a "works" entry stops launching.
- An uninstall test: install → use → remove → assert no files or services
  remain.
- The label table becomes part of the proof page (roadmap Stage 7).
