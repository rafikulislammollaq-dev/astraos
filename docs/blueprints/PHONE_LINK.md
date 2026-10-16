# The phone and the computer as one device

Blueprint, October 2026. Status: **proposed.** Nothing here is implemented
except the first slice of the Stage 1 phone page: the computer serves the
assistant page on the local network, a phone pairs with a six-digit code shown
on the computer (`astra-ai pair`), and the pairing can be revoked (`astra-ai
unpair`). That slice exists in the source and awaits its first boot-self-test
run as proof; no built image offers it yet, and everything else in this
document — the companion application, notifications, clipboard, calls — is not
implemented. The roadmap items are Stage 1 (the phone page) and Stage 5 (Astra
Link); what exists today is in [`../../README.md`](../../README.md).

## The promise

Notifications, clipboard, files, photos and calls flow between the phone and
the computer with no manual syncing. The computer is the home base the phone
plugs into, and the phone is the screen and microphone the computer borrows —
without a cloud account in the middle, unless the person chooses one.

## How it works

Two rails, so every phone is welcome:

1. **The browser page** (roadmap Stage 1): the computer serves a small page on
   the local network; the phone pairs by confirmation, then reaches the
   assistant, sends files and reads status. Zero install; works on iPhones
   too, within Apple's limits.
2. **A companion application (Android first; iPhone if and when Apple allows
   the same reach)**: pairing by QR code, then notification mirroring,
   clipboard sync (per-direction switches), file transfer, the phone's camera
   and microphone as computer input, and **automatic photo and video backup
   over the home network** into a private library on the computer — a personal
   cloud in the house.

Where the Linux ecosystem already solved a part — the KDE-Connect family of
protocols is the baseline to evaluate — AstraOS reuses it instead of
reinventing it. The AstraOS-specific additions are the preconfiguration, the
Guard integration, the photo library and the audit trail.

Later, honestly labeled stages: calls and messages display (needs Android
permissions), the computer's screen on the phone (remote session), and Android
applications on the desktop as an **experiment** (Waydroid and its relatives
are real but partial; they live on an experiments shelf, never on the
promise).

"Your phone plugged into a monitor becomes a desktop" is vendor magic (Samsung
DeX) and is not ours to promise. The comparable AstraOS move is the reverse:
your computer is already the dock, and the phone is its remote.

## Honest boundaries

- Pairing is explicit, per-device and revocable; keys are per pair. The default
  transport is the local network only — no rendezvous server, no account.
- Photo backup on Android is real background work; on iPhone, iOS limits it to
  when the application is open. The settings page says which phone gets what.
- Clipboard sync is off by default in each direction and is audited like any
  other Guard-visible action.
- The experiments shelf never appears until the feature behind it passes the
  tests its label promises.

## How this gets proven

- The daemon's protocol parts and the browser page run under CI against a pair
  of virtual machines (a "phone" and the "computer"): pair, send a file, sync
  the clipboard, revoke the phone, and assert refusal after revocation.
- Photo backup is proven where it runs: on real phones and the real computer,
  with the numbers (transfer speed, battery effect) published rather than
  guessed. CI proves the pieces; hardware proves the experience.
