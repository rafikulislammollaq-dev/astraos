# AstraOS roadmap

This document is the plan, not the current system. What exists today is in
[`README.md`](../README.md) (maturity table, "What has been tested") and
[`docs/KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md). Nothing below becomes a claim
until a run, a test or an artifact proves it, and the proof is recorded; the
`findiso` entry in [`CHANGELOG.md`](../CHANGELOG.md) is the standard for how a
failure is handled — recorded with its cause, not hidden.

The blueprints for the promised experiences — the first boot, profiles, one
store, roll-backable updates, the phone link, the system assistant, privacy,
reach, creator packs and the community rails — are in
[`docs/blueprints/`](blueprints/README.md). They are plans too. The long-horizon
pillars behind this direction — the mesh, the timeline, the canvas and the graph —
are designed there as well, beyond the stages.

The founding engineering brief for the distribution itself is
[`PROJECT_PLAN.md`](PROJECT_PLAN.md); this roadmap extends it for the AI-era
direction and does not replace it. The direction consolidates two external reviews
of this project's README (October 2026). Third-party details from those reviews —
model names, market figures, kernel versions — are leads to verify on this
project's own hardware, not facts.

## The goal

AstraOS should be the operating system for the PC people already own: **a private,
local-first AI computer that turns plain-language instructions into controlled,
verifiable work, with public proof that it works.** Not a chat window bolted onto a
desktop; not a cloud agent wrapper with a Linux theme.

Why this direction: Windows 10 support ended in October 2025 and many working PCs
cannot officially run Windows 11; today's most-cited "AI distros" route agent work
to cloud services by default; and cloud agent products have drawn privacy
criticism for reading and writing personal folders. Local-first, permissioned and
provable is a real position, and nobody has shipped it — this project's value is
proving it rather than asserting it.

## Principles

- **Local-first.** The default experience runs on this machine; cloud inference is
  optional, explicit, and says what would leave the computer.
- **Model-independent.** The desktop, networking and applications work fully with
  no model installed. The ISO ships none; nothing downloads one silently.
- **Hardware-adaptive.** Engine build, quantization and model rung are chosen from
  a measured capability profile. Old CPUs are the target, not a fallback.
- **Trust before power.** Permissions, sandboxing, auditing and undo exist before
  the assistant touches system state. The assistant is a guest on the machine.
- **Action-oriented.** The assistant produces artifacts and reports honestly what
  it did, what it could not do, and what it changed.
- **Come as you are.** People arrive with habits — from Windows, from Android, from
  Mint, Ubuntu, Arch or Kali, from Plasma. The OS adapts to them — layout,
  shortcuts, files, apps — instead of demanding retraining, and nothing locks them
  in. Nobody should ever have to leave because something was too hard, and nobody
  should ever have to stay because they're locked in.
- **Provable.** Every claim in the README is backed by a CI run, a test or an
  artifact. A failure is recorded as a failure.
- **Extensible.** Components are replaceable without changing the others; Debian
  stays the base, Xfce the desktop, and the assistant stays an application, not
  part of the base system.

## Component map (provisional names)

| Component | Responsibility | State |
|---|---|---|
| Astra Core | the distribution: packaging, desktop, boot, recovery | exists; maturity tracked in `README.md` |
| Astra Engine | local inference: `llama-server`, the model ladder, the JSON worker | partial: builds and runs in CI (emulated Sandy Bridge, 360M smoke model); no self-selection, no evaluations yet |
| Astra Guard | permissions, sandbox, audit log, undo | does not exist |
| Astra Runtime | task objects: plan → approve → execute → verify, persistence, resume | does not exist (`astra-ai work` is a single structured answer today) |
| Astra Vault | document index and user-approved memory | does not exist |
| Astra Missions | the task interface: plans, approvals, results | does not exist |
| Astra Voice | dictation, wake word, read-aloud | does not exist (`whisper-cli` builds in the engine artifact) |
| Astra Link | phone pairing: notifications, clipboard, file transfer, camera and microphone, photo backup | does not exist |
| Astra Skills | manifest-declared, permissioned capabilities | static skills and knowledge files exist; manifests and isolation do not |

The names are provisional; the boundaries are not. Each component must be
replaceable without changing the others.

The order follows three choices from the October 2026 review: the runtime is the
center of the platform; nothing on the runtime gets system access before Guard
exists; and the first complete workflow is the local research assistant, not chat.
A fourth direction comes from the project itself (October 2026): the OS people come
from Windows, Android and other Linux distributions should feel at home in it from
day one — that is Stage 5.

## What must not regress

Already true, and stays true through every stage:

- The engine runs on CPUs without FMA, BMI2 or F16C (the SIGILL lesson).
- The assistant is opt-in: the ISO ships no model, and the desktop is complete
  without one.
- The worker's JSON grammar is enforced even when a model is told to answer in
  prose (proven in CI).
- The maturity table and the test evidence stay honest: unproven things say so.
- The image boots with no network required.

## Stage 1 — Prove the platform

A person can install AstraOS on hardware they own, boot it, connect it and keep it
updated. Every step proven in CI or recorded as untested.

- [x] **ISO builds in CI with structural validation.** 2026-10-16, run 38864588609:
  25/25 checks, `structural=PASS`, 2,432,696,320 bytes. Live boot by hand in
  VirtualBox, 2026-10-15.
- [x] **CI boot self-test green.** 2026-10-16, run 38881934636 (commit 8f81e3d): the
  built ISO booted under QEMU **emulation** — the runner has no KVM — and the image's
  self-test reported `PASS (39 checks, 0 failed)`: console login prompt at 143.7 s,
  LightDM active, the Xfce session as user `astra`, the full `astraos-*` package set,
  the hardware and codec stack, the Flathub remote, NetworkManager and — as one of its
  checks — a real hostname lookup, so the 0.1.0 DNS defect cannot return silently. Two
  harness defects were fixed to get here (`findiso`; a systemd ordering cycle, see
  `CHANGELOG.md`). Run 38913161772 (commit 0e47f4d, 2026-10-16) reported `PASS (51 checks,
  0 failed)` — the same shape plus the firewall, phone-arc and real-screenshot checks
  recorded in the items below. The test boots the ISO's kernel with the ISO as its live
  medium; the syslinux and GRUB boot menus are exercised by the `boot-menus` exercise
  below (green in that run).
- [ ] **Calamares installer end to end in a VM**, and the installed system boots.
  The exercise exists in the source (2026-10-16): `scripts/install-boot-test.sh`
  installs the ISO onto a blank disk by driving the ISO's own Calamares UI over the
  QEMU monitor, then boots that disk alone and requires the image's self-test in its
  installed mode. Its first CI run (2026-10-16, run 38919644411) failed before the
  guest ever booted: the driver's `usb-tablet` had no USB controller to attach to
  and QEMU exited at startup (`No 'usb-bus' bus found for device 'usb-tablet'` in
  `qemu1.out`). Fixed the same day (`qemu-xhci` on the command line, pinned by
  `tests/static/test_install_boot.py`); the retry is the proof, and its outcome will
  be recorded here. The manual procedure in `docs/INSTALLATION_VIRTUALBOX.md` stays
  either way.
- [x] **Boot menu paths exercised in CI**: syslinux (BIOS) and GRUB-EFI, not only
  the kernel extracted from the ISO. The exercise exists in the source (2026-10-16):
  `scripts/boot-menu-test.sh` boots the ISO with QEMU's own firmware — the host
  supplies no kernel and no command line — accepts the menu's default entry through the
  QEMU monitor, and waits for the login prompt that the ISO's own menu entries put on
  the serial console; the `boot-menus` job runs it for both firmwares and uploads both
  logs. Green 2026-10-16, run 38913161772 (commit 0e47f4d): the `boot-menus` job (6m41s)
  ran both firmwares — syslinux on BIOS, GRUB on UEFI — and both serial logs end at
  the live system's `astra-live login:` prompt (`astraos-boot-menus` carries both logs).
- [ ] **An APT repository for the `astraos-*` packages**, so installed systems
  receive updates. None exists today; an installed system currently gets Debian
  packages and nothing else.
- [x] **Firewall decision: default-on.** Decided and implemented on 2026-10-16: ufw
  starts on boot (`ENABLED=yes` in `/etc/ufw/ufw.conf`, installed by the identity
  hook), inbound is denied, and exactly two things are reachable from the local
  network — the assistant's page (`8765/tcp`, pairing-gated) and mDNS (`5353/udp`,
  what finds printers). DHCP replies are covered by ufw's own `before.rules`, so the
  old "it could break the installer's network" reason is answered, not ignored. The
  self-test carries the proof: it checks the active state, the deny default and the
  page rule, and the phone exercise runs with the firewall up while the caller's
  probe of a watched, not-allowed port must leave no arrival in the guest. Green
  2026-10-16, run 38913161772 (commit 0e47f4d): `RESULT: PASS (51 checks, 0 failed)`
  with `firewall-active`, `firewall-default-deny`, `firewall-page-allowed`,
  `firewall-probe-listening` and `firewall-blocks-other-ports` all green, while the
  host's probe of port 18766 (the guest's watched 8766) timed out and the guest
  recorded no arrival (`phone-host.log`: `firewall probe -> 18766 TimeoutError('timed out')`).
  The one check that failed the earlier behavioural run (38903678646) demanded a
  `ufw status` spelling ufw never prints; it now reads the verbose listing, and this
  run proves the fix.
- [x] **The assistant's web page on a phone**: localhost until paired, then the LAN
  with pairing and the firewall on. The pairing half exists in the source
  (2026-10-16) as its first slice: `astra-ai pair` shows a six-digit code, a phone on
  the LAN pairs with it, `astra-ai unpair` revokes every phone, and the boot
  self-test's `astraos.phone=1` section — with the host-side `phone-host.log` as
  evidence — is built to prove the whole arc end to end. Green
  2026-10-16, run 38913161772 (commit 0e47f4d): all six phone checks green
  (`phone-armed`, `phone-localhost`, `phone-paired`, `phone-served`, `phone-revoked`,
  `phone-refused-after-revoke`) with `phone-host.log` carrying the host's arc —
  pairing code read from the serial console, page GET 200, unpaired health 401, pair
  POST 200, paired health 200, revoked health 401, and the blocked-port probe timed
  out. The firewall half is recorded in the firewall item above.
- [ ] **Try Secure Boot**: live-build's `--uefi-secure-boot` path with Debian's
  signed shim and GRUB (the installed live-build documents the option). The source
  now uses it (2026-10-16) and the exercise exists: `scripts/boot-menu-test.sh
  --medium secure` boots the ISO under OVMF's Secure Boot firmware with the
  Microsoft keys enrolled, so a run that reaches the login prompt means the
  Microsoft-signed shim, Debian-signed GRUB and Debian-signed kernel were verified
  by firmware. The `boot-menus` job runs it beside the BIOS and plain-UEFI paths;
  the checkbox flips — and the firmware configurations that boot get documented —
  when a run is green. Until then the README keeps "Secure Boot is not supported".
- [x] **The HUD on a booted image's screen.** The boot self-test's screenshot is
  meant to be the first version of this evidence; the first green run's screenshot
  came back black — a QEMU stdvga blanking defect (see `CHANGELOG.md`). The source
  fix — the guest turns blanking off, forces the display on and repaints the session
  before reporting its result; the host verifies the capture has content and retries
  a flat image while the guest still holds the session — is green since 2026-10-16,
  run 38913161772: the capture carries the real desktop. Green 2026-10-16, run
  38919644411 (commit 8e40d99): the self-test started the dashboard as the live user
  before it prepared the screen (`hud-on-screen` green), the run reported
  `RESULT: PASS (52 checks, 0 failed)`, and the capture — a 1280×800 PNG, 104,723
  bytes — shows the dashboard itself: the clock, the system and terminal panels,
  the memory and filesystem bars, and the endpoint card reading "NO ENDPOINT".
- [ ] **A recovery procedure that has been performed**: snapshot, break, restore,
  in a VM, with Timeshift.

## Stage 2 — Hardware Brain and honest benchmarks

`astra-ai` detects the machine and chooses the engine build, quantization and model
rung itself. The SIGILL lesson becomes a feature.

- [ ] **A capability profile**: CPU flags and instruction sets, RAM, GPU, NPU where
  one exists, storage, audio devices — written at first run and shown in plain
  words.
- [ ] **Engine builds selected from the profile.** CI already builds an AVX
  variant; add AVX2 and a Vulkan build, record which machines need which, and never
  install an engine the CPU cannot run.
- [ ] **An "AI readiness" tier** derived from measurements, not branding.
- [ ] **An evaluation suite with fixed tasks**; publish success rate and tokens per
  second per tier, with answer quality and execution quality scored separately. The
  360M model stays a smoke test and is never presented as a quality result.
- [ ] **Run the full ladder on the project's target machine** (the 1.7B executor is
  already downloaded) and record the numbers: that is what turns "runs on old PCs"
  from a design goal into a measurement.
- [ ] **Benchmark candidate models on the real tiers** before any model name
  appears in the README.
- [ ] **Newer hardware, opt-in**: signed kernels from trixie-backports as an
  explicit choice, never the default. NPUs (XDNA and similar) are claimed only
  after a run on a real machine that has one.

## Stage 3 — Astra Guard: the seatbelt and the undo button

Model output is a request; a policy engine outside the model decides what happens.
Nothing powerful runs without Guard in front.

- [ ] **Four permission levels** (observe / prepare / modify / privileged), deny by
  default above prepare; every approval shows the actual target and effect. The
  model must never grant itself permission.
- [ ] **Sandboxing with bubblewrap and Landlock.** First target: confine
  `llama-server` itself — no network, read-only model folder — and prove it with
  tests.
- [ ] **An inspectable audit log**: what was accessed, what ran, what changed.
- [ ] **Undo**: automatic snapshots before privileged work and a tested rollback.
  The root filesystem is ext4 today; a Btrfs + snapshot default is a change to
  evaluate on old hardware, not a promise.
- [ ] **Prompt-injection discipline, with tests**: documents are untrusted input,
  and fixtures that order the agent to exfiltrate must be denied, not narrated.
- [ ] **No root for models or workers**; privileged actions go through a separate,
  explicit mechanism with its own approval.

## Stage 4 — The flagship workflow: a local research assistant

The first complete task: "find the documents about X, compare them, produce a
report with citations, save it, and show me what changed."

- [ ] **Task objects with a lifecycle** (queued → planning → awaiting approval →
  running → verifying → completed, plus paused / failed / cancelled /
  needs-attention), persisted and resumable across a reboot.
- [ ] **A small, reliable tool set for v0**: search and read authorized folders,
  extract text (PDF), compare documents, write into a workspace — and a verifier
  that checks the artifact exists, is well-formed, and that every citation
  resolves to a real passage.
- [ ] **The task interface** (Missions) showing real progress from executed steps,
  approvals with targets, artifacts, and unresolved limitations — never invented
  percentages.
- [ ] **A benchmark of representative tasks** with published pass rates. Success
  targets are set from measured results, not aspiration; the suite starts smaller
  than the review's suggested one hundred cases and grows.
- [ ] **Budgets**: time, memory and tool-call limits so a weak model cannot loop
  forever.

## Stage 5 — Come as you are: migration, familiarity and retention

People arrive with habits — from Windows, from Android, from Mint or Ubuntu, from
Arch or Kali, from Plasma. They should not have to relearn computing to use this
OS, and they should never leave because it broke. This stage records the
maintainer's direction (October 2026); it comes after Guard and the flagship
because familiarity on an unproven base would be decoration.

- [ ] **A first-run welcome that can be skipped**: language, layout, file import,
  phone pairing, AI opt-in, Packs — every choice reachable again later from one
  settings panel, and none of it requiring an account or a network. The design is
  [`FIRST_BOOT.md`](blueprints/FIRST_BOOT.md).
- [ ] **Layout profiles that are real**: one switch changes panel, menu, launcher
  and keyboard shortcuts together — Windows-like / macOS-like / Linux-classic /
  AstraOS — plus a "where is it now?" cheat sheet for whatever you came from.
- [ ] **A migration assistant**: detect Windows and Android sources; preview and
  import Documents / Desktop / Pictures / Music / Videos item by item with
  confirmation; import browser bookmarks from Chrome / Edge / Firefox profiles;
  print a report of what arrived and what did not. Never move or delete without
  asking.
- [ ] **"I use this app on Windows"**: type an app name, get the honest ladder —
  native alternative, Flatpak, Wine, or web app — each labeled works / works with
  caveats / not yet, starting with the apps switchers actually use. The labels come
  from tests, not optimism.
- [ ] **Reset and fresh-start**: "reset the system, keep my files" and "factory
  reset", both tested in a VM. People trust what has a visible way back to clean.
- [ ] **Updates that cannot brick it**: snapshot before a system upgrade and a
  one-command rollback, with update-success numbers on the proof page (depends on
  the Stage 3 undo decision).
- [ ] **"How do I ...?": an OS that explains itself**: an offline help center with
  migration guides — coming from Windows, from Android, from Mint or Ubuntu, for
  Arch and Kali users, for Plasma users — reachable through the assistant, whose
  answers cite the actual documents.
- [ ] **Astra Link, the Android bridge**: pairing out of the box (notifications,
  clipboard, file transfer), phone camera and microphone as PC input, and automatic
  photo and video backup over the LAN into a private library on the PC — a personal
  cloud in the house, no Google account. The Stage 1 phone page is its foundation.
- [ ] **No lock-in, by construction**: apt stays apt, upstream packages stay
  available, dotfiles import from a repository or archive, containers and virtual
  machines work, and every AstraOS component can be replaced without breaking the
  rest.
- [ ] **Desktop editions, honestly labeled**: an official, tested, themed KDE
  Plasma session for Plasma users — advertised only once it passes the same bar as
  Xfce — and no requirement to change desktops to use AstraOS.
- [ ] **Packs for whole lives, installed on demand** (no ISO bloat): Gaming (Steam,
  Proton helpers, GameMode, MangoHud), Creative (OBS, Krita, GIMP, Inkscape,
  darktable), Security (a Kali-minded toolkit: nmap, Wireshark, forensics — labeled
  a toolkit, not a hardened platform), Developer (toolchains, containers), Office,
  Media. Each pack optional, each tested.
- [ ] **A reason to stay that is not hype**: measured update reliability, rollback
  success and speed on the target hardware; zero ads, telemetry or dark patterns.
  For the person who drifted in for the looks: that is the shop window — the
  product is that nothing breaks.

## Stage 6 — Voice, memory and daily use

- [ ] **Push-to-talk dictation first**, system-wide, using the shipped
  `whisper-cli`; measure accuracy and latency on the target CPU before promising
  anything.
- [ ] **Compare `whisper.cpp` and `sherpa-onnx` with numbers** (accuracy, latency,
  CPU, memory, noise) and audit every model's licence before shipping it — some
  wake-word models are non-commercial and cannot ride along in the image.
- [ ] **Wake-word activation only after push-to-talk is reliable** and false
  activations have been measured.
- [ ] **Deterministic handling for unambiguous commands** (open, volume, status) —
  no model needed for those.
- [ ] **Astra Vault**: index only explicitly selected folders; keep conversation
  history, user-approved memory and the document index separate; citations link
  into the original files; the user can see, remove, rebuild, disable and export
  everything; retrieved documents remain untrusted input.
- [ ] **Read-aloud** through the shipped `speech-dispatcher`, natural-language
  file search, and "ask the project docs" offline.
- [ ] **Multilingual**: test the languages actually supported before advertising a
  language list.

## Stage 7 — Platform, ecosystem and trust

- [ ] **A local MCP gateway** exposing the OS (packages, services, logs, network,
  metrics, files through portals) as tools, with Guard policy in front; pin the
  supported protocol versions; keep the internal permission model independent of
  any protocol's behaviour.
- [ ] **Skill manifests**: identity, version, inputs, outputs, required
  permissions, runtime, dependencies, integrity, compatibility — shown before
  install; signed and revocable.
- [ ] **Astra Doctor**: read journal, dmesg and `inxi` (already in the image),
  explain failures in plain language, and propose allowlisted fixes with undo —
  starting with the failures observed on real machines (audio, Wi-Fi, suspend),
  not a blank sheet.
- [ ] **A compatibility matrix, built with consent**: a hardware report the user
  previews before sending (no telemetry by default), and a public
  works / workaround / broken table. Prefer existing probe formats over inventing
  one.
- [ ] **A CI-generated proof page**: the ISO hash, the structural checks, the boot
  self-test log and screenshot, and the tested CPU matrix.
- [ ] **Signed releases and an SBOM**; the Stage 1 APT repository becomes the
  signed update channel.
- [ ] **Packs**: keep every capability, but move Office, Media, Wine and Dev into
  opt-in first-run groups, and install only the firmware the machine needs — a
  smaller ISO without losing the "everything is available" claim.
- [ ] **An AI-contribution policy with disclosure requirements**: contributors
  must understand, review and test what they submit.
- [ ] **Desktop**: stay on Xfce/X11 while that is the right choice for old
  hardware; build Guard's GUI on portals now so an experimental Wayland session is
  possible when Xfce's compositor is usable. No Wayland claims before that.
- [ ] **Reach**: refurbishers, schools and small offices; the old PC in the corner
  as a private AI server for a household or a classroom over local Wi-Fi — the
  Stage 1 phone page is the first step.

## Beyond the stages — the long horizon

The stages are the schedule; underneath them runs the direction they all serve —
three pillars, designed in blueprints whose first slices sit inside the stages and
whose whole has no schedule yet:

- **Everywhere — the mesh.** Your devices act as one computer: one identity, a
  session that follows you, any screen as a window, heavy work placed where it
  fits, an optional always-on Anchor at home. The design is
  [`blueprints/MESH.md`](blueprints/MESH.md); its first slices are the Stage 1
  phone page and Stage 5's Astra Link
  ([`blueprints/PHONE_LINK.md`](blueprints/PHONE_LINK.md)).
- **Remembers — the timeline.** Rewind the system, branch it to try something
  risky, merge what was good, and search your own past — locally, encrypted,
  opt-in by source, with forgetting that really forgets. The design is
  [`blueprints/TIMELINE.md`](blueprints/TIMELINE.md); the system layer is
  [`blueprints/UNBREAKABLE.md`](blueprints/UNBREAKABLE.md) in Stages 3 and 5.
- **Shapes — the canvas.** Say what you want; the screen for it is built from
  permissioned pieces, used, and dissolved; what you pin stays as it was. The
  design is [`blueprints/CANVAS.md`](blueprints/CANVAS.md); its first slices are
  the Stage 4 Missions interface and the Stage 7 skill manifests.
- **Meaning — the graph.** Files stay files; on top of them, things and links let
  a person search by describing. The design is
  [`blueprints/GRAPH.md`](blueprints/GRAPH.md); its first slice is the Stage 6
  Vault, narrow on purpose.

None of the four has a schedule yet, and the working rules below apply unchanged:
an item is done only when a run, a test or an artifact proves it, and the four
files say in their own words that nothing of them exists.

Ten tests would prove the whole direction once its pieces exist. They are targets,
not claims, and none of them can run today:

1. **The river test.** Lose a laptop in water; on a new one, be productive within
   20 minutes.
2. **The ransom test.** Run ransomware in a lab, rewind, and lose less than five
   minutes of work.
3. **The bad update test.** Break a system update on purpose; the machine boots
   the previous system by itself.
4. **The grandmother test.** A first-time user completes five everyday tasks
   without help, in the Simple profile.
5. **The friend's TV test.** From QR code to your desktop on a stranger's screen
   in under 30 seconds, with nothing left behind afterwards.
6. **The airplane test.** Everything essential works with no internet, and
   changes merge correctly on landing.
7. **The old laptop test.** A ten-year-old laptop with 4 GB of memory feels fast,
   with heavy work offloaded.
8. **The forget test.** Delete a memory and prove it cannot be recovered from the
   index or any backup.
9. **The audit test.** An independent party rebuilds the OS from source and gets
   bit-for-bit identical results.
10. **The exit test.** Export everything to open formats and open it on a plain
    Linux install in under an hour.

## How success is measured

| Area | Measurement |
|---|---|
| Operating system | clean installation, boot reliability, update success, recovery works |
| Migration | first boot to a comfortable setup; imported items verified |
| AI tasks | end-to-end completion rate on the fixed benchmark |
| Tool use | valid calls, correct arguments, unnecessary steps |
| Efficiency | completion time, retries, peak memory, CPU |
| Voice | recognition accuracy, latency, false activations |
| Security | unauthorized attempts blocked; injection fixtures denied |
| Local-first | no network egress under offline-only settings |
| Retrieval | citation correctness and source support |
| Experience | time to finish representative tasks, corrections needed |

Numbers are published per hardware tier and per model. Release targets are set
from measured results; where no measurement exists, the README says so.

## Working rules

1. An item is done only when a run, a test or an artifact proves it, with the
   proof linked. Until then it is "not started" or "in progress" — never implied
   as working.
2. Failures are recorded: what failed, why, what changed — the `findiso` entry in
   `CHANGELOG.md` is the model.
3. Heavy work runs in CI. The project's target machine is a test subject, not a
   build server.
4. The image never requires a model, never phones home, and never installs
   software that was not asked for.
5. Third-party claims (model quality, hardware support, market figures) are
   verified on this project's own tiers before they appear anywhere.
