# The graph: data by meaning, files as files

Blueprint, October 2026. Status: **proposed.** Nothing in this document is implemented,
and no built image offers anything like it. The first slice is the Vault index in
Stage 6 ([OS_AI.md](OS_AI.md) and the roadmap); everything beyond it is long-horizon
and has no schedule. What exists today is in [`../../README.md`](../../README.md).

## The promise

Your data stops being only folders. Search by describing: "the receipt from the
hotel in Lisbon", "Priya's birthday photos from last year". Programs that adopt the
shared model hand you search, links and history for free — and every existing
program keeps opening plain files the way it always did, because the files never
went anywhere.

## How it works

### Things and links

Everything becomes a **Thing** — a person, a place, an event, a project, a document,
a photo, a message, an expense — with types and properties, joined by typed links
("attended", "belongs to", "mentions", "paid for"). A photo links to the trip, the
people in it and the hotel receipt from the same days. This is a personal knowledge
graph in an embedded database on your devices, synchronised with the merge rules of
the mesh ([MESH.md](MESH.md)). Types are open and versioned, so "Event" means the
same thing to every capability.

### Files are still files

Photos, videos and documents are ordinary content-addressed blobs attached to
Things. A Files view shows normal folders — a home directory every existing program
can read and write exactly as before. Anything saved there is *ingested*: metadata
read, text extracted, and only with the person's opt-in, speech transcribed and
faces or objects recognised locally. The results are Things and links; when a guess
is wrong ("that is not Priya, that is Riya"), one correction is remembered.

### The Vault relationship

Stage 6's Astra Vault is this blueprint's first, narrow slice: index only folders a
person explicitly added, keep citations into the original files, and let the person
see, remove, rebuild, disable and export everything. The broad graph comes later, if
the narrow slice earns it.

### The lesson from history, as a design rule

Database-style filesystems were tried before and failed (WinFS was worked on for
years and dropped in 2006). The failure modes are known, so they are refused up
front: files stay the source of truth; the graph is a rebuildable index and overlay,
**never the only copy**; types stay small, open and allowed to be messy; no program
is forced to adopt it; and programs that do adopt it get search, links, merging and
history — an incentive, not a mandate.

## Honest boundaries

- The graph is never the only copy. Delete it and the files still open; rebuild it
  by reindexing.
- "No files, no folders" is a slogan this project refuses; folders keep working, and
  nothing forces a person into the graph.
- Recognition and transcription are guesses, labeled as guesses, on your machine,
  off by default, and correctable in one step; nothing is renamed or rewritten
  without approval.
- Ingesting a large library costs real time and battery on old hardware; the work
  needs the Anchor or idle time, and the numbers are measured before anything is
  promised ([REACH.md](REACH.md)).
- The graph's search index is encrypted and local; semantic search is a feature of
  your machine, not a service ([PRIVACY.md](PRIVACY.md)).

## How this gets proven

- An ingest fixture (photos with metadata, documents with text, a dialog audio clip
  with consent) produces the expected Things and links; file checksums are
  unchanged.
- A correct-the-mistake test: one override is remembered and survives a reindex.
- A corruption test: delete the index and the files still open; reindexing
  reproduces the same Things and links — rebuildability is the claim under test.
- An export test: the graph exports to open formats, and the export is enough to
  rebuild it on a machine that has only the files.
- No-network assertions throughout: nothing leaves the machine while any of this
  runs.
