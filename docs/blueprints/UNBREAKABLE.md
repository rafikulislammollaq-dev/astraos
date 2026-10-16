# Unbreakable: updates that roll back, state that can be undone

Blueprint, October 2026. Status: **proposed.** Nothing here is implemented, and
no built image offers anything like it. The roadmap stage is Stage 3 (undo),
with the user-facing halves in Stage 5; what exists today is in
[`../../README.md`](../../README.md).

## The promise

Mistakes and bad updates become undoable. If an update leaves the machine
unbootable, the previous system is still on the disk — one menu entry away.
People stay on a system they trust, because the system can survive them.

## How it works

The pieces exist in the Linux world, and some ship here already (`timeshift` is
in the image):

- **Snapshot points.** Before every system update, before every Guard-approved
  "modify" or "privileged" operation, and on a schedule for home data. System
  and home snapshots are separate policies — a failed experiment should not
  roll back your documents.
- **The updater.** `astraos-update` wraps the APT flow: snapshot → upgrade →
  health check (services up, boot configuration validated, desktop reachable)
  → promote the snapshot to "known good". A failed health check offers
  rollback immediately.
- **Boot rescue.** The bootloader menu lists recent snapshots (the
  `grub-btrfs`/`snapper` family of tools, to be evaluated) so an unbootable
  update is a menu choice, not a rescue-USB session. The live USB remains the
  last resort, and its restore procedure is exercised in the recovery
  documentation.
- **The filesystem decision.** Today root is ext4. The honest options —
  Btrfs with snapshots as the default, or Timeshift on ext4 — get evaluated on
  the project's own old hardware, and the choice, with what each gives up, is
  documented before any of this is promised.

## Honest boundaries

- This is **transactional with snapshots, not image-atomic** — the
  Silverblue-style architecture is a different base and a different promise.
  The README will use exactly these words.
- Snapshots are not backups: they live on the same disk and share its fate,
  and they resist ransomware only when they are out of reach of what is
  encrypting files. The documentation says this in the same breath as the
  feature.
- A snapshot protects the system; it does not resurrect work that was never
  saved anywhere else. External copies remain part of the advice.
- Rollback restores the system, not every change made after the snapshot — the
  interface shows what a rollback would change before doing it.

## How this gets proven

- A VM test: update with an injected failing package, assert the health check
  catches it and rollback returns to the working state.
- An unbootable test: break the kernel entry deliberately in a VM, choose the
  snapshot entry from the boot menu, reach the desktop, and assert the system
  is usable.
- A timing record: how long each rescue takes on the old hardware, published.
