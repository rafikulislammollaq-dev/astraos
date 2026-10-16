# Reach: what "runs on everything" honestly covers

Blueprint, October 2026. Status: **proposed.** Nothing here is implemented, and
no built image offers anything like it beyond the facts in
[`../../README.md`](../../README.md). The roadmap stages are 1 and 2.

## The promise

A ten-year-old laptop feels usable and fast; a modern machine feels instant.
"This hardware is from 2012" is a design target, not a joke — the project's own
test machine is one.

## How it works

- **Tiers with measured budgets.** T1: two cores, 4 GB RAM, a 64-bit CPU
  without FMA/BMI2 (the 2011–2015 fleet; the project's own machine). T2: any
  modern mid-range system. T3: gaming and workstation class. Each tier
  publishes a budget — boot seconds, idle RAM, desktop cold start, and the
  assistant rung that fits — and CI regression-checks what a virtual machine
  can check (boot time, memory floors) while real hardware proves the rest.
- **Engine builds per class** — the Hardware Brain (Stage 2): the llama.cpp
  build (AVX today, AVX2 and Vulkan planned) is chosen from the measured CPU,
  never guessed. A machine without FMA keeps working; that lesson already cost
  one SIGILL.
- **Handhelds** (Steam-Deck-like: amd64 plus a controller) are a
  T3-with-controls case — Gaming Pack, big-picture session, honest per-game
  labels. No console claims.
- **The kernel ladder**: signed trixie-backports kernels as an explicit
  opt-in for hardware the 6.12 kernel is too old for; never silent, never
  default.

## Honest boundaries

- **ARM and RISC-V are not covered today.** An aarch64 port is a separate
  project (cross-build, boot, device trees, testing) and will be proposed on
  its own merits, not smuggled into a slogan. Phones and tablets are not an
  installation target at all — the phone story is
  [PHONE_LINK.md](PHONE_LINK.md): your computer's AI in your phone, not
  AstraOS on your phone.
- "Feels fast" is measured per the tiers above; no adjective without a
  number.
- Firmware and Wi-Fi reach stay bounded by what the kernel and the vendors
  provide; the hardware documentation says which is which.

## How this gets proven

- A performance job per build records boot time and memory floors in the VM
  (directional), and a published table records the real numbers on the T1
  machine and any hardware the project actually owns.
- The AI ladder publishes tokens per second per tier per model (Stage 2's
  evaluation suite) — the numbers people need before installing, not after.
