# The canvas: screens that fit the moment

Blueprint, October 2026. Status: **proposed.** Nothing in this document is implemented,
and no built image offers anything like it. The first slices are the Missions
interface (Stage 4) and skill manifests (Stage 7); the generated shell itself is
long-horizon and has no schedule yet. What exists today is in
[`../../README.md`](../../README.md).

## The promise

Instead of hunting for an app, you say what you want, and the screen for that task
appears — built from trusted, permissioned pieces — and dissolves when you are done.
Tools you use often pin down and stay exactly as they were. Any tool you pinned can
be changed by describing the change. And with the assistant switched off, every
everyday task still has a plain, predictable screen.

## How it works

### Abilities, data and screens, pulled apart

An app bundles three things: what it can do, what it knows, and how it looks. The
canvas pulls them apart. Abilities become **capabilities**: small, described,
permissioned functions ("send a message", "convert a document", "find flights")
that run sandboxed — as a WebAssembly component or a container — or bridge to
something that already exists (a web API, an Android app inside the compatibility
layer, a Windows program driven through automation; the bridges are labeled
partial, per [APP_STORE.md](APP_STORE.md)). Every capability carries a **manifest**:
a plain-language description, typed inputs and outputs, the permissions it needs,
its author and signature, its version and its tests — the same discipline as the
skill manifests in the roadmap's Stage 7. The data lives in the graph and the files
([GRAPH.md](GRAPH.md)). The screen is generated for the moment.

### From a sentence to a screen

1. **Intent.** Speaking, typing or pointing; a small on-device model turns it into a
   structured goal ([../AI.md](../AI.md) designs the model ladder and the router).
2. **Resolve.** The OS finds what it already knows (people, dates, earlier work) and
   the permitted capabilities that could help.
3. **Compose.** The assistant writes a **panel plan**: a short, declarative
   description of the layout, the building blocks, which data each shows and which
   capability each button calls. Data, not code: it cannot do anything the
   capabilities do not allow.
4. **Render.** A component kit — lists, tables, forms, charts, maps, players, an
   editor, a drawing surface, a message thread — draws the plan, adapting to the
   screen and to how it is being used: touch, mouse, keyboard or voice.
5. **Act.** Every press goes through the capability broker: permissions check, the
   consent rules apply, and the audit log ([OS_AI.md](OS_AI.md)) records it. The
   model proposes; ordinary deterministic software decides.
6. **Keep or dissolve.** Finish, and the panel goes; its data stays. Ask for it
   again and the cached plan returns it immediately — the second time a familiar
   task needs no model call at all. Pin it, and it becomes a stable, named tool.

### Fixed, assisted, fluid

Every tool is one of three: **fixed** (a pinned tool looks and behaves the same
every time — daily tools), **assisted** (the canvas may rearrange within limits you
set and always shows what changed) and **fluid** (one-off screens that dissolve).
The muscle-memory rule covers all three: once you have used a layout, it comes back
as it was, and changing it needs your say-so.

### Editable tools

A pinned tool is a plan plus capabilities, so changing it is a conversation: "make
this export to PDF", "hide the budget column", "summarize this every Sunday". The
plan is edited, rehearsed in a branch ([TIMELINE.md](TIMELINE.md)), shown as before
and after, and only then applied. Tools can be shared like recipes, and others can
adopt them.

### The honest architecture note

A generated shell that replaces the desktop is a compositor-scale project. This
project's desktop is Xfce on X11 today, and the roadmap refuses compositor claims
until the pieces are real. So the first canvas-like things are applications and
surfaces over the existing desktop — a panel window drawing cached plans, the
Missions interface, store cards — and the full shell is a direction with no date.
The README will always say which of the two a person is actually looking at.

### Professional tools and games

A generated screen is the right answer for planning, tracking, searching, settings
and everyday tasks. It is the wrong answer for a piano roll, a node editor or a
competitive game, where thousands of details were tuned over years. Those stay
first-class hand-crafted **Tools** in their own windows, connected to the system
through portals: open and save, reach snapshots, send heavy work to the mesh
([CREATORS.md](CREATORS.md)). "No apps" is a direction for everyday computing, not
a ban on excellence.

## Honest boundaries

- Closed programs stay closed. Full editing works for AstraOS-native tools and
  open-source programs; for closed ones the canvas can wrap and drive them through
  accessibility and scripting, never rewrite their insides.
- The assistant writes plans, not pixels or programs — but that is only safe
  because the broker enforces, not the model. Plans are still treated as untrusted
  input ([PRIVACY.md](PRIVACY.md), roadmap Stage 3).
- Fast generation is bounded by hardware: common tasks use small models and cached
  plans; a weak machine gets fewer generated screens, and the fallback screens
  always exist. Numbers per tier before any "instant" claim.
- A wrong plan can be silly, not dangerous — because it is schema-checked and
  permission-checked before rendering, shown before use and editable afterwards.
  The "where did my button go" feeling is a bug class with its own tests.

## How this gets proven

- Plan validation: every generated plan must satisfy the schema and reference only
  permitted capabilities; fixtures of malformed and over-reaching plans must be
  rejected before anything renders.
- Broker tests: a plan with an unpermitted action is refused and logged; an approved
  action appears exactly once in the audit log with its result.
- A fixture battery of everyday intents on the T1 machine: latency, cache hits on
  the second ask, and the no-model path (fixed and cached screens only) all
  measured and published.
- An edit test: describe a change, get a before/after diff, rehearse it in a branch,
  apply it, and assert the pinned tool is byte-identical until the change is
  accepted.
- Accessibility checks on the component kit: screen sizes, input modes and contrast
  are asserted, not assumed.
