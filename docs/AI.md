# The AstraOS assistant

This document describes the optional AI assistant that ships with the `astraos-ai`
package: what it is, what it will not do, what hardware it needs, and how a phone
can act as the microphone for a PC that has none.

**Nothing here is required to boot, log in, network, update or recover an
AstraOS system.** The assistant is started on demand, it fails soft when any of
its parts is missing, and no part of the desktop depends on it. This is the
extension point discussed in `PROJECT_PLAN.md` section 22 and the limitation
recorded in `KNOWN_LIMITATIONS.md` section 3.12, now with an implementation.

---

## 1. What it is

A local assistant, in four pieces:

| Piece | Installed at | What it is |
|---|---|---|
| Server | `/usr/lib/astraos/ai/server.py` | A small HTTP server, Python standard library only |
| Page | `/usr/share/astraos/ai/web/index.html` | One HTML file: styles and script inline, no external requests |
| Python package | `/usr/lib/astraos/ai/*.py` | Settings, the llama.cpp engine wrapper, the action repertoire, voice in/out |
| The ladder | `/usr/lib/astraos/ai/{tiers,planner,worker,journal,knowledge,skills}.py` | Two models with two jobs, the skills library, and the task journal |

Start it from a terminal:

```bash
astra ai start          # http://127.0.0.1:8765/ - available only on this machine
astra ai start --lan    # listen on the local network too; a phone must pair:
astra-ai pair           # show the six-digit code the phone enters to pair
astra-ai unpair         # revoke every paired phone
astra ai open           # open the page in the browser
astra ai status         # is it running, is a model installed
astra ai stop           # stop it (stopping also revokes every paired phone)

astra ai work TASK      # do a task: plan it, run it, verify every step
astra ai journal        # what ran, what failed, and what you must decide
astra ai skills         # the skills installed, and what each needs here
astra ai knowledge WORDS # search this computer's own documentation
```

The model runs on this computer. The page makes no request of any kind except to
the server that served it; there are no fonts, scripts, trackers or telemetry to
fetch, and none of it would work on a machine with no internet connection anyway.
That is a product property, checked by `tests/static/test_astra_ai_server.py`,
which fails if an external address appears in the page.

The assistant answers questions about the system, and it can carry out a small,
fixed list of actions (for example opening an application or reporting system
status). It is a normal program running as you: it has your rights and no others.

### 1.1 Why two models and not one

One small model has to be three things at once - good enough to plan, cheap
enough to call a hundred times, and wise enough to know when it is out of its
depth - and it is none of them. The measured finding behind splitting the roles
(arXiv 2601.11327v2, v2 2026-04-13) is that multi-agent systems built on small
models are **planner-limited, not executor-limited**: an 8B orchestrator scores
23.0 / 23.0 / 23.6 on GAIA whether its sub-agents are 1.7B, 8B or 32B, and giving
the *orchestrator* thinking is worth +18.2 GAIA and +36.7 AIME, while giving the
*workers* thinking is worth marginal or negative amounts. ProST
(arXiv 2509.04508v2) reaches the same conclusion from the other side: a 14B
planner with 7B workers beats 7B/14B/14B on the Pareto front at equal parameters.

So the parameter budget goes into the middle brain, and the executor is the
smallest model that can follow one instruction. On the reference machine the
two are never in memory together - loading both is the difference between an
assistant and a machine that swaps the desktop out - so `tiers.py` owns at most
one llama-server and swaps the model when the tier changes, which costs a
reload of ten to thirty seconds and buys a machine that still works.

| Tier | Model | Job |
|---|---|---|
| executor | `spark-x2.5-1.7b-q4_k_m` (~1.0 GB) | reads one request, makes one tool call, reads what came back, retries once with the failure, or escalates |
| middle brain | `spark-x2.5-4b-q4_k_m` (~2.4 GB, 6 GB RAM) | reads the whole request plus the retrieved knowledge and writes the plan as a typed list of actions |
| router | `smollm2-360m-instruct-q8_0` (~400 MB) | optional; sorts a request into executor, brain or a plain answer |

