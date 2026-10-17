# Setting Up The Assistant

keywords: assistant, setup, astra ai, astra-ai, model, gguf, llama.cpp, llama-server, build, whisper, voice, espeak, start, stop, journal, skills, avx

The assistant is two pieces and neither is bundled: a model file and the llama.cpp
runtime. `astra ai setup` is the guided starting point - it creates the two directories
the package expects (`~/.local/share/astraos/ai/models` and `~/.local/share/astraos/ai/bin`),
reports what is already there, and tells you which of the two is missing. If you already
have a GGUF file, import it yourself with `astra ai setup ~/path/model.gguf`, which
copies it into the model directory - this is the whole download-free path, and nothing
is fetched at any point.

To fetch a model instead, use the package's own catalogue: `astra-ai setup --list` shows
it, and `astra-ai setup --model NAME` downloads one entry. Copy the names exactly from
that list, because a name that is not in it fails with `unknown model`.

There are two tiers to install, on purpose, and the order matters:

`spark-x2.5-1.7b-q4_k_m` is the **executor**, about 1.0 GB. It is the one that is always
needed: it reads a request, runs one action, verifies what happened and reports back.
`smollm3-3b-q4_k_m` (about 1.8 GB) is the alternative executor, a different model family,
if you would rather carry a 3B.

`spark-x2.5-4b-q4_k_m` is the **middle brain**, about 2.4 GB, and it needs 6 GB
of RAM or more. It is the one that plans multi-step work, and installing it is what turns
the assistant from a one-command tool into something that can do a task. The two are
separate commands because loading both at once on a machine with 4 GB is the difference
between an assistant and a machine that swaps your desktop out - the assistant loads one
model at a time, and a plan costs a reload of about ten to thirty seconds.

For machines that cannot afford those, the catalogue has smaller alternatives:
`qwen2.5-1.5b-instruct-q4_k_m` (about 1.1 GB) as the executor and
`qwen2.5-3b-instruct-q4_k_m` (about 1.9 GB) as a middle brain for 4 GB.

If you have fine-tuned a model yourself, or downloaded a GGUF from somewhere else, import
the file directly with `astra ai setup ~/path/to/your.gguf` and no download happens at
all. That is the supported path for a custom model, and it is the one a fine-tuned model
should take.
The runtime is the `llama-server` binary, on `PATH` or in the assistant's own bin
directory. `astra-ai setup --build llama` builds it from upstream source, and there is a
real reason to prefer that over downloading a release binary: on this class of CPU - AVX
but no AVX2, no F16C, no FMA, no BMI2 - a prebuilt binary dies immediately with an illegal
instruction, and the build only takes a few minutes.

The build has one variant per CPU class, chosen with `--variant`:

* `avx` (the default) turns AVX on and AVX2, F16C, FMA and BMI2 off - the Sandy Bridge
  this release is tested on has exactly AVX. FMA and BMI2 matter as much as AVX2: they
  are Haswell features and the build enables them by default even with AVX2 switched
  off, which produced a server that died with SIGILL and no output at all on the first
  model it loaded.
* `avx2` turns AVX2, F16C, FMA and BMI2 on - most of ggml's speed on Haswell and later.
* `auto` picks the newest variant this machine's CPU can run, read from `/proc/cpuinfo`.

Both variants pass `-DGGML_NATIVE=OFF -DGGML_AVX512=OFF -DGGML_BLAS=OFF
-DBUILD_SHARED_LIBS=OFF`: never the build machine's own instruction set, no AVX-512, and
one self-contained installed file instead of an executable that still needs the build
tree for its libraries. A named variant is checked against `/proc/cpuinfo` before the
first compiler runs - `--variant avx2` on a machine without AVX2 is refused with that
reason, because the resulting binary would die with SIGILL on the first question - and
the choice is recorded beside the installed binaries, which `astra-ai status` checks
against the CPU. The same applies to whisper with `astra-ai setup --build whisper` (or
`--build all` for both).

There is a third way that skips the compiler without risking the wrong CPU: AstraOS's own
CI builds both programs for both variants (the Build AI engine workflow) and publishes
each as a workflow artifact together with `SHA256SUMS.txt` and `BUILD-INFO.txt`:
`astra-ai-engine-linux-x86_64-avx` runs on Sandy Bridge and later,
`astra-ai-engine-linux-x86_64-avx2` needs Haswell or later. Download the artifact whose
name matches the machine, copy `llama-server` and `whisper-cli` into
`~/.local/share/astraos/ai/bin/`, and `astra-ai status` shows the path it found. A binary
downloaded from anywhere else is still the thing to avoid: nobody there built it for this
CPU.
Voice needs one more thing: `astra-ai setup --voice` covers espeak-ng for speaking and a
whisper model for transcribing, and `astra ai say TEXT` speaks a line through the
machine's own speakers.

Once a model is ready, `astra ai start` serves the page at `http://127.0.0.1:8765/` and
`astra ai open` opens it in the browser; `astra ai stop` stops it, and Ctrl+C in the
terminal also does. `astra ai status` answers "is it running, is a model installed" at
any time. `astra ai start --lan` makes the same page reachable from other devices on the
local network, which prints a warning line for a reason: there is no password and no TLS,
so anyone on that network can open the page and chat, though actions still require a
confirmation in the page they are watching. Use it on a network you trust, for the
minutes you need it, and stop the server afterwards.

`astra ai` with no subcommand prints the list it supports. `astra ai journal` shows what
the assistant has done - the tasks, the steps, the commands that ran - and `astra ai
skills` lists the skill files installed, both the ones AstraOS ships under
`/usr/share/astraos/ai/skills/` and your own in
`~/.local/share/astraos/ai/skills/`; a skill in your own directory wins over the shipped
one of the same name. `astra-ai actions` prints the fixed list of things the assistant
may do, and `astra-ai ask QUESTION` asks a single question without the page. Both are
worth reading: the action list is the complete repertoire, and it contains nothing that
installs, upgrades or sends anything, because all of that would need root.
