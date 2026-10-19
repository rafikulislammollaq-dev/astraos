# Things that happen by themselves

Blueprint, October 2026. Status: **proposed.** Nothing here is implemented, and no built
image runs anything unattended. What exists today is `planner.py` (a plan is a constrained,
typed step list, seven steps at most, every step naming what must be true afterwards),
`actions.py` (the named action repertoire, with a privilege denylist and no shells) and
`journal.py`; `astra-ai` today answers one request and stops. The roadmap stages are 4
and 6.

## The promise

Work a person does the same way every time should happen by itself. Work a person repeats
without noticing should be *offered* back to them as an automation they can read, rehearse,
arm, disarm and undo — never adopted on their behalf. "Every Sunday, tidy the downloads
folder and tell me what moved." "When a PDF lands in this folder, summarise it into my
notes." The computer notices, proposes and rehearses; and when something happens on its
own, the log says exactly which automation did it.

## How it works

- **An automation is a saved plan plus a trigger, and there is no new machinery.** The
  trigger is local and simple: a time, a file appearing, a login, a device joining the
  network, a message arriving. The condition narrows it: only on mains power, only in this
  folder, only for this sender. The plan is the same constrained, typed step list
  `planner.py` already writes for a one-off request, with the same seven-step ceiling and
  the same per-step evidence field. The runtime that runs a task once is the runtime that
  runs it on a schedule.

- **An automation is readable, not merely trusted.** The same schema, the same
  line-by-line veto, and the same refusal of anything outside the action repertoire.

- **Nothing is armed without being rehearsed.** The first run happens against a copy or in
  a branch and shows the difference it would have made; arming is a separate, explicit act.
  This is consent level 1 from the direction, made concrete.

- **Undo is declared up front.** An automation states how it will be undone — write only
  into its own workspace, keep the previous version, snapshot before a system change — and
  an automation that cannot say how it would be undone does not run unattended.

- **Learning is a proposal, never an adoption.** When the same sequence of steps recurs in
  the activity journal, the journal may offer to turn it into an automation, showing the
  sequence it noticed. It never arms one by itself, never widens a trigger silently, and
  remembers a declined proposal as declined. This is the rule that muscle memory is sacred,
  applied to behaviour rather than to layout.

- **An unattended run still stops at the outside world.** Sending, paying, publishing and
  unrecoverable deletion need approval every single time, whether a person asked or an
  automation did, and the action waits in an outbox rather than going out and being
  apologised for afterwards.

- **Every automation has ceilings and quiet hours**: time, tool calls and memory, so a weak
  model cannot loop forever, plus an instruction not to run unattended on battery unless it
  was told explicitly that it may.

- **Automations are portable files.** A manifest and a plan in plain text, readable without
  this project's software, exportable and shareable — so "here is my Sunday tidy" can be
  handed to a friend as a file rather than as an account.

## Honest boundaries

- **Not everything should be automated, and this document will not pretend otherwise.**
  Anything that reaches the outside world stays a deliberate act.

- **A trigger on file events fires during a large copy.** Coalescing and debouncing are
  part of the work, not a detail to be discovered on somebody's real machine.

- **A proposal can be wrong.** The person is shown the sequence that was noticed and
  decides, and the decision sticks.

- **Automations are the most attractive target for prompt injection, because they run
  unattended.** Tainted input may not select an automation, and no automation may read
  untrusted content and then act on the outside world within the same run.

- **Proposals can only come from what was recorded.** An automation is built from the
  opt-in activity memory of Stage 6; with that off, automations come only from what a
  person describes by hand. The system does not quietly begin watching in order to be
  helpful.

## How this gets proven

- A scheduled automation in a virtual machine: it fires, it changes exactly what it
  declared and nothing else, its receipt names the automation and the trigger, and one
  command puts the machine back as it was.
- Arming without a rehearsal is refused, and the refusal says why.
- An unattended run whose plan reaches an outside action pauses for approval instead of
  proceeding, and the pause appears in the log.
- An injection fixture aimed at an armed automation is denied and recorded, not narrated.
- A proposal test: a recorded journal containing one repeated sequence produces exactly one
  offer, and declining it means the offer is not made again.
