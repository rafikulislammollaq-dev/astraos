# Creators and workers: audio, video, design, development

Blueprint, October 2026. Status: **proposed.** Nothing here is implemented, and
no built image offers anything like it (PipeWire, the audio system these packs
build on, does ship — see [`../../README.md`](../../README.md)). The roadmap
stage is 5.

## The promise

A musician, a video editor, a designer or a developer opens the machine and
finds the tools of their trade working — not installed one battle at a time.
The industry-standard application that has no Linux version is named honestly,
next to the alternative that does.

## How it works

Packs (install-on-demand groups) built around Linux-native best-of-breed
tools, each pack tested as a unit:

- **Audio**: PipeWire (already the system's audio, with its JACK layer) —
  Ardour, LMMS, Reaper where the vendor's terms allow, and **yabridge** for
  Windows plugins, which is how working musicians actually move. A measured
  low-latency profile with realtime privileges set up correctly, tested on the
  T1 machine.
- **Video**: Kdenlive and Shotcut, OBS Studio, HandBrake, FFmpeg; VA-API
  hardware encode (the drivers already ship) verified per generation; honest
  labels for the proprietary studios — DaVinci Resolve is a per-machine maybe
  with a published checklist; Adobe Premiere and Final Cut are not Linux
  programs, and the pack says so plainly alongside the alternatives.
- **Design**: Krita, GIMP, Inkscape, Blender, darktable; color management
  (colord/ICC) configured with the gaps named; Wacom-class tablets as a tested
  path (udev rules and a checked settings flow), not an assumption.
- **Development**: the Debian toolchains already in the archive (GCC, Clang,
  Python, Node, Go, Rust), containers and virtual machines for test work,
  editors from both worlds, debuggers and profilers. The point is a machine
  where `git clone && make test` succeeds out of the box.

## Honest boundaries

- The industry standard is Windows and macOS software. The packs' job is to be
  honest and useful: native-first recommendations, Wine where it truly works
  and is labeled, vendor paths where vendors provide them, and a plain "not on
  Linux" where that is the truth.
- Proprietary codecs, plugins and drivers keep their licensing terms; the pack
  installs what is redistributable and points to the vendor for the rest, with
  the exact steps shown.
- "Professional grade" is earned per workflow by measurement (audio latency,
  dropped frames, encode quality), published per tier — never by adjective.

## How this gets proven

- Each pack: a VM job installs it, launches every application headlessly where
  possible, screenshots the rest, and fails on a broken launch.
- Audio: a latency and xrun measurement job on real hardware; video: an
  encode/decode assertion with VA-API on a machine that has it; design: tablet
  and color checks on real hardware.
- The readiness table per pack (works / caveats / not yet) lives on the proof
  page.
