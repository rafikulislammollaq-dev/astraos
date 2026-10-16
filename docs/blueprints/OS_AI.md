# The assistant as a system service

Blueprint, October 2026. Status: **proposed.** Nothing here is implemented, and
no built image offers anything like it. What exists today is the engine and the
`astra-ai` command line (see [`../AI.md`](../AI.md)); this blueprint is the
system integration that does not exist yet. The roadmap stages are 3 and 4.

## The promise

Describe a problem — "my Wi-Fi keeps dropping" — and the assistant
investigates, proposes a fix and, after approval, applies it, showing every
step. Describe a file and it searches only what you told it to index.
Everything runs locally by default, and everything it does is in a log a person
can read.

## How it works

- **A user-space service, never root.** The assistant lives in the user's
  session (systemd user units). Without an installed model it does not run at
  all: no model, no process, no idle daemon. The desktop is complete without
  it.
- **Diagnose and fix** is Doctor logic (roadmap Stage 7, with first slices in
  Stage 2): collect evidence (journal, dmesg, nmcli, `inxi`), form a
  plain-language hypothesis, propose an allowlisted action with a preview of
  exactly what will change (through Guard, "modify" level), verify after the
  change, and write the outcome to the log. Unallowlisted conclusions end in
  advice, not action.
- **File search by description** reads the Vault index — only folders the
  person explicitly added — and says which index it searched, with citations
  into the original files.
- **Every action is audited**: one readable log lists what ran, what was read,
  what changed and the result. It can be exported and cleared. The audit trail
  is a feature, not a debug aid.
- **The ladder stays capability-aware** (existing design): weak machines get
  smaller models and a smaller action set, and the assistant says what it can
  and cannot do on this machine instead of trying anyway.
- **Extensions** arrive through skill manifests and the MCP gateway (roadmap
  Stage 7): permissions declared, shown before install, enforced by Guard —
  never by asking the model nicely.

## Honest boundaries

- The assistant cannot fix what the system cannot diagnose; "I don't know" is
  a first-class answer that ends in a help page, not a guess.
- No silent network: with no cloud option enabled, there is no code path that
  sends data anywhere. When a future optional cloud assist exists, the exact
  payload is previewable before anything leaves.
- No root, no ambient package installs, no security-setting changes without an
  explicit approval that says what and why.
- The 360M model is an engine smoke test, never a quality claim; action sets
  are gated on measured reliability per rung.

## How this gets proven

- CI fixtures (from Stage 2 on): in a VM, break the network state
  deterministically, run the diagnose flow, and assert the correct detection,
  the correct proposal, that the action is refused without approval, and that
  the log contains the whole story.
- An audit-log test: every action in the fixture appears exactly once, with
  its result.
- A no-model test: the desktop and all of this stay absent, and the system is
  fully usable.
