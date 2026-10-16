# AstraOS roadmap

This document is the plan, not the current system. What exists today is in
[`README.md`](../README.md) (maturity table, "What has been tested") and
[`docs/KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md). Nothing below becomes a claim
until a run, a test or an artifact proves it, and the proof is recorded; the
`findiso` entry in [`CHANGELOG.md`](../CHANGELOG.md) is the standard for how a
failure is handled — recorded with its cause, not hidden.

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
| Astra Skills | manifest-declared, permissioned capabilities | static skills and knowledge files exist; manifests and isolation do not |

The names are provisional; the boundaries are not. Each component must be
replaceable without changing the others.

The order follows three choices from the October 2026 review: the runtime is the
center of the platform; nothing on the runtime gets system access before Guard
exists; and the first complete workflow is the local research assistant, not chat.

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
- [ ] **CI boot self-test green.** The first attempt (run 38864588609) failed on a
  bug in the test harness, not the image: `findiso` was passed to the guest,
  live-boot loop-mounted the squashfs as if it were an ISO and never found the
  medium (see `CHANGELOG.md`). Fixed; the next green run is the proof. When green,
  every build proves: boot to the desktop, the Xfce session, the `astraos-*`
  package set, the hardware and codec stack, the Flathub remote, NetworkManager
  and — as one of its checks — a real hostname lookup, so the 0.1.0 DNS defect
  cannot return silently.
- [ ] **Calamares installer end to end in a VM**, and the installed system boots.
  openQA is the established tool for driving an installer in CI; the manual
  procedure in `docs/INSTALLATION_VIRTUALBOX.md` stays until then.
- [ ] **Boot menu paths exercised in CI**: syslinux (BIOS) and GRUB-EFI, not only
  the kernel extracted from the ISO.
- [ ] **An APT repository for the `astraos-*` packages**, so installed systems
  receive updates. None exists today; an installed system currently gets Debian
  packages and nothing else.
- [ ] **Firewall decision.** ufw ships disabled by design (policy in
  `/etc/ufw/astraos-policy.conf`, pinned by the tests). Decide whether default-on —
  with the assistant's page as the only listener — becomes the new default, and
  prove the result in the self-test.
- [ ] **The assistant's web page on a phone**: localhost until paired, then the LAN
  with pairing and the firewall on.
- [ ] **Try Secure Boot**: live-build's `--uefi-secure-boot` path with Debian's
  signed shim and GRUB (check the installed live-build version supports it).
  Document the firmware configurations that are actually known to boot. Until a
  machine reports otherwise, the README keeps "Secure Boot is not supported".
- [ ] **The HUD on a booted image's screen.** The boot self-test's screenshot is
  the first version of this evidence.
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

## Stage 5 — Voice, memory and daily use

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

## Stage 6 — Platform, ecosystem and trust

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

## How success is measured

| Area | Measurement |
|---|---|
| Operating system | clean installation, boot reliability, recovery works |
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
