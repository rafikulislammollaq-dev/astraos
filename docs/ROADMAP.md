# AstraOS roadmap

This document is the plan, not the current system. What exists today is in
[`README.md`](../README.md) (maturity table, "What has been tested") and
[`docs/KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md). Nothing below becomes a claim
until a run, a test or an artifact proves it, and the proof is recorded; the
`findiso` entry in [`CHANGELOG.md`](../CHANGELOG.md) is the standard for how a
failure is handled — recorded with its cause, not hidden.

The blueprints for the promised experiences — the first boot, profiles, one
store, roll-backable updates, the phone link, the system assistant, privacy,
reach, creator packs, the community rails, what the computer connects to and what
it does by itself — are in
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
| Astra Engine | local inference: `llama-server`, the model ladder, the JSON worker | partial: builds and runs in CI (emulated Sandy Bridge, 360M smoke model); self-selects the engine build and the ladder rung from the measured profile; per-tier quality numbers still need real hardware |
| Astra Guard | permissions, sandbox, audit log, undo | partial: four permission levels, prompt-injection discipline and a hash-chained audit log exist and are tested; sandboxing and undo do not |
| Astra Runtime | task objects: plan → approve → execute → verify, persistence, resume | partial: the journal persists plans, attempts, step index and provenance, and `astra-ai resume` continues a stopped task; approval and verification are still phases inside a step rather than task states |
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
  built ISO booted under QEMU **emulation** — because the runner's `/dev/kvm` is
  `root:kvm` and the runner user is not in the `kvm` group, so the exercise's own
  writability test said no; corrected 2026-10-19, when run 39222797247 became the first
  to use the runner's own virtualisation — and the image's
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
- [x] **Calamares installer end to end in a VM**, and the installed system boots.
  **Proven 2026-10-19, run 39242006646** — the last entry below. The exercise exists in
  the source (2026-10-16): `scripts/install-boot-test.sh` installs the ISO onto a blank
  disk by driving the ISO's own Calamares UI over the QEMU monitor, then boots that disk
  alone and requires the image's self-test in its installed mode. Every exercise before
  the green one failed for a different, named reason:
  - Run 38919644411 (2026-10-16) died before the guest booted: the driver's
    `usb-tablet` had no USB controller to attach to and QEMU exited at startup
    (`No 'usb-bus' bus found for device 'usb-tablet'` in `qemu1.out`). Fixed the same
    day — `qemu-xhci` on the command line, pinned by
    `tests/static/test_install_boot.py`.
  - Run 39024106426 (2026-10-17) walked the whole wizard and left it on its first
    page: the driver pressed Return at a Calamares 3.3 that designates no default
    button. Rewritten to click the widgets' real positions, located in the driver's
    own screendump.
  - Run 39049818027 (2026-10-17) clicked eleven times and still left the wizard on
    its Welcome page for the whole 45-minute budget: the clicks were sent as HMP
    `mouse_move`, which is a *relative* move delivered to the PC's PS/2 mouse, while
    the live session's X server follows the absolute `usb-tablet`. Every coordinate
    went out as a thousand-pixel delta and the pointer pinned itself to a screen
    corner. The screenshots are the proof — 02 through 09 are the same page with a
    different clock. Fixed in source by moving the driver to QMP and sending
    `input-send-event` `abs` axes; the driver now also hashes the client area before
    and after its walk, so an unresponsive pointer is reported in about two minutes
    instead of costing 45.
  - Run 39103628321 (2026-10-18) tested that fix and reached the first click, where
    QEMU aborted: naming the tablet as the `device` on each event walks the consoles,
    and the fixed text console `-vga std` creates has no `device` property to find
    (`Property 'qemu-fixed-text-console.device' not found` in `qemu1.out`). The events
    now omit the device — the tablet is the only absolute pointer on the machine, so
    an `abs` event has one possible home — and `query-mice` records the pointer
    routing in `ui.log` before the first click. The same run showed the welcome
    screendump being taken before Qt had drawn anything, so the client-area detection
    now looks again once before falling back.
  - Run 39105685521 (2026-10-18) spent the whole 48-minute budget, and its screendumps
    from `02-locale` to `18-exec` are the same **Welcome** page again. The digest that is
    supposed to catch a pointer which never moved stayed quiet, because it was reading the
    wrong pixels. Three defects came out of that evidence, each one read out of QEMU's own
    source. First, an `input-send-event` `abs` value is **not a pixel**: QEMU's
    `INPUT_EVENT_ABS_MIN`/`MAX` are `0x0000`/`0x7FFF`, `qmp_input_send_event` passes the
    value through unscaled, and `hw/input/hid.c`'s `hid_pointer_event` assigns it straight
    to the tablet's axes — so the driver's (1002, 670) landed near (39, 16); the
    coordinates are now scaled to `0x7FFF`. Second, `qemu_input_find_handler` returns the
    *first* handler whose mask intersects the event, and the i8042 PS/2 mouse (`BTN|REL`)
    registers before the tablet (`BTN|ABS`), so `abs` moves went to the tablet and every
    button press went to the mouse; `query-mice` in `ui.log` recorded exactly that
    (`PS/2 Mouse current=True absolute=False` beside `HID Tablet current=False
    absolute=True`), and the driver now makes the tablet current with HMP's `mouse_set`
    over `human-monitor-command` and records the result back. Third, the digest hashed
    from x=0 instead of the client area's left edge, so its verdict turned on the
    desktop's left column rather than the wizard. The exec loop also nudged the pointer
    before each screendump, because X blanked the screen from `19-exec` onward into
    uniform 282-byte dumps with no evidence in them — **and that did not work**, which the
    next run's evidence shows: run 39222797247 went black at the same frame with the same
    move before every dump, so the wake input is a bare Shift now and a pointer *move* is
    not trusted to reset the blanking timer.
  - Run 39222797247 (2026-10-19) is the first exercise whose evidence could be read past
    the first page, and it shows the walk never left the partitions page. The CI seed
    asked for `initialPartitioningChoice: eraseDisk`, which is **not a value Calamares
    has**: `Config::installChoiceNames()` holds `none, nochoice, alongside, erase,
    replace, manual`, and `installChoiceNames().find()` returns the *first* entry of that
    table — `none`, meaning no choice — for a name it does not know, silently for this key
    (unlike the swap key three lines below it in `Config.cpp`). The partitions page
    therefore arrived with neither radio selected, Calamares disables Next until one is,
    and every click after that was a no-op QEMU accepted without complaint: frames
    `04-partition` through `18-exec` are that same page, and `19-exec` onward are black.
    Four things carried that spelling — the seed in `scripts/install-boot-test.sh`, the
    disk-safety assertion in `0300-installer.hook.chroot`, and the two test pins holding
    that assertion — and the hook's was the worst of them: it refused the build when the
    file *contained* `eraseDisk`, while the value that actually authorises erasure
    (`erase`) would have gone straight through, so the safety net guarded nothing. It now
    requires the shipped value to *be* `none`. Beyond the seed: every step of the walk is
    judged by the client area's bytes before and after, so a step that does not move ends
    the walk naming the page it could not leave; the Erase disk row is clicked on the page
    itself, which does not depend on the seed being right; and the window is waited for by
    looking rather than by sleeping a fixed 60 seconds, which was the emulated answer. The
    same run is the first on the runner's own KVM, and the first read without a build
    behind it (the stored-ISO exercise).
  - Run 39230792183 (2026-10-19) is the first run to walk the whole wizard and *install
    something*: every frame is a different page (`04-partition`, `04a-pointer-erase`,
    `04b-erase-chosen`, `05-users`, `08-summary`, `09-install`), and `10-exec` shows the
    Install page with its progress bar at 13%, *"Filling up filesystems"*. It then stopped at
    job 26 of 27 — `ERROR: Error while running: KeyError: 'grubInstall'`. Calamares reads one
    config per module (the copy at `/etc/calamares/modules/`), and this repository's
    `bootloader.conf` is installed to that path, so it *replaces* Calamares' own instead of
    extending it: the five keys that module reads with no default (`grubInstall`,
    `grubMkconfig`, `grubCfg`, `grubProbe`, `efiBootMgr`) were simply not in it. Three more
    defects came out of the same evidence. The verdict's pass condition greps the structured
    session log for `unpackfs` and `bootloader` — and that file is written to
    `//.cache/calamares/session.log` because the installer unit runs with an empty `HOME`,
    which is neither of the two places the guest's collector looked, so **the exercise could
    not have passed however well the installation went**. The script's claim that `rc=0`
    implies the queue finished is false: after the bootloader failure Calamares put up its
    error page and exited 0 by itself in seconds. And a local `size` in the new exec loop
    overwrote the module's screen-dimension dict, killing the driver a minute into a healthy
    install. This one *did* need the ISO rebuilt — the Calamares config is installed into the
    image by the build hook and the installer script lives in `includes.chroot`, unlike
    everything in the two runs above.
  - Run 39242006646 (2026-10-19, against the stored ISO from run 39238238246) is **green**,
    and it is the first green install exercise in this repository's history. Calamares ran
    its queue to 27 of 27 with `rc=0`; the disk booted with no ISO attached; the LightDM
    greeter appeared; and the self-test reported `PASS (51 checks, 0 failed)` in installed
    mode. Two defects stood between the previous run and this one, and they are the same
    shape — configuration that replaced Calamares' own while being incomplete. The
    bootloader config was missing the five keys its module reads with no default
    (`grubInstall` first; run 39230792183). And the `mount` module had **no config at all**:
    the project installs upstream's `calamares` and deliberately not
    `calamares-settings-debian`, which is where Debian's own `/etc/calamares` tree comes
    from, so a module config this repository does not ship is *absent* rather than
    defaulted — and without `extraMounts` the target had no `/dev` for `grub-install`
    (`cannot find a device for /boot/grub (is /dev mounted?)`, run 39233194012). One host
    bug followed: `cp` through sudo kept the installed `grub.cfg`'s unreadable mode, so the
    phase-2 check grepped a file it could not open and reported a correct patch as missing
    (run 39238238246; fixed in `a6b04d6`). The exercise now records which module configs
    the medium actually carried, with hashes, so a stale medium is named as a stale medium
    rather than read as a failed installation.

    **What this green run does not prove**, and nothing below may be inferred from it: the
    installation was legacy BIOS with one ext4 partition, no encryption and no swap; the
    disk was virtual; nobody logged in to the installed system (the greeter was
    photographed, not used); and the installed system carries the *live* image's initramfs,
    because nothing in the sequence regenerates it — that it boots is something this run
    measured, not something the design provides. Those gaps are the `UNTESTED` rows in
    `docs/KNOWN_LIMITATIONS.md`.

  The manual procedure in `docs/INSTALLATION_VIRTUALBOX.md` stays either way.
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
  receive updates. The assembly exists (2026-10-16): `scripts/build-apt-repo.sh`
  turns the build's .debs into the tree apt reads — `pool/main/...` files,
  `Packages` and its gzip, and a `Release` carrying both indices' hashes — signs it
  with `--key` (`InRelease`, `Release.gpg`, an exported public keyring) or says
  loudly that the output is unsigned and fit only for controlled use, and re-hashes
  every file the index names before it reports success. Proved locally the same day
  (WSL): a host's own apt fetched the index from the assembled archive
  (`Get: ... stable/main amd64 Packages`, no errors) and the signed variant verifies
  (`gpg --verify InRelease` → Good signature). The build job now assembles it from
  the packages it built and uploads `astraos-apt-repo` (unsigned); the first CI
  assembly is recorded (2026-10-17, run 39024106426). The same job also carries the
  consumption proof: a fresh `debian:trixie` container adds the tree as
  `deb [trusted=yes] file:/repo stable main`, runs `apt-get update` against it, and
  installs `astraos-system-tools` out of it — its dependency drags `astraos-base` in
  with it, and the step ends by requiring the installed package to report back,
  through the file it ships and the command that reads it, the exact version dpkg
  recorded; that step is green (2026-10-17, run 39028358504: the fresh container
  installed `astraos-system-tools` 0.2.0 out of the tree). Still open: an *installed*
  system has never fetched updates from it, and where the archive will be served
  from is an undecided hosting question (a GitHub Pages branch, a static host, or a
  file:// medium for airgapped fleets are the candidates).
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
- [x] **Try Secure Boot**: live-build's `--uefi-secure-boot` path with Debian's
  signed shim and GRUB (the installed live-build documents the option). The source
  uses it (2026-10-16), the exercise exists, and it is green: `scripts/boot-menu-test.sh
  --medium secure` booted the ISO under OVMF's Secure Boot firmware with the
  Microsoft keys enrolled to the live login prompt (2026-10-17, run 39028358504; the
  same run booted BIOS and plain UEFI the same way), so firmware verified the
  Microsoft-signed shim and Debian-signed GRUB and kernel instead of refusing the
  medium. The firmware configurations that boot are recorded in `CHANGELOG.md` and
  `KNOWN_LIMITATIONS.md` §1.2. Physical machines remain untested; the README records
  both halves.
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

- [x] **A capability profile**: CPU flags and instruction sets, RAM, GPU, NPU where
  one exists, storage, audio devices — written at first run and shown in plain
  words. The source exists (2026-10-16): `astra-ai profile` measures the machine by
  reading `/proc` and `/sys` as the running user — an unprivileged reading, never a
  privileged probe — prints it in plain words, writes it as JSON beside the
  assistant's settings, and `astra-ai status` makes sure it exists at first run. The
  derived AI-readiness rung below reads the same numbers. **Proven 2026-10-19, run
  39238238246's smoke-boot**: the live self-test ran the command as the live user and
  required the written file — `ok ai-profile (measured as astra and written to
  /home/astra/.config/astraos/machine.json)`, `RESULT: PASS (58 checks, 0 failed)`.
- [x] **Engine builds selected from the profile.** The source has both CPU variants
  (2026-10-17): `--variant avx` (the reference build CI ships), `--variant avx2`
  (Haswell and later), `--variant auto` (newest this CPU can run, read from
  `/proc/cpuinfo`); a named variant is refused before the build when the CPU lacks the
  features, the choice is recorded beside the installed binaries, and `astra-ai status`
  checks it against the CPU. `machine.recommend()` now makes the same choice from the
  measured flag set (2026-10-19), so the profile and the build agree by construction.
  **The two-variant CI run is no longer pending**: run 39244594257 (2026-10-19) built
  and proved both jobs, `avx` and `avx2`, green. Still open: a Vulkan build, and
  downloading the right artifact automatically instead of by hand.
- [x] **An "AI readiness" tier** derived from measurements, not branding.
  Implemented 2026-10-19 in `astraos/ai/machine.py`: `recommend()` reads the same
  profile and chooses the engine build (avx2 only when the CPU lists all of avx2,
  f16c, fma and bmi2; avx otherwise; nothing without avx), the ladder rung (full /
  worker / router / none) from the resident sizes documented in `docs/AI.md`, and the
  free space those models need — and states the number that decided each step. It is
  written into the profile JSON, printed by `astra-ai profile` and `astra-ai status`,
  and pinned by three tests in `tests/static/test_astra_ai_profile.py`. The reference
  machine (4 GiB, AVX without AVX2) is recommended the `avx` build and the `worker`
  rung; it is never offered the 4B brain it does not have the RAM to hold.
- [ ] **An evaluation suite with fixed tasks**; publish success rate and tokens per
  second per tier, with answer quality and execution quality scored separately. The
  360M model stays a smoke test and is never presented as a quality result. The
  source exists (2026-10-17): `astra-ai eval` runs eight fixed tasks with
  deterministic checks — five through the call a question uses, three through the
  worker's constrained JSON — scores answer quality and execution quality
  separately, takes tokens per second from the engine's own usage block (or says it
  was not reported), and writes a JSON report beside the models under the
  assistant's data directory. The engine workflow runs the suite on the 360M smoke
  model, asserts the report is well formed, and uploads it as a smoke result. First
  run recorded 2026-10-17, run 39026539476 (commit 1a309cb): the smoke model scored
  4/5 answer and 3/3 execution on a 4-vCPU runner at 18.3 tokens/s, and the one
  failure is the suite doing its job — it put the three colours on one line, and the
  check said so instead of waving it through. Those numbers are the 360M smoke
  model's, not answer quality; the per-tier numbers still need a run on real
  hardware with a real model.
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

- [x] **Four permission levels** (observe / prepare / modify / privileged), deny by
  default above prepare; every approval shows the actual target and effect. The
  model must never grant itself permission. Implemented 2026-10-19 in
  `astraos/ai/guard.py`: the classification is a literal map over the catalog (a test
  fails when an action is added without a level, and an unclassified action is
  refused), `evaluate()` refuses anything above prepare without an approval, and the
  approval names the resolved arguments and the effect rather than the action's
  category. `actions.execute()` is the single enforcement point. The model cannot
  grant itself permission: `approved` is the caller's `confirmed`, which only a human
  can produce, and a test holds the catalog's `needs_confirm` to the levels.
  `type_text` and `press_key` joined the confirmation set — typing into the focused
  window can change a document or run a command in a terminal.
- [ ] **Sandboxing with bubblewrap and Landlock.** First target: confine
  `llama-server` itself — no network, read-only model folder — and prove it with
  tests.
- [x] **An inspectable audit log**: what was accessed, what ran, what changed. Every
  decision and its outcome is appended to
  `$XDG_STATE_HOME/astraos/guard/audit.jsonl` as one JSON line, each carrying the
  digest of the record before it. `astra-guard audit` prints the ledger (or `--json`
  for a machine), and `astra-guard verify` walks the chain and names the first edited
  or removed record; tests prove both tampering and deletion are caught. A privileged
  action whose record cannot be appended is refused, so the actions that matter never
  run unlogged. The chain is tamper-*evident*, not signed: someone who can write the
  file can rewrite the whole chain.
- [ ] **Undo**: automatic snapshots before privileged work and a tested rollback.
  The root filesystem is ext4 today; a Btrfs + snapshot default is a change to
  evaluate on old hardware, not a promise.
- [x] **Prompt-injection discipline, with tests**: documents are untrusted input,
  and fixtures that order the agent to exfiltrate must be denied, not narrated.
  `guard.scan_untrusted()` recognises instruction-shaped content in what the assistant
  read (ignore-the-instructions, role changes, "run this command", "open this URL",
  exfiltration); the worker marks such a request `document`; and
  `evaluate(provenance="document")` refuses everything above observe, with the target
  and the reason, audited as a denial. Fixtures in `tests/static/test_astra_guard.py`
  order the assistant to open an exfiltration URL, run a command and type over a
  document — each is refused, a normal document is not — and an end-to-end test
  replaces the subprocess seam and asserts that nothing ran.
- [x] **No root for models or workers**; privileged actions go through a separate,
  explicit mechanism with its own approval. The catalog has refused root, `sudo` and
  the system's own files since it was written; Astra Guard adds the explicit approval:
  `privileged` is a level, `execute()` refuses it without `approved=True`, the four
  privileged actions are pinned by a test, and the engine and worker run as the user
  with no account of their own. The approval is the person's yes, never the model's.

## Stage 4 — The flagship workflow: a local research assistant

The first complete task: "find the documents about X, compare them, produce a
report with citations, save it, and show me what changed."

- [ ] **Task objects with a lifecycle** (queued → planning → awaiting approval →
  running → verifying → completed, plus paused / failed / cancelled /
  needs-attention), persisted and resumable across a reboot. **Partly implemented
  2026-10-19**: the journal persists the plan before the first step runs, every
  attempt, the step index and the plan's provenance, and `astra-ai resume` continues
  a stopped task at the step that did not succeed (nine tests in
  `tests/static/test_astra_ai_resume.py`). The statuses pending / running / paused /
  ok / failed / needs_human / cancelled exist. Still missing: `planning`,
  `awaiting approval` and `verifying` are phases inside a step rather than states of
  the task, so a task waiting for a human is not distinguishable in the journal from
  one that is running.
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
