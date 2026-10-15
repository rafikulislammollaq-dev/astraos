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

A local assistant, in three pieces:

| Piece | Installed at | What it is |
|---|---|---|
| Server | `/usr/lib/astraos/ai/server.py` | A small HTTP server, Python standard library only |
| Page | `/usr/share/astraos/ai/web/index.html` | One HTML file: styles and script inline, no external requests |
| Python package | `/usr/lib/astraos/ai/*.py` | Settings, the llama.cpp engine wrapper, the action repertoire, voice in/out |

Start it from a terminal:

```bash
astra ai start          # http://127.0.0.1:8765/ - available only on this machine
astra ai start --lan    # also reachable from other devices on the local network
astra ai open           # open the page in the browser
astra ai status         # is it running, is a model installed
astra ai stop           # stop it
```

The model runs on this computer. The page makes no request of any kind except to
the server that served it; there are no fonts, scripts, trackers or telemetry to
fetch, and none of it would work on a machine with no internet connection anyway.
That is a product property, checked by `tests/static/test_astra_ai_server.py`,
which fails if an external address appears in the page.

The assistant answers questions about the system, and it can carry out a small,
fixed list of actions (for example opening an application or reporting system
status). It is a normal program running as you: it has your rights and no others.

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

5. **Downloads are opt-in.** Nothing is fetched when the package is installed or
   when the assistant starts. A model or a tool appears only by a setup command
   that says what it is about to do first: `astra ai setup` (local files and
   guidance), `astra-ai setup --model NAME` (the catalogue), or
   `astra-ai setup --build llama` (compile the runtime from source).
   A machine with the package installed and no model still works: `/api/health`
   reports not ready, and the page explains how to finish the setup.

One thing that is *not* a boundary: the `--lan` mode. There is no password on the
page, no TLS, and anyone on the same network who can reach the address can chat
with the assistant and see its answers. Actions still require confirmation *in
the page they are watching*, so a stranger can propose but the person at the PC
decides. The server prints this in one line at startup, and the sentence is part
of the interface on purpose:

```
warning: this page is open to every device on the local network; actions still require confirmation in the page
```

Use `--lan` on a network you trust, for the minutes you need it, and stop the
server afterwards (`astra ai stop`).

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

There is no benchmark table here because none has been measured on real hardware.
If you measure words-per-second on a specific model and CPU, a report is welcome
(`CONTRIBUTING.md`); until then treat the numbers above as the design envelope,
not as measurements.

---

## 4. Setting it up (opt-in)

`astra ai setup` is the guided starting point. It creates the two directories the
package expects, reports what is already present, and explains the two pieces the
assistant needs. Neither is bundled, and neither is downloaded automatically:

1. **A model** - a GGUF file, 1B-3B, Q4, placed in the model directory that
   `astra ai setup` prints. If you already have one, import it locally:

   ```bash
   astra ai setup ~/Downloads/some-model-q4_k_m.gguf
   ```

2. **A llama.cpp server** - the `llama-server` binary, on `PATH` or in the
   assistant's bin directory (again printed by `astra ai setup`). Debian may
   package it (`llama.cpp`, `llama-cpp`) or you can build it; either way the
   binary must be executable by your user.

Optional, but needed for voice features:

* a text-to-speech tool for the "PC speakers" option. `espeak-ng` is what the
  image ships and what the assistant prefers; `espeak` and `spd-say` are also
  used when they are the ones installed. A neural voice (Piper and its model
  files) is **not** supported yet, and the honest reason is that it is a second
  download plus a voice to choose before the machine can say anything - the
  assistant has to answer with whatever the machine already has;
* `whisper.cpp` for transcribing recorded audio that the browser cannot
  transcribe itself.

If you would rather download than supply your own, the package's command line
tool has a catalogue: `astra-ai setup --list` shows it, `astra-ai setup --model
NAME` fetches one model, and `astra-ai setup --build llama` (or `whisper`, or
`all`) compiles the runtime from source. `astra-ai setup --voice` covers both
halves of voice. Each is an explicit command; nothing downloads on its own.

After any of this, `astra ai status` reports whether the model is ready, and
`astra ai start` serves the page. The server never needs a restart to notice a
missing tool: each endpoint reports "not installed" with the command that would
fix it.

---

## 5. The phone as a microphone

Some desktops - particularly the older ones this project targets - have no
microphone, but the user is holding a phone. The assistant can use it:

1. Start the server in LAN mode on the PC: `astra ai start --lan`. It prints an
   address such as `http://192.168.1.20:8765/`.
2. Open that address on the phone, on the same network.
3. Tap the microphone button and speak. The transcription appears in the PC's
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
* There is **no authentication**. Anyone else on the network can open the same
  page. Confirmation protects execution, not conversation.

---

## 6. What is deliberately not included yet

Stated so the omissions are decisions, not surprise gaps:

* **No wake word, no always-listening mode.** The microphone is open only while
  the button says it is. The ring pulses when it is listening or speaking - that
  is the indicator, and it is the whole story.
* **No cloud models and no API keys.** There is no configuration for an online
  provider; the page makes no external request even to check one.
* **No arbitrary shell.** The action repertoire is fixed and small. "Run this
  command for me" is answered by explanation, not execution.
* **No vision, no image input, no attachments.** Text and voice only.
* **No per-action sandbox.** Actions run as you, with your rights. There is no
  AppArmor profile or container around them.
* **No TLS and no authentication**, covered above.
* **No automatic updates.** Nothing fetches or replaces a model on its own.
  The catalogue downloader (`astra-ai setup --model NAME`) runs only when
  typed, and `astra ai setup` itself only imports files you already have.
* **No persistence of conversations.** A reload forgets the transcript; the
  history lives in the page's memory and in the model's context window, nowhere
  else.
* **No GPU acceleration plan for this release.** If a future machine can use it,
  that is a future decision; Sandy Bridge cannot.
* **No measurements section.** As in `HARDWARE_COMPATIBILITY.md`, nothing here
  has been benchmarked on real hardware yet. This document describes what is
  built and configured - not what has been proven.

---

## 7. Where the checks live

* `tests/static/test_astra_ai_server.py` - request parsing, the event framing the
  page depends on, the not-ready path, the refusal of plans outside the action
  repertoire, and the "no external addresses in the page" rule. It runs without
  a network, a model or a display.
* `astra ai status` - the on-machine answer to "is it actually working".

The usual rule applies: an unperformed check is never a pass. If the assistant
has not been used on your machine, its status is "unknown", not "works".
