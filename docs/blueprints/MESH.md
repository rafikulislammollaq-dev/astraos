# The mesh: your devices as one computer

Blueprint, October 2026. Status: **proposed.** Nothing here is implemented except the
first slice of the Stage 1 phone page ([PHONE_LINK.md](PHONE_LINK.md)): the assistant
page pairs a phone with a code shown on the computer, and the pairing is revocable.
That slice exists in the source and awaits its first boot-self-test run as proof; no
built image offers it yet, and everything else described below is not implemented.
Most of it sits beyond the roadmap's stages; the first slices are the Stage 1 phone
page and Stage 5's Astra Link, and the Stage 7 old-PC AI host
([REACH.md](REACH.md)). What exists today is in [`../../README.md`](../../README.md).

## The promise

Your laptop, your phone, the old PC in the cupboard and a borrowed screen act as one
computer. Your session follows you. Heavy work runs where it fits. Any screen can
become a window onto your machine and then forget you were there. One identity stands
under all of it, held by you and no company.

## How it works

### One identity

A cryptographic key pair that means "this is you", created at first run and kept in
the machine's security hardware where one exists. Each device gets its own key,
signed by the identity; adding a device is a QR code, a confirmation on an existing
device and an approval (fingerprint where the hardware offers one). Losing a device
is one action — revoke its key — after which the shared keys rotate so the lost
device can read nothing new. Recovery is chosen at setup: a written phrase kept
somewhere safe, or social recovery (pieces of a secret held by people you trust; the
mathematics, Shamir's Secret Sharing, dates from 1979). The setup screen says the
price of real ownership out loud: if every device and the recovery path are lost,
the data is truly gone — no company can reset an identity it never held.

### The private network

Devices find each other and speak over an encrypted peer-to-peer network: direct on
the same Wi-Fi, and across the internet through NAT traversal, with a relay as the
fallback — a server that passes encrypted packets it cannot read, which anyone,
including you, could run. This family of technology is proven (WireGuard, the
Tailscale family, Syncthing); the plan is to reuse it rather than invent it. Which
parts become AstraOS components and which stay user-replaceable is design work, not
assumed here.

### Three kinds of sharing

- **Data** is stored as content-addressed blocks: identical content costs one copy,
  corruption is detectable, and each device chooses what it holds fully ("pinned")
  and what streams in on demand. A phone never needs the whole video library.
- **Session** — open windows, the clipboard, what you are doing — travels as a
  stream of small changes, using the merge-without-a-server family (Automerge,
  Yjs).
- **Settings** are a declarative description of how you like things; a new device
  builds itself from it, with per-device exceptions such as screen size.

### The scheduler and the Anchor

Every device publishes a small profile — CPU, GPU, NPU, memory, battery, heat,
network, and your rules ("never use my phone for heavy work below 50% battery").
When you start a heavy job — an export, a build, indexing, a large model — the
scheduler places it by speed, battery cost, where the data already lives and your
rules. The first targets are batch jobs and offloading to a stronger device you own,
plus the **Anchor**: an optional always-on machine (an old PC is perfect) that keeps
backups, runs a relay, hosts the larger model and does the nightly indexing.
Everything works without an Anchor; everything feels better with one. Lending power
through trust circles happens only with explicit consent; the mesh never uses
strangers' devices.

### Doorways

A Doorway turns any screen into a window onto your computer. On an AstraOS machine,
the rendering happens on the machine you are at. On any other screen — a hotel TV, a
friend's laptop — a QR code, a scan with your phone and a fingerprint approval start
an encrypted, low-latency stream (the Moonlight/WebRTC family); the screen's
keyboard or your phone as a trackpad drives it; End session, and nothing is left
behind, because the borrowed screen only ever received pixels. A borrowed screen is
still untrusted — it could be recording — so a Doorway starts at a guest trust
level: the Vault stays hidden, passwords are typed on your phone, and sensitive
tools need an explicit override with a warning. The OS cannot make a stranger's
hardware safe; it can only limit what it shows.

### The phone

The phone story is [PHONE_LINK.md](PHONE_LINK.md), deliberately companion-first: the
computer is the home base, the phone is its screen, microphone and remote — not an
AstraOS installation on the phone. "Plug your phone into a monitor and get a
desktop" is vendor magic (Samsung DeX) and is not promised here either.

## Honest boundaries

- If every device and the recovery path are lost, the data is truly gone. That is
  the design, not a bug.
- Phones and tablets are not an installation target; ARM is not covered
  ([REACH.md](REACH.md)). The companion app is the phone story.
- Splitting one AI model across several weak devices is usually slower than one
  strong device; the scheduler's honest sweet spot is batch work and offload to a
  stronger machine you own.
- Graphics offload needs compatible drivers, and network delay limits what can be
  split; both are measured before anything is promised.
- A relay passes packets it cannot read, but someone must run one; "anyone can" is
  not "someone does".
- Hole punching fails through some routers; the mesh degrades to the relay, and
  offline every device simply holds enough to work alone and merges later.

## How this gets proven

- Two virtual machines, one identity: create, add a device (the QR flow's protocol
  exchange), revoke the second, assert the first refuses it afterwards and that new
  data is unreadable to it.
- Recovery: reconstruct the identity from a phrase and from social shares in a VM;
  a wrong share set must fail, not silently produce a broken identity.
- Sync under fault injection: edits made offline on both sides merge on reconnect
  (text and structured data); an unmergeable conflict surfaces as "which one?" with
  both versions kept.
- A Doorway test between two VMs: stream a session to the second, end it, and
  assert the borrower received pixels/protocol only — no files, no state — and that
  the guest trust level hid the Vault and refused a sensitive action.
- Scheduler: a batch job is placed by a rule set, produces identical results, and
  is never started on a device the rules exclude.
- All of it in CI where a virtual machine can stand in, and on the T1 machine where
  it cannot, with the difference labeled, per the working rules.