Both ladder models are from Spark-X2.5 (iFLYTEK's SparkLLM series, Apache 2.0);
its published table puts the 4B at HLE 12.3 against Qwen3.5-4B's 8.6.
`smollm3-3b-q4_k_m` stays in the catalogue as an alternative executor with a
different tokenizer, and the 4 GB fallbacks remain
`qwen2.5-1.5b-instruct-q4_k_m` and `qwen2.5-3b-instruct-q4_k_m`.

`astra-ai setup --model <name>` installs a tier; `astra ai status` says which
ones are installed. Everything works with the executor alone - a task that needs
more than one step is then attempted in one step, and the reply says so.

### 1.2 Why the tool calls cannot be malformed

A small model asked politely for JSON produces broken JSON. `llm.py`'s
`ask_json()` therefore sends llama.cpp a JSON schema, and llama.cpp constrains
generation to it: the tokens that would break the schema are never generated, so
a tool call is either valid or empty. `enable_thinking` is forced off for the
same reason - llama.cpp issue #20335 documents that grammar enforcement is
silently skipped when a model's thinking mode is enabled, which would leave the
constraint that this whole design rests on turned off.

The catalogue the model may choose from is closed (`actions.ACTIONS`, 30-odd
entries, 32 in the current build), the planner's grammar refuses a step that
names anything outside it, `_prune_args()` drops an argument the action does not
take, and `execute()` refuses the irreversible actions unless the caller passes
`confirmed=True`. The model cannot widen its own vocabulary.

### 1.3 The journal, and why it is visible

The two largest measured failure modes of small-model agent systems are
bookkeeping, not reasoning: step repetition (15.7%) and not knowing they are
finished (12.4%) - MAST, arXiv 2503.13657, 1600+ annotated traces across seven
frameworks. `journal.py` fixes both by writing the plan to SQLite **before** it
runs, tracking which step is next, and re-rendering `plan.md` on every state
change:

```
$ astra ai journal
journal: ~/.local/share/astraos/ai/journal.sqlite3
plan.md: ~/.local/share/astraos/ai/plan.md
  ok           4
  needs_human  1
  awaiting a human:
    #12 run_command: the assistant wants to run this command (command='pdftotext report.pdf -')
```

`needs_human` is not a failure. A step a person declined is recorded as the
correct outcome of that conversation, and the journal shows what was asked and
what was answered, so saying no is auditable rather than silent.

### 1.4 Skills, and the knowledge they come from

A skill is one `SKILL.md` file in a named directory, and there are two places
they live: `/usr/share/astraos/ai/skills` (shipped, root-owned, read-only) and
`~/.local/share/astraos/ai/skills` (yours). Write a file into yours and the
next question can use it:

```
# Summarise a PDF

keywords: pdf, extract, text, document, summarise
requires: pdftotext
when: the user wants the contents of a PDF as text or as a summary
---

## Steps

1. Find the file with search_files, then pass its path to read_pdf.
2. read_pdf runs pdftotext -layout and returns the extracted text.
3. Say in three bullets what the document is about, and name the file.
```

Eight skills ship with the assistant (PDF and documents, finding and organising
files, summarising documents, offline email triage, a read-only system health
report, screenshots, locale and timezone, backup and sync). Each one lists what
it needs, and a skill whose requirement is missing says so instead of failing
half-way through - `astra ai skills` shows which.

Alongside them is the knowledge pack: this distribution's own documentation,
rewritten as short procedures with the exact commands, so the assistant quotes
the machine instead of guessing. It is indexed with SQLite FTS5 (BM25, weighted
so an author's keyword beats prose), which is in the standard library and needs
no model. The search that produced this doc's answers is tested against the
corpus in `tests/static/test_astra_ai_brain.py`, and a question the corpus does
not cover returns nothing at all - never the nearest thing that looked
plausible, because "I could not find that on this machine" is the difference
between an assistant and a confident liar.

---

## 2. The safety model

Five rules, all of them structural rather than advisory:

1. **The repertoire is a whitelist.** The assistant can only propose actions that
   exist in `actions.ACTIONS` in the installed Python package. The repertoire is
   written in a file you can read; there is no plugin directory, no shell escape,
   and no way for a model, a page, or another program to add an action at
   runtime. The server re-checks the plan itself before executing it
   (`server.py`, `plan_refusal()`): a plan that does not name a real action is
   refused even if some client asks for it directly.

2. **Nothing destructive runs without a human confirming it.** A reply that
   proposes an action arrives as an *action card* in the page, showing the
   action's name, its human-readable summary and - for destructive ones - the
   command that would run. It sits there until Confirm is pressed. Cancel, or
   closing the page, runs nothing. The confirm step is a separate request
   (`POST /api/confirm`); the chat stream itself only ever proposes.

3. **Unprivileged.** The server and the actions run as your user account, with
   your permissions. `astra ai` never asks for a password, never calls `sudo`,
   and cannot do anything you could not type into a terminal yourself.

4. **No boot service.** There is no systemd unit, no autostart entry, no cron
   job. The assistant exists only while you are running it. Nothing at login,
   shutdown or recovery invokes it, and uninstalling the package leaves the
   system untouched.

5. **The image ships a working assistant; everything after that is opt-in.**
   The image ships the executor tier (`spark-x2.5-1.7b-q4_k_m`, about 1.0 GB),
   the tiny English speech model (`whisper-tiny.en`, about 74 MB) and both
   engine variants, so a live session and a fresh install answer without a
   network. The image build fetches those exact bytes once and verifies them
   against `/etc/astraos/ai-bundle.conf`; nothing is fetched when the assistant
   starts. The middle brain (`spark-x2.5-4b-q4_k_m`, about 2.4 GB), the other
   tiers and a runtime built from source remain opt-in and appear only by a
   setup command that says what it is about to do first: `astra ai setup`
   (local files and guidance), `astra-ai setup --model NAME` (the catalogue),
   or `astra-ai setup --build llama` (compile the runtime from source).
   An image built without the bundle still works: `/api/health` reports not
   ready, and the page explains how to finish the setup.

One thing that is *not* a boundary: the `--lan` mode. A device that is not the
computer itself cannot use the page until it pairs - `astra-ai pair` shows a
six-digit code on the PC, the phone enters it once, and `astra-ai unpair` takes
the access away again. That is still not a strong boundary, and the honest
limits are: there is no TLS, so the code and the paired token travel in clear
text on the local network; a paired token is trusted until it is revoked; and
someone at the PC can always act without pairing at all. Actions additionally
require confirmation *in the page that proposed them*, so a stranger can propose
but the person at the PC decides. The server says its own version of all this in
one line at startup:

```
note: every device on the local network can reach this page, and only a paired phone can use it; actions still need confirmation in the page
```

Use `--lan` on a network you trust, for the minutes you need it, and stop the
server afterwards (`astra ai stop`), which revokes every paired phone.

---

## 3. Hardware limits

AstraOS targets old, ordinary hardware, and the assistant is sized for **Sandy
Bridge-era machines** (Intel second-generation Core, around 2011) because those
are exactly the PCs the project exists for:

| Constraint | Consequence |
|---|---|
| Sandy Bridge CPU: AVX but no AVX2, no FMA | llama.cpp runs, but slower than any modern benchmark video suggests |
| No usable GPU compute (HD 2000/3000 has no Vulkan/usable OpenCL path for inference) | **CPU inference only**; there is no GPU offload to enable |
| 4-8 GB RAM on a typical such machine | Stick to models that fit comfortably; a 3B model plus the desktop is about the ceiling on 4 GB |
| CPU-only throughput | Expect a few words per second with a 1B model and fewer with a 3B. This is a conversation, not autocomplete |

The supported model profile is therefore deliberately narrow:

* **1B to 3B parameters**, quantised to **Q4** (Q4_K_M is the usual choice).
  Smaller quantisations get noticeably worse at following the action format;
  larger models cross from "slow" to "unusable" on this class of CPU.
* A 1B Q4 file is roughly 0.7-0.9 GB on disk, a 3B Q4 file roughly 1.7-2.2 GB.
* Speech recognition (whisper.cpp) follows the same rule: the `tiny` or `base`
  model, not larger. Transcription is slower than real time on these CPUs; a
  10-second recording may take tens of seconds on the smallest whisper model.

There is no benchmark table here because none has been measured on the reference
hardware. What exists is the instrument that would produce one - `astra-ai eval`
(section 4.1) - and the rule that its numbers travel with the model name they were
measured on. If you measure words-per-second on a specific model and CPU, a report
is welcome (`CONTRIBUTING.md`); until then treat the numbers above as the design
envelope, not as measurements.

---

## 4. Setting it up

The image is not a blank assistant. It ships the executor tier and the tiny
speech model under `/usr/share/astraos/ai/models`, and both engine variants under
`/usr/lib/astraos/ai/engine`; `/usr/local/bin/llama-server` picks the newest
variant the CPU actually lists. A fresh live session or install therefore answers
without a network and without a setup command. The middle brain is the part that
is opt-in, because it is 2.4 GB and only upgrades an assistant that already works.

`astra ai setup` remains the guided starting point. It creates the two directories
the package expects, reports what is already present, and says what is missing:

1. **The middle brain** - `astra-ai setup --model spark-x2.5-4b-q4_k_m`
   (about 2.4 GB, 6 GB of RAM). Without it the assistant plans one step at a
   time and says so. A model you already have can be imported locally:

   ```bash
   astra ai setup ~/Downloads/some-model-q4_k_m.gguf
   ```

2. **A runtime you build yourself** - `astra-ai setup --build llama` compiles the
   pinned source for this CPU. A `llama-server` already on `PATH` or in the
   assistant's bin directory is used as well.

Optional, but needed for the neural voice:

* text-to-speech for the "PC speakers" option. `espeak-ng` is what the image
  ships and what the assistant prefers; `espeak` and `spd-say` are also used
  when they are the ones installed. A neural voice (Piper and its model files)
  is **not** supported yet, and the honest reason is that it is a second
  download plus a voice to choose before the machine can say anything - the
  assistant has to answer with whatever the machine already has;
* speech-to-text already works: the image ships `whisper-cli` and
  `ggml-tiny.en.bin`, so a recording is transcribed with no build and no
  download. `astra-ai setup --build whisper` replaces the shipped binary for a
  user who wants to build it.

If you would rather download than supply your own, the package's command line
tool has a catalogue: `astra-ai setup --list` shows it, `astra-ai setup --model
NAME` fetches one model, and `astra-ai setup --build llama` (or `whisper`, or
`all`) compiles the runtime from source. `astra-ai setup --voice` covers both
halves of voice. Each is an explicit command; nothing downloads on its own.

Compiling on this hardware takes about twenty minutes of every core, so the
distribution builds the runtime for itself: every change under
`packages/astraos-ai/root/usr` triggers the **Build AI engine** workflow, which
runs `astra-ai setup --build all` once per CPU variant - `avx` for the Sandy
Bridge class, `avx2` for Haswell and later - proves each result (the avx build
on an emulated Sandy Bridge with a real model; the avx2 build natively, with
its 256-bit code checked and a guard that the runner really lists AVX2), and
publishes the two tarballs as the `ai-engine-2026-10-19` release. The image
build downloads those release assets, verifies their SHA-256, and installs both
variants, so the ISO does not depend on a CI artifact that expires.
one whose name matches the machine, copy `llama-server` and `whisper-cli` into
`~/.local/share/astraos/ai/bin/`, and `astra-ai status` shows the path it found
(and complains when the recorded requirements do not match the CPU) - the
number of compilers you had to run stays zero.

After any of this, `astra ai status` reports whether the model is ready, and
`astra ai start` serves the page. The server never needs a restart to notice a
missing tool: each endpoint reports "not installed" with the command that would
fix it.

### 4.1 Measuring what you installed (`astra-ai eval`)

"It runs" and "it answers well" are different claims, and the second one needs a
number before it is worth repeating. `astra-ai eval` runs the fixed task suite
(`docs/ROADMAP.md`, Stage 2):

* **Eight tasks, deterministic checks.** Five go through the same call a question
  uses (*answer* tasks: arithmetic, a capital, a three-line format, a translation,
  a one-sentence summary); three go through the worker's constrained JSON
  interface (*execution* tasks: an answer, an action, and a refusal). Every check
  is a script's decision - "did the answer contain 42" - never a model's or a
  human's opinion, so the same answers score the same way twice.
* **Two scores, counted apart.** A model that chats well and cannot emit a valid
  tool call is a broken assistant, and one percentage would hide which half is
  missing. The report prints answer quality and execution quality separately, and
  each failure carries its reason and the answer it read.
* **Tokens per second from the engine's own numbers.** What gets divided is the
  usage block llama-server returns with each answer; when the engine reports none,
  the report says "not reported" instead of estimating tokens from words.
* **A file, not a screenful.** The report is JSON under
  `~/.local/share/astraos/ai/eval/` (beside the models), named by date and model,
  so this week's run can be read beside last month's.

What the numbers are **not**: they describe the model file and the machine named
in the report, not AstraOS. A run with the 360M smoke model is a smoke test of
the suite itself, never answer quality - the report says so in its own text, and
the CI workflow uploads such a run as a smoke result, not as a benchmark. Run the
suite once per model that matters to you and keep each report with its model name;
that is what makes two reports comparable instead of decorative.

Run it with `astra-ai eval` (or `astra ai eval`). `--limit N` runs a prefix of the
suite for a quick check, `--json` prints the report for a script, and `--stop`
ends the model server when the suite is done. A task the model failed is a
measurement, not an error: the exit status is 0 whenever a report was written, and
1 only when there is no engine to measure with.

---

## 5. The phone as a microphone

Some desktops - particularly the older ones this project targets - have no
microphone, but the user is holding a phone. The assistant can use it:

1. Start the server in LAN mode on the PC: `astra ai start --lan`. It prints an
   address such as `http://192.168.1.20:8765/`.
2. On the PC, run `astra-ai pair`: it shows a six-digit code that is valid for
   ten minutes and pairs one phone.
3. Open the address on the phone, on the same network, and enter the code in the
   pairing banner.
4. Tap the microphone button and speak. The transcription appears in the PC's
   input box; press Send there (or on the phone).

There are two ways the page listens, and it uses the better one available:

* **Browser speech recognition (preferred).** Where the browser provides the
  Web Speech API, the page asks for on-device transcription
  (`processLocally`) when the browser supports it. Where it does not, some
  browsers route audio to their vendor's speech service - that is outside
  AstraOS's control, and the page's promise "nothing leaves this computer" is a
  statement about *its own* requests, not about the browser's. If that matters to
  you, use the recorded-audio path below, or check your browser's behaviour.
* **Recorded audio through whisper (fallback).** Where there is `MediaRecorder`
  but no usable speech recognition, the page records, converts the recording to
  16 kHz mono WAV in the browser itself, and posts it to the PC
  (`POST /api/transcribe`), where `whisper.cpp` transcribes it. Nothing about the
  audio leaves the local network. Without whisper installed, the server answers
  with a 503 and a message saying to run `astra ai setup`.

Two honest caveats:

* **Browsers require a secure context for microphones.** Most treat
  `http://` addresses other than `localhost` as insecure, so a phone opening the
  PC's plain `http://192.168.x.x:8765/` address may refuse the microphone
  outright. Browser speech recognition often still works in that situation,
  because it is a different permission. If neither works, listen on the PC side:
  run the page at `http://127.0.0.1:8765/` on the PC itself (which *is* a secure
  context) with a microphone attached.
* **Pairing is a bearer code, not an account.** The page itself opens for anyone
  on the network, but it only answers a phone that has entered the code shown by
  `astra-ai pair`; the token is kept by that browser, and `astra-ai unpair`
  revokes every phone. On plain HTTP a watcher on the same Wi-Fi can see the
  traffic (see the no-TLS entry below). Confirmation protects execution; a
  paired phone is trusted for conversation.

---

## 6. What is deliberately not included yet

The ladder changes nothing here except to add a requirement of its own: the
middle brain is a 2.4 GB download the user chooses to make, and a machine with
4 GB of RAM will not run it well. That is stated in `astra ai status` and in the
knowledge entry, rather than being smoothed over.

Stated so the omissions are decisions, not surprise gaps:

* **No wake word, no always-listening mode.** The microphone is open only while
  the button says it is. The ring pulses when it is listening or speaking - that
  is the indicator, and it is the whole story.
* **No cloud models and no API keys.** There is no configuration for an online
  provider; the page makes no external request even to check one.
* **No arbitrary shell.** The action repertoire is fixed and small. "Run this
  command for me" is answered by explanation, not execution.
* **No vision, no image input, no attachments.** Text and voice only.
* **The model server can be confined; the actions are not.** When bubblewrap or
  firejail is installed, the engine runs `llama-server` in a read-only cage (the
  whole root and the model folder read-only, with private `/tmp` and `/dev/shm`),
  and `sandbox: on` in the settings refuses to start without one; `auto` is the
  default and reports the fallback, and `astra-ai status` prints the probe. The
  network stays shared because the page talks to the server over `127.0.0.1` —
  a private network namespace would make it unreachable — and Landlock is not
  used. The actions themselves run as you, with your rights: there is no
  AppArmor profile or container around them.
* **No automatic undo.** `astraos/ai/undo.py` takes copy-based snapshots and
  restores them, with tests, but no privileged action takes one yet and there is
  no `astra-ai undo` command.
* **No TLS, with pairing as the whole access control**, covered above.
* **No automatic updates.** Nothing fetches or replaces a model on its own.
  The catalogue downloader (`astra-ai setup --model NAME`) runs only when
  typed, and `astra ai setup` itself only imports files you already have.
* **No persistence of conversations.** A reload forgets the transcript; the
  history lives in the page's memory and in the model's context window, nowhere
  else.
* **No GPU acceleration plan for this release.** If a future machine can use it,
  that is a future decision; Sandy Bridge cannot.
* **No measurements section.** As in `HARDWARE_COMPATIBILITY.md`, nothing here
  has been benchmarked on the reference machine yet. The evaluation suite
  (`astra-ai eval`, section 4.1) is the instrument; a number is published only
  with the model name and the machine it was measured on.

---

## 7. Where the checks live

* `tests/static/test_astra_ai_server.py` - request parsing, the event framing the
  page depends on, the not-ready path, the refusal of plans outside the action
  repertoire, and the "no external addresses in the page" rule. It runs without
  a network, a model or a display.
* `tests/static/test_astra_ai_eval.py` - the suite's scoring: every task can pass
  and can fail, a failure keeps its reason and the answer it read, the two scores
  are counted apart, tokens per second is the engine's own count or is absent,
  and a machine with no engine gets one actionable line and exit 1 instead of a
  report full of zeroes.
* `tests/static/test_astra_ai_sandbox.py` - the model server's cage: a read-only
  root and model folder, private `/tmp` and `/dev/shm`, the loopback the page
  needs, `probe()` telling "installed" from "can start", and `sandbox: on`
  refusing to start without one.
* `tests/static/test_astra_ai_undo.py`, `test_astra_ai_missions.py`,
  `test_astra_ai_limits.py` and `test_astra_ai_benchmark.py` - snapshots and
  rollback, progress read from the journal, the model-server memory cap, and the
  three-task benchmark.
* `astra ai status` - the on-machine answer to "is it actually working".

The usual rule applies: an unperformed check is never a pass. If the assistant
has not been used on your machine, its status is "unknown", not "works".
