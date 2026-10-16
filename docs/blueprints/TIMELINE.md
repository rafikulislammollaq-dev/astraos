# The timeline: a computer you can rewind, branch and search

Blueprint, October 2026. Status: **proposed.** Nothing in this document is implemented,
and no built image offers anything like it. The first slice is the system layer in
[UNBREAKABLE.md](UNBREAKABLE.md) (Stages 3 and 5); the later layers have no schedule
yet and say so. What exists today is in [`../../README.md`](../../README.md).

## The promise

Mistakes stop being permanent. A bad update, a wrong delete or a wanted experiment
are undone in one visible step — rewind the machine, branch it to try something
risky, merge back what was good. And your past is searchable: "that chart I saw in a
video last spring", found locally, encrypted, under your control, with forgetting
that really forgets.

## How it works

### The four layers

1. **The system.** Snapshots before updates, a health check after, and a menu entry
   back to the previous state: designed in [UNBREAKABLE.md](UNBREAKABLE.md) —
   transactional with snapshots, in the plan's exact words, not the image-atomic
   promise of other systems.
2. **Your data.** The plan is a copy-on-write filesystem — Btrfs evaluated first, on
   the project's own old hardware ([UNBREAKABLE.md](UNBREAKABLE.md) owns the
   filesystem decision) — taking cheap snapshots on a schedule and *just before
   anything risky*. Old snapshots thin out like Time Machine's: dense recent
   history, sparse old. Snapshots copy to your other devices and the Anchor
   ([MESH.md](MESH.md)), so one dead disk does not take the whole history with it;
   out-of-reach copies are what make the ransomware story true — a snapshot on the
   same disk shares its fate, and the documentation says so in the same breath.
3. **Activity memory** (opt-in, source by source). An event log — documents opened,
   edits, pages, tools that ran — is the index into your past. Turning on more, with
   screen and audio memory, periodic captures are read out into text on your own
   machine (OCR, transcription), turned into embeddings, and searched by
   description. This layer is off by default, every source is a separate switch, and
   it is the biggest storage cost — which is why it lives mostly on the Anchor and
   fades first.
4. **Live state** — the hardest layer, and version one says something smaller:
   documents, window layout and what each program saves through a standard resume
   interface. Restoring a running program exactly as it was (the CRIU family, VM
   snapshots) arrives first for programs inside AstraOS's own runtime and grows
   from there; programs heavy on graphics or open connections are fragile, and the
   interface says which is which.

### Branches

A branch is a snapshot you can write to: it starts instantly and costs nothing
until something changes. First shape: a sandboxed container or a small virtual
machine running in a window; booting into a branch is a later, separately proven
step. Each branch has rules — internet, identity, which files it can see (none, a
read-only view, or a copy) — and its uses are named plainly: unknown installers, the
assistant's rehearsed plans (a fix or task is tried in a branch and the difference
shown before the real system is touched, [OS_AI.md](OS_AI.md)), what-if work, a
child's world, and an old computer imported as a branch so nothing from a past life
is lost at migration ([FIRST_BOOT.md](FIRST_BOOT.md)).

**Merging back** is Git-shaped: the timeline compares the branch with its split
point and shows a clear list of what changed; text merges line by line, structured
data merges by its own rules, settings merge as a declarative difference, and an
unmergeable file (a photo edited twice) is kept in both versions with "which one?"
asked. A legacy program's private database cannot be merged by anyone in general —
for those, you choose "take the branch version" or "keep main". Programs that keep
their data in the graph ([GRAPH.md](GRAPH.md)) get merging for free; that is the
incentive, not a mandate.

### The parts that cannot be rewound

The outside world: an email sent, a payment made, a post published. The timeline
marks irreversible actions in the history ("this sent an email at 15:02"), and an
outbox holds outgoing actions for a short, visible undo window. Anything the
assistant wants that reaches the outside world needs explicit approval, every time
([OS_AI.md](OS_AI.md)). The principle: the OS rehearses locally and commits to the
world only on purpose.

### Remembering safely

- Opt-in by source: system and data snapshots follow the snapshot policies; activity
  and screen memory are off until switched on, each source separately.
- Local and encrypted: keys stay in the machine's hardware; the search index never
  leaves the mesh.
- Never-remember zones: the Vault, private windows, password fields, banking and any
  app you list; screen memory pauses itself when a sensitive field is on screen.
- Other people count: calls and meetings are recorded only when you start it, with a
  visible indicator and a prompt to tell the others.
- Forgetting is real: "forget the last hour" removes an item from the index and
  destroys its encryption key (crypto-shredding), so even old backups of it become
  unreadable.
- Memory fades on your schedule: raw captures become text, then summaries, then key
  facts — the shelf life of your past is yours to set.

## Honest boundaries

- The outside world cannot be rewound. The outbox slows outgoing actions a little;
  it cannot unsend what has left.
- A legacy program's private database cannot be merged by anyone in general; branch
  merges say "take one" there instead of pretending.
- Branches are not, by themselves, a security boundary: containers and virtual
  machines reduce reach; the kernel remains the kernel ([PRIVACY.md](PRIVACY.md)).
- Screen memory is a surveillance feature pointed at yourself, by choice. It ships
  off, per-source, with fading and zones; if the cost numbers on the T1 machine are
  bad, it stays an Anchor feature and the README says so.
- Exact live-state resume is research for the general case; version one promises the
  smaller thing and no more.

## How this gets proven

- Rewind: snapshot → break → restore in a VM, timed on the T1 machine, with the
  number published ([UNBREAKABLE.md](UNBREAKABLE.md) owns this test).
- A branch test: an unknown installer runs inside a branch with no access to real
  files; discard; assert the host is byte-for-byte untouched.
- Merge tests: text, structured data and settings merge; a twice-edited file
  surfaces "which one?"; take-version works for a legacy program's database.
- Forgetting: forget an item, then assert it cannot be recovered from the index or
  from a copied snapshot — the crypto-shredding claim, actually run.
- Never-remember: with a scripted app and a simulated password field, assert the
  capture loop pauses and nothing of it reaches the index.
- Outbox: a staged outgoing action is held, undone inside the window, and marked
  irreversible when it commits.
- All index-building runs with no network, asserted, before any feature claim.
