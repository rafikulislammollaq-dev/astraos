# Profiles: one system, many setups

Blueprint, October 2026. Status: **proposed.** Nothing here is implemented, and
no built image offers anything like it. The roadmap stage is Stage 5; what
exists today is in [`../../README.md`](../../README.md).

## The promise

One installation serves a beginner, a developer, a security researcher, a gamer
and a child — each person gets a setup that fits them within a minute, and
nobody is a second-class citizen of a "different edition". Switching is
instant, and nothing is ever locked away.

## How it works

A profile is a preset over three layers that already exist in the plan, not a
second operating system:

1. **Layout and shortcuts** — the same mechanism as the first-boot question
   ([FIRST_BOOT.md](FIRST_BOOT.md)).
2. **Software** — Packs (install-on-demand groups; see [CREATORS.md](CREATORS.md)
   and the roadmap's Stage 5).
3. **Policy** — the permission defaults Guard (Stage 3) applies: what may be
   installed, what may reach the network, what needs an approval prompt.

Concretely:

- **Simple**: larger text and targets by default, plain-language dialogs, a
  "recommended" store view, installs limited to reviewed sources until the
  person changes the policy. Everything still exists — settings just start
  where a beginner needs them.
- **Power**: terminal on Super+Enter, no confirmation for actions on your own
  files, containers and virtual machines ready, and opt-in backports
  (trixie-backports) as an explicit switch — never silently rolling.
- **Security work**: the toolkit Pack (nmap, Wireshark and relatives — labeled
  a toolkit, not a hardened platform) plus an *isolated workspace*: a
  disposable virtual machine or container where experiments live, so nothing
  touches daily data.
- **Gaming**: a couch-friendly session option (big-picture launcher, controller
  focus), GameMode and MangoHud profiles, and per-game checks that say what
  the machine can actually run.
- **Family**: per-person accounts; for managed accounts, time budgets (a small
  session service that ends the day cleanly, not a locked kernel), store
  allowlists, and network content filtering at the resolver. What is per-user
  and what is per-machine is stated on the settings page, because the
  difference matters.

## Honest boundaries

- Profiles are **not separate operating systems**. The "modes" idea of five OS
  personalities would mean five systems to test and secure; presets plus Packs
  and Guard deliver the same wish without the matrix.
- "Security work" is a toolkit and a sandbox, **not a security guarantee** —
  the differences that matter are in how experiments are isolated, and the
  page says so on screen.
- Parental controls protect against accident and impulse, not a determined
  teenager with a live USB; the family page says exactly that.
- No profile switches mid-session under a person's feet; applying a profile
  shows what will change first.

## How this gets proven

- A VM test: create each profile over the same installed system, assert the
  desktop settings, the visible store sources and the Guard policy defaults
  match the profile's definition — and that switching twice returns the system
  to a defined state.
- A managed-account test: an install outside the allowlist fails, the time
  budget ends the session, and the audit log records both.
- Screenshots per profile join the CI artifacts when the stage starts.
