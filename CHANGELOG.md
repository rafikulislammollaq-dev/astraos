# Changelog

All notable changes to AstraOS are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project uses [semantic versioning](https://semver.org/spec/v2.0.0.html) with the
following meaning for this project:

- **MAJOR** — a change that requires reinstalling, or that breaks package compatibility.
- **MINOR** — new functionality in a backwards-compatible way.
- **PATCH** — fixes and internal changes.

Because AstraOS is a distribution, a MINOR or MAJOR release also pins a new Debian base.
The pinned base is recorded in `VERSION` and `config/distribution.env`.

---

## [Unreleased]

### Added

- **A first-run welcome, shown once.** A new account's first login opens a page that
  says what the machine is (an independent distribution on Debian 13), what to try
  first (the assistant, the help centre, the dashboard, the phone pairing) and what
  has not been proven (no install on physical hardware, an unsigned image, an
  unsigned archive). It opens once: a marker in the user's state directory is what
  makes it a first-run thing rather than a habit, and the launcher says nothing at
  all when there is no page to show, so a login is never broken by it. The boot
  self-test checks that both halves - the page and the autostart entry that opens
  it - are really in the image.

- **Astra Doctor: a health report you can paste into a bug report.**
  `astraos-doctor` prints this machine's health - the release, the kernel, the CPU, the
  memory, the disks that are nearly full, the swap pressure, the units that failed,
  this boot's errors, the addresses and routes, the graphics card, the assistant's own
  state - and every line names the command or the file it came from, so a reader can
  check the number rather than trust it. It only reads: it never writes, never asks for
  a password and never runs anything as root, so it is safe to run on a machine that is
  already unwell. `--share` produces the same report with the user name, the host
  name, the home path, the addresses, the MAC addresses, the machine id and any serial
  number replaced, and says on its face that it did; `--json` is the same thing for a
  machine to read. Five tests run it against a fixture machine and a directory of stub
  commands, so what it prints is checked against what the machine said.

- **An offline help centre, generated from the pages the assistant already ships.**
  `scripts/build-help-center.py` turns the `knowledge/` pages and the `skills/` into
  one self-contained HTML file: every topic is in the page, a search box filters on
  the title, the keywords and the body, and nothing is fetched from anywhere - no
  external script, no stylesheet, no image - so it works on a machine with no
  connection at all. A launcher ("AstraOS Help") puts it in the desktop menu. The
  page is generated and committed, and a test regenerates it and compares, so it
  cannot drift from the corpus. First run pending: the page has never been opened
  in a booted image yet.

- **A proof page for every run, written from the run's own artifacts.**
  `scripts/generate-proof-page.py` reads what a run produced - the build log, the
  boot self-test log and its capture, the three boot-menu logs with the Secure Boot
  firmware's hashes, the install exercise and the APT archive - and writes one
  document: the image and its SHA-256, the structural checks, the self-test's own
  result, whether each firmware path reached the live login prompt, what the
  installer did and what the installed system then reported, and the archive's
  contents and signing state. Every line is read from an artifact; a missing
  artifact is written down as missing ("not shown in this run"), and the page ends
  with what the run does *not* prove. A new `proof` job downloads the artifacts,
  writes the page, appends it to the run summary and uploads it as `astraos-proof`.
  First CI run pending.

- **A software bill of materials for the packages the build produced.**
  `scripts/generate-sbom.py` writes an SPDX 2.3 document naming every AstraOS
  package with its version, its SHA-256, its supplier and its licence, plus the
  image's hash when it is given one. It reads each `.deb`'s own control data with a
  small `ar` reader, so it needs no `dpkg-deb` and runs anywhere Python does, and
  the document says plainly that Debian's packages keep their own licences. The
  build job writes it and uploads it as `astraos-sbom`. First CI run pending.

- **The model server can be caged, a changed file can be restored, and a running task
  can be watched (source; 42 tests, one skipped on this host, 2026-10-20).** Four
  Stage 3/4 gaps that earlier entries named as missing now have code and tests:

  * **Sandbox** (`astraos/ai/sandbox.py`): `llama-server` runs under bubblewrap (or
    firejail) with the whole root and the model folder read-only, private `/tmp` and
    `/dev/shm`, and `--die-with-parent`. `sandbox` in the settings is `auto` (the
    default), `on` (refuse to start without one) or `off`; `probe()` separates
    "installed" from "can start here", `auto` reports the fallback, and
    `astra-ai status` prints the result. The network stays shared because the parent
    talks to the server over `127.0.0.1`; a private namespace would make it
    unreachable. Thirteen tests in `tests/static/test_astra_ai_sandbox.py`.
  * **Undo** (`astraos/ai/undo.py`): copy-based snapshots with a manifest, exact
    restore of files and directories, removal of paths that did not exist, refusal of
    an id that is a path, and no deletion after a failed capture. Six tests in
    `tests/static/test_astra_ai_undo.py`.
  * **Missions** (`astraos/ai/missions.py`, `astra-ai missions [--json]`): real
    progress from the journal's executed step index, open states and pending
    approvals, never an invented percentage. Eight tests in
    `tests/static/test_astra_ai_missions.py`.
  * **Memory cap** (`astraos/ai/memory.py`): `memory_cap_mb` in the settings (default
    0, no cap) becomes `RLIMIT_AS` on the model-server child through `preexec_fn`;
    `astra-ai status` prints it. Eight tests, one skipped where `setrlimit` is
    absent, in `tests/static/test_astra_ai_limits.py`.
  * **Task benchmark** (`astraos/ai/benchmark.py`): three named tasks run through
    `Worker.handle` with pass/fail, the worker's own reason and per-task seconds; a
    crash is one failed task, not a failed suite. Seven tests in
    `tests/static/test_astra_ai_benchmark.py`.

  What is **not** proven here: the sandbox tests build the command and replace the
  wrapper, so no test has started a real `llama-server` inside bwrap; the memory cap's
  child test skips on the Windows development host; no snapshot is taken automatically
  before a privileged action and there is no `astra-ai undo` command; the benchmark
  tests use a fake worker and no pass rate has been measured on real hardware; and
  cgroups are still unimplemented (the module says so). `docs/ROADMAP.md`,
  `docs/AI.md` and `docs/SECURITY.md` now say what exists and what does not instead of
  "no sandbox" and "no undo".

- **The image ships a working assistant, and the research tool set it needs
  (source; 2026-10-20).** The live filesystem now carries the executor model
  (`Spark-X2.5-1.7B-Q4_K_M.gguf`, 1,107,457,856 bytes), the tiny English speech
  model (`ggml-tiny.en.bin`, 77,704,715 bytes), both engine variants (AVX and
  AVX2), the `llama-server`/`whisper-cli` selectors, and the model notices and
  licences. `0650-ai.hook.chroot` fetches each artifact from a pinned URL, checks
  its SHA-256 (and the models' byte counts) and refuses to finish the build on a
  mismatch; `0700-verify.hook.chroot` asserts the installed bytes, and
  `scripts/validate-iso.sh` now looks for them inside the squashfs rather than
  trusting the ISO surface. The exact URLs and hashes are in
  `/etc/astraos/ai-bundle.conf`; the engine release, model revision and hashes
  were checked against the live artifacts before this entry was written.
  `docs/AI.md`, `docs/KNOWN_LIMITATIONS.md` and the README no longer describe an
  empty assistant.

  The same batch completes Stage 4's first two items. The assistant can
  `read_pdf` (through `pdftotext`), `compare_files` (a unified diff),
  `write_file` (only inside `~/.local/share/astraos/workspace`, `modify` in
  Guard, needing the user's yes) and `verify_citations` (each quoted passage
  checked against a path, list, mapping or literal text). `write_file` is
  verified by reading the bytes back, and `verify_citations` by requiring every
  result to be true. A task now records `planning` while the middle brain is
  borrowed, `awaiting approval` while the confirmation is open, and `verifying`
  while the action is checked; a 100-tool-call budget pauses a looping task at
  the same resumable point as the time budget. Tests:
  `tests/static/test_astra_ai_workspace.py`, the new lifecycle and call-budget
  cases in `test_astra_ai_budget.py`, and the ISO/manifest checks in
  `test_astra_ai_bundle.py`.

  What is **not** proven here: the image has not yet been rebuilt with this
  bundle in this session, so the byte-level claims are pinned-input checks and
  repository consistency, not a completed ISO run. The build and the boot/install
  exercise are the next GitHub Actions runs; a green run is what will move the
  CI-evidence rows. `pdftotext` is exercised through the subprocess seam, not on
  a real PDF, because the static suite must run where poppler is absent. The
  memory cap exists but is off by default and its child test skips on this host;
  see the first entry above.

- **The installer installs AstraOS, and the installed disk boots on its own.** Run
  39242006646 (2026-10-19) is the first green install exercise in this repository's
  history: the ISO booted, its own Calamares UI was driven through every page, all 27 jobs
  ran with `rc=0`, the disk then booted **with no ISO attached**, the LightDM greeter
  appeared, and the image's self-test reported `PASS (51 checks, 0 failed)` in installed
  mode. Getting there took a different named defect in every exercise; the last two were
  the bootloader config that replaced Calamares' own incompletely and the `mount` config
  that did not exist at all (both in `### Fixed` below), and one host-side bug followed
  (also below). The green run's evidence artifact records which Calamares module configs
  the medium carried, with hashes, and the hashes of the configs it ran on — so this is a
  measurement, not a claim.

  **What it does not prove matters as much as what it does.** The installation was legacy
  BIOS, one ext4 partition, no encryption and no swap; the disk was virtual; the greeter
  was photographed but nobody logged in; and the installed system boots the *live* image's
  initramfs, because nothing in the Calamares sequence regenerates one. Those rows stay
  `UNTESTED` in `docs/KNOWN_LIMITATIONS.md`, and the green run does not move them.

- **A driver fix no longer pays for an ISO rebuild: the exercise can run against a stored
  ISO (source; `.github/workflows/install-test.yml`).** The install exercise is
  host-side — `config/live-build/config/includes.chroot` carries only `etc` and `usr`, so
  nothing under `scripts/` is ever inside the image, and a change to the driver, to its
  tests or to these documents does not change one byte of the ISO. The workflow takes the
  `astraos-iso` artifact a previous `build-iso.yml` run already archived (fourteen days),
  from the run named by `run_id` or the newest run that has one, and runs exactly the
  exercise the `install-boot` job runs — same script, same flags, same runner, same
  ceiling, same evidence artifact — with no build in front of it. That removes roughly
  eighteen minutes of packaging from every attempt at a loop expected to run many times:
  run 39103628321 spent 25m27s to reach a 5m32s verdict, and run 39105685521 spent
  1h10m11s, in both cases behind a build the previous attempt had already paid for. The
  rule it encodes: rebuild when the image's contents change (packages, hooks, branding,
  the Calamares modules, the live configuration); test against the stored ISO when only
  the driver changed. Pinned by two tests in `tests/static/test_install_boot.py` — one
  holding the claim that justifies the shortcut (the driver is not inside the image's
  include tree), one holding the stored-ISO workflow to the same script, flags, runner
  and artifact so the two cannot drift apart.

- **The assistant can find and read the user's documents, and only those (source; 8
  tests, 2026-10-19).** Stage 4's flagship task starts with "find the documents about
  X", and there was no way to find one. `search_files` walks the user's Documents,
  Desktop, Downloads, Pictures, Music and Videos for a name, and `read_file` returns a
  text file from them. Both are `observe` in Astra Guard — a read changes nothing, and
  the audit log records it — so the model can use them without a confirmation and the
  user can still see what was read.

  The roots are a short allowlist rather than a denylist of secrets, because a denylist
  is wrong the moment a new program writes a secret somewhere. The path is resolved
  *before* the check, so a symlink inside Documents that points at `/etc` resolves to
  `/etc` and is refused; a file beside Documents is refused even when the path is
  relative. Binary files are refused rather than decoded into noise, files over 1 MB
  are refused rather than becoming a one-megabyte answer, and the search stops at 50
  matches or 20,000 files rather than walking a home directory forever. Tests use
  `ASTRAOS_FILES_HOME` to point the six folders at a temporary home; a test that reads
  the developer's own Documents would fail on a machine without one and pass for the
  wrong reason.

  Not done, and named so it is not assumed: there is no PDF text extraction, no
  document comparison, no writing into a workspace, and no citation verifier yet. This
  is the read half of the tool set, not the whole of it.

- **A task has a step budget and a time budget (source; 6 tests, 2026-10-19).**
  `docs/ROADMAP.md`, Stage 4 asks for budgets so a weak model cannot loop forever. A
  plan longer than twelve steps is now refused before it becomes a task — `"The plan
  has 13 steps and one task runs at most 12. Nothing was started"` — because a plan
  that never starts should not leave a row somebody has to dismiss. A task that
  spends 900 seconds is filed `paused` where it stopped rather than `failed`: the work
  is unfinished, not wrong, and `astra-ai resume` continues at the next step. Both
  entry points use the same check — the collected path (`astra-ai work`) and the
  streaming path (the web page) — since a budget one of them skips is not a budget.
  The clock is injected, so the tests move it instead of waiting; six of them in
  `tests/static/test_astra_ai_budget.py` cover the refusal, the plan exactly at the
  limit, the pause, pausing then resuming to completion, and the streaming path.

  Not done, and named so it is not assumed: there is no memory cap (that needs a
  cgroup or `setrlimit` around the model server) and no separate tool-call count (a
  step is the only unit the catalog has).

- **A stopped task can be resumed, and it remembers where it came from (source; 9
  tests, 2026-10-19).** The journal already stored the plan before the first step ran,
  every attempt and the step index, and its comment said that "a crash on step two
  leaves nothing for a human to resume from" - but nothing read that state back: the
  list of unfinished tasks was for looking at. `astra-ai resume` now continues one.
  With no id it lists the tasks that are open (including the new `paused`); with an id
  it starts at the first step that did not succeed, so a failed third step is retried
  rather than skipped, and a step that succeeded is not run twice. Resuming needs no
  model to start: the steps are already decided, and `astra-ai work` and
  `astra-ai resume` ask the same terminal question through one shared function.

  The task now carries the provenance of its plan. A plan written from a document
  stays a document's plan after a reboot, so the guard refuses it again rather than
  treating `resume` as a fresh, trusted request. Journals written before this change
  get the column by `ALTER TABLE`, reading their old tasks as the user's own; a test
  opens one and checks it. Nine tests in `tests/static/test_astra_ai_resume.py` cover
  the retry point, the skip point, the stopped plan, the finished task, the missing
  plan, provenance, `paused`, the migration, and the shared confirmation.

- **Astra Guard: four permission levels, a refusal of untrusted instructions, and an
  audit chain (source; 13 tests, 2026-10-19).** `docs/ROADMAP.md`, Stage 3 asks for a
  policy engine outside the model and a record that can be inspected afterwards.
  `astraos/ai/guard.py` supplies both. Every action in the catalog is classified
  `observe` (reads), `prepare` (reversible changes to the session), `modify` (can change
  or lose the user's work) or `privileged` (changes the machine or runs a command) in a
  literal dictionary, and a test compares it with `actions.ACTIONS`: adding an action
  without deciding its level fails the suite, and an unclassified action is refused at
  run time rather than guessed at. `evaluate()` denies anything above `prepare` unless a
  human has approved it, and names the resolved arguments and the effect — "type_text is
  modify ... and needs your yes", never "allow the assistant to type". `actions.execute()`
  is the single enforcement point, so the command line, the web page and the worker
  cannot take different paths around it.

  Retrieved documents are treated as data. `scan_untrusted()` recognises the shapes of
  an instruction smuggled into text the assistant read (ignore-the-previous,
  role-change, "run this command", "open this URL", exfiltration), the worker marks
  such a request `document`, and the guard refuses everything above `observe` for it —
  audited as a denial, with the reason a person can read. The fixtures order the
  assistant to open an exfiltration URL, run a command and type over a document; each is
  refused, a normal document is not, and the end-to-end test replaces the subprocess
  seam and asserts that the refused plan ran nothing.

  Every decision and outcome is appended to
  `$XDG_STATE_HOME/astraos/guard/audit.jsonl` as one JSON line carrying the digest of
  the record before it. `astra-guard audit` prints the ledger, `astra-guard verify` names
  the first edited or removed record, and tests prove both are caught. A privileged
  action whose record cannot be appended is refused, so the actions that matter never
  run unlogged. The chain is tamper-*evident*, not signed: someone who can write the
  file can rebuild the whole chain.

  `type_text` and `press_key` moved into the confirmation set as part of this: typing
  into the focused window can change a document or run a command in a terminal. The
  previous note in `actions.py` argued the other way — that asking for every phrase
  would make the feature useless — and the reversal, and why, is recorded there. The
  person is asked once per plan, with the exact text, not once per phrase.

  Not done, and named so it is not assumed: no sandbox (bubblewrap/Landlock), no undo or
  snapshots, and no security audit. The audit log protects against an edited line, not
  against an account that can rewrite the file.

- **The machine's profile now chooses the engine build and the ladder rung (tests,
  2026-10-19).** `docs/ROADMAP.md`, Stage 2's promise is that `astra-ai` picks the build,
  the quantization and the model rung itself, and the earlier readiness rung stopped at
  "ready / tight / unsupported" — a useful floor, not a choice. `machine.recommend()`
  now reads the same measured profile and returns the engine variant (avx2 only when the
  CPU lists all of avx2, f16c, fma and bmi2; avx otherwise; nothing without avx), the
  rung it can fill (`full` = executor + middle brain + router, `worker`, `router`, or
  `none`), the models that rung contains with their resident sizes, and the reason for
  every step, including the number that said no. The sizes are `docs/AI.md`'s table, not
  taste: 1.0 GB for the 1.7B, 2.4 GB for the 4B, 0.4 GB for the 360M, plus 1 GiB of free
  space. The choice is written into the profile JSON and printed by `astra-ai profile`
  and `astra-ai status`; three tests pin the reference machine to `avx` + `worker` and a
  Haswell-class 16 GiB machine to `avx2` + `full`, and pin the refusals (no AVX, too
  little RAM, too little free space) to a named reason rather than a shrug.

- **The engine now comes in the two CPU variants the machines actually need (source;
  both variants proven in CI, run 39244594257, 2026-10-19).** `docs/ROADMAP.md`, Stage 2 asks for engine
  builds selected from the machine's profile and for never installing an engine the CPU
  cannot run. `astra-ai setup --build` now builds one of two variants: `avx` (the
  default; AVX on, AVX2/F16C/FMA/BMI2/AVX512 off - the Sandy Bridge this release is
  tested on has exactly AVX) and `avx2` (the four Haswell features on, for Haswell and
  later), or `auto`, which reads `/proc/cpuinfo` and picks the newest the CPU can run.
  A named variant is checked against that file *before* the first compiler runs -
  `--variant avx2` on a Sandy Bridge is refused with the reason (the binary would die
  with SIGILL on the first tensor, measured 2026-10-16) instead of being built into the
  failure - and the choice is recorded in `ENGINE-BUILD.json` beside the installed
  binaries, which `astra-ai status` reads back and compares with the CPU, so a copied
  artifact built for another machine is flagged before the first question. The **Build
  AI engine** workflow becomes a two-variant matrix building through the same command a
  user runs (`--variant "${{ matrix.variant }}"`): the avx job keeps the static scan (no
  FMA/BMI2/F16C) and the emulated-Sandy-Bridge run, the avx2 job proves the opposite
  direction (the runner must list avx2; the disassembly must contain 256-bit code and no
  AVX-512), and the artifacts are named apart -
  `astra-ai-engine-linux-x86_64-avx` / `-avx2` - with `BUILD-INFO.txt` carrying the
  variant, its requirements and the flag list read out of `setup.py`, never retyped.
  Both variants stay `GGML_NATIVE=OFF` and one self-contained file.

- **The evaluation suite the model ladder was missing (source; first CI run recorded
  2026-10-17).** `docs/ROADMAP.md`, Stage 2 asks for fixed tasks and a published success
  rate before a model is described with confidence, and "the assistant works" said
  after one friendly question was the habit that had to go. `astra-ai eval` runs eight
  fixed tasks with deterministic checks — five through the same call a question uses
  (arithmetic, a capital, a three-line format, a translation, a one-sentence summary)
  and three through the worker's constrained JSON interface (an answer, an action, a
  refusal) — and scores **answer quality and execution quality separately**, because a
  model that chats well and cannot emit a valid tool call is a broken assistant and
  one percentage would hide which half is missing. Every failure keeps its reason and
  the answer it read; every check has a passing and a failing example pinned in
  `tests/static/test_astra_ai_eval.py`, because a check that cannot fail would score
  every model 100%. Tokens per second is the engine's own usage block (`llm.Engine`
  now records `last_usage` from each non-streaming answer) or says "not reported" —
  an estimate from words would be a false measurement. The report is JSON under
  `~/.local/share/astraos/ai/eval/`, named by date and model so runs can be diffed,
  and it names the model file and the machine it measured; the text report carries
  the sentence that stops a smoke-model run from being read as answer quality. A
  machine with no engine gets one actionable line and exit 1, never a report full of
  zeroes. The **Build AI engine** workflow now runs the suite on the 360M smoke model
  through the real CLI, asserts the report is well formed and scored both halves,
  uploads it as a smoke result, and states the distinction in its summary;
  `astra ai eval` passes through the `astra` dispatcher like the other sub-commands,
  and `docs/AI.md` section 4.1 explains what the numbers are and are not. The first
  run (run 39026539476, commit 1a309cb) recorded the smoke model at 4/5 answer and
  3/3 execution — including a failure the check named instead of waving through (it
  put the three colours on one line) — and 18.3 tokens/s from the engine's own
  counts; per the rule, that is a smoke result about the suite, not a quality claim
  about the model.

- **The virtual machines people try first now have their guest agents (first CI
  exercise green 2026-10-17, run 39028358504).** AstraOS is usually booted in a virtual
  machine before it is trusted with anything, and the image shipped none of the guest
  tooling: clipboard sharing, display resize and host-initiated clean shutdown depended
  on installing it by hand, and in VirtualBox they were impossible from Debian's own
  packages. `config/package-lists/35-hardware.list.chroot` now selects
  `qemu-guest-agent` (QEMU/KVM: clean shutdown, time sync, host queries),
  `spice-vdagent` (SPICE: clipboard and display resize) and `open-vm-tools` with
  `open-vm-tools-desktop` (VMware, both halves). Every name, path, unit and udev rule
  was read out of the pinned trixie packages themselves — the `.deb` files downloaded
  and opened — rather than guessed, and nothing needs enabling: the QEMU and SPICE
  agents are started by their packages' own udev rules when their virtio ports appear,
  and the VMware daemon's unit is conditioned on the hypervisor, so every agent is
  inert on every other machine and the same image behaves the same on bare metal.
  VirtualBox's Guest Additions stay absent, and now say why: Debian 13 packages
  `virtualbox-guest-*` only in its unstable suite, and this project ships only its
  pinned release — `docs/TROUBLESHOOTING.md` tells VirtualBox users to install
  VirtualBox's own Guest Additions ISO, which is what was always necessary. The image
  asserts the claim before the medium is packed: `0700-verify` checks the binaries, the
  units, the udev rules and the session autostarts, the boot self-test checks the four
  packages, and — where the caller provided the port a hypervisor would provide — that
  the agent they start is actually running, reporting a portless boot (the install
  exercise's disk boot) as a note instead of a silent pass. The service policy records
  the one enabled unit (VMware's, self-conditioned) and notes the two udev-activated
  ones so the audit explains them.

- **The boot exercise now talks to the guest agent (first run green 2026-10-17, run
  39028358504).**
  The guest's own self-test can only see that the agent's unit is active; the protocol
  is what a hypervisor actually uses. `scripts/smoke-boot.sh` now attaches a virtio
  serial port named `org.qemu.guest_agent.0` (host end in a unix socket) and, while the
  guest still holds its session, `scripts/qga-ping.py` performs the dialogue QEMU's
  documentation defines: `guest-sync-delimited` (which flushes channel noise and proves
  the peer echoes our id), `guest-ping`, then `guest-info` for the version — kept as
  `qga-host.log` beside the other evidence. An image that reported PASS with an agent
  that never answered fails the run; the guest half of the same claim lives in its
  `qemu-guest-agent` check. The client's framing is pinned on every host by
  `tests/integration/test_qga_ping.py` against a fake agent that prefixes messages with
  `0xFF`, emits events and non-JSON filler, and splits a message across reads — the
  shapes a real channel arrives in — plus a silent channel that must time out and a
  reply with the wrong id that must be refused.

- **The APT archive the packages were missing (CI assembled it on 2026-10-17, and the
  same job proves it apt-consumable — green the same day, run 39028358504).**
  An installed AstraOS got Debian packages and nothing else: no archive
  carried `astraos-*` updates.
  `scripts/build-apt-repo.sh` assembles the tree an installed system's apt can read:
  `pool/main/<package>/<file>.deb`, `dists/stable/main/binary-amd64/Packages` (and
  its gzip), and `dists/stable/Release` carrying both indices' sizes and hashes.
  With `--key` the Release is signed (`InRelease`, `Release.gpg`) and the public half
  is exported beside the index as `astraos-archive-keyring.gpg`; without a key the
  script says loudly that the output is unsigned — integrity without authenticity —
  and fit only for controlled use. It never generates or stores a key. Before
  reporting success it reads its own index back: every file named is opened again
  and re-hashed, and a mismatch fails the script — an index that does not describe
  its pool is worse than no archive. The build job assembles the repository from the
  packages it built and uploads it as `astraos-apt-repo`. Proved locally 2026-10-16
  (WSL): a host's own apt fetched the index from the assembled archive
  (`Get: ... stable/main amd64 Packages`, no errors) and the signed variant verifies
  (`gpg --verify InRelease` → Good signature). The first CI assembly is recorded
  (2026-10-17, run 39024106426: the build job assembled the tree from the packages it
  built and uploaded `astraos-apt-repo`, 5.9 MB). The job now also proves the archive
  is apt-consumable, not merely well-formed: a fresh `debian:trixie` container adds
  the tree as `deb [trusted=yes] file:/repo stable main`, `apt-get update` must
  succeed against it, and `astraos-system-tools` is installed out of the archive —
  its depends drags `astraos-base` in with it, and the step ends by requiring
  `astraos-release-info` to report back the exact version dpkg recorded, so apt
  reading the index, the files arriving and the installed package describing itself
  are all exercised at once. That step is green (run 39028358504: the fresh container
  installed `astraos-system-tools` 0.2.0 out of the tree). An *installed* system
  updating from a hosted archive remains untested: the hosting question is still open.

- **The machine's capability profile, measured (first run green 2026-10-17, run
  39028358504).** `astra-ai profile` reads `/proc/cpuinfo`, `/proc/meminfo`,
  `/proc/asound/cards`, `/sys/class/drm`, `/sys/class/accel` and free space as the
  running user — an unprivileged reading, never a privileged probe — prints the
  machine in plain words (CPU and instruction sets, RAM and swap, graphics,
  accelerator, audio, free on `/`) and writes the same numbers as JSON beside the
  assistant's settings (`~/.config/astraos/machine.json`). The AI-readiness rung
  ("ready" / "tight" / "unsupported") is derived from those measurements against
  the model ladder's documented sizes and the engine builds' actual requirements
  (AVX on; AVX2, F16C, FMA and BMI2 off), not from branding. `astra-ai status`
  makes sure the profile exists at first run and names its path. The boot
  self-test's new `ai-profile` check runs the command as the live user and
  requires the written file; that check is green (`ok ai-profile`, run 39028358504:
  measured as `astra` and written to `/home/astra/.config/astraos/machine.json`).

- **The ISO carries Debian's signed Secure Boot chain, firmware-verified (green
  2026-10-17, run 39028358504).** `config/live-build/auto/config` now asks live-build for
  `--uefi-secure-boot enable`: the EFI system partition gets the Microsoft-signed shim
  with Debian's keys embedded, a Debian-signed GRUB, and the kernel the chroot
  installs is Debian's signed one — a complete chain for a machine with Secure Boot
  enabled to verify, instead of an unsigned medium it refuses. The build host needs
  `shim-signed` and `grub-efi-amd64-signed` for live-build to copy from, and both are
  now in `scripts/bootstrap-build-environment.sh` (the image's own package list
  already carries them for installs). The new `boot-menu-test.sh --medium secure`
  boots the ISO under OVMF's Secure Boot firmware with the Microsoft keys enrolled:
  the key store is *required*, so a machine missing it fails the run with its own
  message rather than falling back to a blank store that would leave Secure Boot
  unenforced and the evidence worthless, and the exact firmware pair with its SHA-256
  sums is kept beside the serial log. The run reached the login prompt on 2026-10-17
  (run 39028358504): OVMF's Secure Boot firmware with the Microsoft keys enrolled
  verified the Microsoft-signed shim and the Debian-signed GRUB and kernel instead of
  refusing the medium, and the same run's BIOS and plain-UEFI boots reached it too.
  The README, the security documents and the limitations document now record it; the
  build manifest keeps `secure_boot=UNTESTED`, because a build cannot know how its own
  image boots.

- **The self-test starts the HUD for the screenshot.** The roadmap's HUD item wants
  a capture that carries the dashboard itself, and the dashboard is a full-screen
  application started from its launcher — not an autostart — so the live-medium
  self-test now starts `astraos-hud` as the live user from the shipped entry point,
  waits for its process under both its spellings (the `astraos-hud` shim and the
  `astraos_hud` module it execs), gives GTK its first frames, records the new
  `hud-on-screen` check and only then prepares the screen for the caller's capture; a
  dashboard that refuses to start fails that check and puts the tail of its log on
  the serial console instead of leaving a quiet, empty desktop in the picture. The
  installed-mode boot does not start it (an installed system shows a greeter, not a
  session). Green 2026-10-16, run 38919644411 (commit 8e40d99): `hud-on-screen` green
  in `RESULT: PASS (52 checks, 0 failed)`, and the capture — a 1280×800 PNG — shows
  the dashboard: the clock, the system and terminal panels, the memory and filesystem
  bars, and the endpoint card.

- **The installer is exercised end to end in CI, against the real Calamares UI
  (first CI run 2026-10-16 failed at QEMU startup; fix under Fixed).**
  `scripts/install-boot-test.sh` boots the built
  ISO in QEMU with `astraos.ci.install=1` on its command line, installs it onto a blank
  20 GiB disk through the ISO's own installer, and then boots that disk alone — no
  medium attached — and requires the image's own self-test in its installed mode. The
  switch is deliberately not the self-test's: the install driver's unit conditions on
  the exact word `astraos.ci.install=1`, and the self-test's unit was tightened from
  the bare prefix `astraos.ci` to the exact word `astraos.ci=1`, because systemd
  matches a condition without `=` against the beginning of a command line word — the
  shared prefix would have let each run during the other's boot, and a self-test that
  screenshots the desktop and powers the machine off mid-install would eat the disk.
  The wizard is driven from outside: the Next button is clicked through the pages
  whose defaults are correct (the one blank disk arrives selected with Erase
  pre-selected, through CI-only presets appended to copies of the shipped module
  configs — never edited into them, never duplicated), a per-run password generated
  on the host is typed into the users page's two password fields, and a screendump
  precedes every step so a wrong coordinate is visible in the evidence instead of
  guessed about. The
  installed half runs the self-test's new installed-mode branch — a login greeter
  instead of a live session, no autologin, no live account, and the installer's
  lock-down file verified from outside the installer — and the host additionally
  requires the login prompt to name the installed account's hostname. The guest half
  (`astraos-install` and its unit) ships in every ISO and starts only when its exact
  word is on the command line. The workflow gained the `install-boot` job
  (`install_boot` in the manual trigger; evidence uploaded as
  `astraos-install-test`). The first run failed at QEMU startup before the guest
  booted (see Fixed); the fix is in the tree, and the retry's outcome will be
  recorded here when it happens.

- **The firewall is on by default (first CI run green, 2026-10-16).** The decision
  recorded in the roadmap — ufw shipped disabled by design — is reversed: a firewall
  that waits to be enabled protects exactly the users who never enable it. `ENABLED=yes`
  now ships in `/etc/ufw/ufw.conf`, and the exceptions live in `/etc/ufw/user.rules`
  (IPv4) and `/etc/ufw/user6.rules` (IPv6): the assistant's page (`8765/tcp`,
  pairing-gated) and mDNS (`5353/udp`, what finds printers), both only from the private
  ranges. Everything else inbound is dropped and logged. DHCP replies were already
  allowed by ufw's own `before.rules`, which answers the old "it could break the
  installer's network" reason rather than ignoring it. The self-test now checks the
  active state, the deny default and the page rule, and the caller probes a port no rule
  allows while the guest watches it — with the firewall up, nothing may arrive, and the
  guest fails its own check if anything does. `/etc/ufw/astraos-policy.conf` explains
  every rule where it lives; `docs/SECURITY.md` §3 and `docs/KNOWN_LIMITATIONS.md` §3.5
  record the scope (private ranges only) and how to widen it. **First CI run green
  (2026-10-16, run 38913161772, commit 0e47f4d):** `RESULT: PASS (51 checks, 0 failed)`
  — `firewall-active`, `firewall-default-deny`, `firewall-page-allowed`,
  `firewall-probe-listening` and `firewall-blocks-other-ports` all green — while the
  host's probe of port 18766 (the guest's watched 8766) timed out and no connection
  reached the guest (`phone-host.log`: `firewall probe -> 18766 TimeoutError('timed out')`).

- **The screenshot capture is made real (first run green, 2026-10-16).** The
  first green boot self-test's captured image was a flat black with only the cursor
  although the session was healthy — QEMU's stdvga emulation (fixed upstream in 9.0.2,
  not in the 8.2 the CI runner ships) clears the shared framebuffer when the guest
  blanks the screen, and unblanking then stays black. The guest now turns blanking off
  (`xset s off`, `s noblank`), forces the display on (`xset dpms force on`, `-dpms`)
  and repaints the whole screen (`xrefresh`) as its `screenshot-ready` check right
  before it reports its result; the host measures every capture's standard deviation,
  retries while the guest still holds the session, keeps the shot with the most
  content, and says so in the transcript when even that is flat. The image utilities
  the guest uses (`x11-xserver-utils`, `x11-utils`) already ship. That run is
  38913161772 (commit 0e47f4d, 2026-10-16): the capture (`screenshot.png`, 1280×800)
  carries the real desktop — sampled across 16,000 points it holds a standard
  deviation of 14.3 on a mean luminance of 2, a dark-themed desktop rather than a flat
  frame.

- **The ISO's own boot menus are exercised (first CI run green, 2026-10-16).** It
  is the menu, not the host, that boots the guest now: `scripts/boot-menu-test.sh`
  boots the built ISO with QEMU's own firmware starting the machine — no kernel, no
  initrd, no command line supplied — accepts the bootloader menu's default entry with
  Enter injected through the QEMU monitor, and passes only when the live system's login
  prompt appears on the serial console. Two media: `bios` (syslinux via the ISO's El
  Torito boot record, plain SeaBIOS) and `efi` (GRUB via OVMF attached as a matched
  pflash code + variable-store pair; the system firmware files are never written to —
  the variable store is always a private copy). The pass condition can only be met if
  the shipped menu entries carry the serial console, so `console=ttyS0,115200n8` is now
  part of `LIVE_APPEND` in `config/live-build/auto/config` — deliberate for real
  hardware as well: a machine with a serial port gets boot messages and a login prompt
  there. `astraos.ci=1` stays out of `LIVE_APPEND` (it would power real desktops off) and
  out of the menu script; the existing mirror test and the new
  `tests/static/test_boot_menu.py` hold both ends. The workflow gained a `boot-menus`
  job (both media per dispatch, the UEFI run still performed when the BIOS run failed,
  evidence uploaded as `astraos-boot-menus`). That run is
  38913161772 (commit 0e47f4d, 2026-10-16): the `boot-menus` job (6m41s) ran both
  firmwares — syslinux on BIOS, GRUB on UEFI, QEMU's own firmware with no kernel and
  no command line supplied — and both serial logs end at the live system's
  `astra-live login:` (`astraos-boot-menus` carries both).

- **The assistant's page can now be reached from a phone — by pairing.** The roadmap's
  Stage 1 phone-page item got its first slice: `astra-ai serve --lan` opens the page to
  the local network, but every request from anything that is not the computer itself is
  refused (HTTP 401) until the phone enters the six-digit code shown by `astra-ai pair`.
  A code lives ten minutes, pairs exactly one phone, counts its wrong tries (five, then
  a one-minute cooling-off), and the paired token can be revoked at any time with
  `astra-ai unpair`; the computer itself is never asked to pair. The page grew the
  pairing screen (a code input when the server says pairing is needed), tokens live in
  the phone's browser only, and nothing is written to disk — stopping the server
  revokes every phone. The boot self-test exercises the whole arc over QEMU's
  forwarded port — this computer serves without pairing, the phone is refused
  unpaired, pairs with the code, gets a served request, and is refused again after
  revocation — with the host side of that exercise recorded in `phone-host.log` beside
  `serial.log`. Honest first-slice scope: plain HTTP on the local network (no TLS yet),
  bearer tokens, and the firewall default stays undecided (see the roadmap's firewall
  item). Unit and static tests pin the gate, the code policy, the page and the evidence
  markers; run
  38913161772 (commit 0e47f4d, 2026-10-16) carried it green: all six phone checks
  passed, and `phone-host.log` holds the host's arc — the pairing code read from the
  serial console, the page GET answering 200, the unpaired health GET 401, the pair
  POST 200, the paired health GET 200, the revoked phone refused again, and the
  blocked-port probe timed out.

- **The first green boot self-test.** 2026-10-16, run 38881934636 (commit 8f81e3d): the
  built ISO booted under QEMU in pure CPU emulation — the runner's `/dev/kvm` is `root:kvm`
  and the runner user is not in the `kvm` group, so the exercise's own writability test
  fell back to TCG (corrected 2026-10-19; run 39222797247 was the first to boot with it) —
  and the
  image's own self-test reported `RESULT: PASS (39 checks, 0 failed)`. The guest reached
  the console login prompt 143.7 s in; the checks confirm LightDM active, an Xfce session
  (xfwm4) running as the live user, every `astraos-*` package at its expected version,
  the hardware, codec and compatibility tools, the Flathub remote, NetworkManager active
  with an IPv4 address, and a real name resolved by DNS — the check that pins the DNS
  defect entry below. Job times: build 18m43s, boot 6m28s; the guest ran 4 vCPU / 4 GiB.
  The evidence artifact is `astraos-boot-self-test` (`serial.log` is the record; the
  screenshot captured through the QEMU monitor came back black — a capture defect,
  fixed on 2026-10-16 and proven green in run 38913161772, the screenshot entry
  above). The test starts the kernel and initrd taken from the ISO with the ISO
  attached as the live medium; the ISO's own boot menus (syslinux BIOS, GRUB EFI) went
  green in CI on 2026-10-16 (the menus entry above, run 38913161772). The README's maturity table and "What has been tested",
  `docs/KNOWN_LIMITATIONS.md` §1.1/§2 and the roadmap's Stage 1 entry record it in the
  same commit.

- **The image can prove that it boots.** The ISO is no longer only built and inspected:
  `.github/workflows/build-iso.yml` gained a `smoke-boot` job (on by default) that boots
  the freshly built ISO in QEMU, waits for the image's own self-test, takes a screenshot
  of the booted desktop through the QEMU monitor and fails the workflow unless the image
  reported PASS. The QEMU command line is built from `config/distribution.env`, so the
  boot test cannot drift from the ISO's own boot entry, and it adds `console=ttyS0` plus
  `astraos.ci=1` (below). KVM is used when the runner provides it, emulation is the
  fallback; `scripts/smoke-boot.sh` is the driver and runs locally against any built ISO.
  The evidence — `serial.log`, `screenshot.png`, `qemu.out` — is uploaded as the
  `astraos-boot-self-test` artifact, and the build job's summary no longer claims booting
  is untested, because the workflow now boots it. (The README's "What has been tested"
  list records the proof: the first green run is the entry above.)

- **Every image carries a self-test it runs on request.** `astraos-smoke.service` (gated
  on `ConditionKernelCommandLine=astraos.ci=1`) runs `/usr/local/sbin/astraos-smoke` after
  the desktop is up: release identity, LightDM + Xfce session, every AstraOS package, the
  hardware and compatibility stack, the commands (HUD, assistant, all-in-one, Windows
  bridge, wine, ffmpeg, flatpak), the Flathub remote, and that a real name resolves. It
  prints one line per check to the serial console, holds the desktop for the screenshot
  and powers off; a normal boot never runs it. Any medium carrying this release can
  describe the machine it is on — what a hardware bug report needs.
  `/usr/share/astraos/SELF-TEST.txt` documents it, `docs/BUILDING.md` §8 covers the CI
  side, and `tests/static/test_smoke_boot.py` pins the output contract, the kernel
  condition, the explicit executable bit at staging time, and the rule that the QEMU boot
  mirrors `distribution.env` instead of retyping the live identity.

- **Hardware enablement beyond the kernel and firmware**
  (`config/package-lists/35-hardware.list.chroot`): VA-API video decode for Intel and AMD
  (plus `vainfo`), `fwupd` for device firmware updates, `zram-tools` (the biggest
  responsiveness win on the 4 GB machines this release targets), `irqbalance`,
  `bluez-firmware`, MTP/Android tools (`libmtp-runtime`, `mtp-tools`, `adb`, `fastboot`,
  the platform-tools udev rules), filesystem tools (`ntfs-3g`, `exfatprogs`,
  `squashfs-tools`) and two printer driver families (gutenprint, escpr).

- **Compatibility with the files and programs people already have**
  (`config/package-lists/45-compatibility.list.chroot`): the full codec set
  (`libavcodec-extra`, `ffmpeg`, GStreamer libav/bad/ugly, DVD navigation), Flatpak with
  the desktop portals and keyring integration, Wine (64-bit out of the box) with
  winetricks, `gdebi`, `timeshift`, `inxi`, `speech-dispatcher`.
  `0900-compat.hook.chroot` points the system-wide Flatpak remote at Flathub: a pointer
  only — no application is installed at build time and nothing is downloaded at boot —
  recorded in `/usr/share/astraos/COMPAT-REPORT.txt`, with the boot self-test checking
  the remote exists. Every name in both lists was verified against the Debian trixie
  archive; `libdvdread8` is virtual there (the time_t transition renamed it), so
  `libdvdnav4` pulls the read library at the soname the release actually ships.

### Fixed

- **The install exercise's phase-2 check grepped a file it had no permission to open, and
  reported a correct patch as missing.** Run 39238238246 completed an installation for the
  first time — the wizard walked every page, `unpackfs` filled the filesystems, the `mount`
  module mounted `/dev`, `/proc`, `/sys` and `/run` into the target because it finally had
  an `extraMounts` list to do it from, `grub-install` found a device for `/boot/grub`, and
  the installed disk carried a `grub.cfg` — and then failed at:

  ```
  grep: /tmp/astraos-install.FyODVS/grub-patched.cfg: Permission denied
  install-boot: patching grub.cfg appended nothing; the installed boot would run no self-test
  ```

  The patch was on the disk. The *reading* of it was not: `cp` through sudo keeps the
  installed `grub.cfg`'s mode, the runner is not root, and the check grepped a file it
  could not open. Both copies are now `chmod 0644` where they are made — they are evidence
  and hold no secret — which also fixes the artifact step that had been copying them as the
  unprivileged runner and failing silently (`|| true`) on both.

- **Every installation this project ever attempted died one job short of finishing, and the
  cause was a configuration file that did not exist rather than one that was wrong.** Run
  39233194012 was the first run to install anything at all — the wizard walked every page,
  `unpackfs` filled the filesystems, twenty-five jobs wrote to the disk — and then job 26 of
  27 stopped:

  ```
  Starting job "bootloader" ( 26 / 27 )
  [PYTHON JOB]: "Bootloader: grub (bios)"
      .. Running QList("grub-install", "--target=i386-pc", "--recheck", "--force", "/dev/vda")
  grub-install: error: cannot find a device for /boot/grub (is /dev mounted?)
  ERROR: Installation failed: "Bootloader installation error"
  ```

  GRUB was not the problem, and neither was the bootloader config in the entry below.
  Calamares named the cause two steps earlier, in the same log:

  ```
  WARNING: No config file for "mount" found anywhere at
  "/src/modules/mount/mount.conf"
  "/etc/calamares/modules/mount.conf"
  "/usr/share/calamares/modules/mount.conf"
  ```

  Nothing in the image supplied any of the three. The `mount` module ran with an **empty**
  configuration, and its `extraMounts` list is the only thing that mounts `/dev`, `/proc`,
  `/sys` and `/run` inside the target before the destructive phase runs. Without them the
  target is not a chroot, and `grub-install` cannot find a device for `/boot/grub` in a tree
  with no `/dev`.

  Why no packaged fallback existed is the choice recorded in
  `config/package-lists/60-installer.list.chroot`: this image installs upstream's `calamares`
  and deliberately **not** `calamares-settings-debian`, which is where Debian's own
  `/etc/calamares` tree comes from. That choice is right — AstraOS *is* the Calamares
  configuration for this image — but its consequence had not been understood, and it is the
  same defect as the missing `grubInstall` one layer up: **a module config this repository
  does not ship is not Debian's default, it is nothing.** `installer/calamares/modules/mount.conf`
  now ships, as Calamares 3.3.14's own file unmodified, along with `fstab.conf` — whose absent
  default was a plain `luks` crypttab entry, where Calamares' own file names
  `luks,keyscript=/bin/cat` as the value Debian and Debian-based distributions need.

  The build hook gained the assertion whose absence let this through. It had validated
  `partition.conf`'s disk-safety policy, `users.conf`'s password policy and the branding, and
  said nothing about the module that makes the target a chroot at all — so an image in which
  that module had *no configuration* was built, booted, and handed to the exercise that died
  on it. Two comments that described a packaged fallback as though one existed, in that hook
  and in `bootloader.conf`, now say what the run measured: on this image, that path is empty.

- **The install exercise deliberately does not seed those two files, although the seed was
  the obvious place for them and it would have been a one-line change.** The guest that
  applies the seed lives *inside* the ISO, so a config seeded to a medium that lacks it can
  never be applied by that medium: a mechanism that cannot do anything, which is this
  project's recurring defect and the exact one described in the entry below. It would also
  fail in the wrong direction — seeding an image's own config over the top makes *"this medium
  cannot install anything"* indistinguishable from a passing run, and that indistinguishability
  is how the original defect survived two exercises. The guest instead records which of the
  four configs the medium already carried, hashes and all, in `modules-in-image.txt`; the host
  fails the run with *"this is a medium older than the fix, not a failed installation"* if one
  was absent, and the file goes into the evidence. `configs.sha256` now covers the four module
  configs as well, so what Calamares was actually given is recorded rather than inferred.

- **The installer already installed a bootloader config that Calamares cannot read, so every
  installation of every AstraOS image has died at job 26 of 27.** Run 39230792183 got further
  than any run before it — the wizard walked every page, `unpackfs` filled the filesystems —
  and then stopped:

  ```
  ERROR: Error while running: KeyError: 'grubInstall'
    /usr/lib/x86_64-linux-gnu/calamares/modules/bootloader/main.py(654): run_grub_install
    main.py(717): install_grub <- main.py(897): prepare_bootloader <- main.py(927): run
  ERROR: Installation failed: "Bad main script file"
  ```

  Calamares reads **one** config per module — the copy at `/etc/calamares/modules/` — and
  falls back to the packaged copy under `/usr/share/calamares/modules/` only when there is
  no file there at all. `installer/calamares/modules/bootloader.conf` is installed to that
  first path, so it *replaces* Calamares' own rather than extending it: every key the module
  reads without a default must be stated in it, and a key that is absent is not a default but
  the `KeyError` above. `grubInstall` was the one that fired; `grubMkconfig`, `grubCfg`,
  `grubProbe` and `efiBootMgr` are the next four hard lookups on the same code path
  (main.py lines 779, 719, 748, 459) and would have fired in turn, one per attempt. All five
  are now stated, copied verbatim from Calamares 3.3.14's own `bootloader.conf` — the
  configuration upstream tests.

  Two comments in that file were lying as well. "`efiauto` detects UEFI versus legacy BIOS"
  described a value that is not in the file (it reads `grub`) and is not one this module
  accepts — on a UEFI machine `efiauto` falls past every branch to a *debug* line and
  installs no bootloader at all, so the stale comment was a loaded gun aimed at whoever
  "restored" it. And two keys that nothing in the module reads have been removed:
  `kernel: "/vmlinuz-linux"` named Arch's kernel path in a module that has no `kernel` key,
  and `timeout: 10` described a GRUB menu timeout that lives in `/etc/default/grub` on the
  installed system. **A key that is dead is worse than a key that is absent, because it reads
  like a decision** — and `vmlinuz-linux` is the same shape of Arch copy-paste as the
  `initialPartitioningChoice: eraseDisk` in the entry above, from the same class of mistake.

  The gap that let it through was in the build hook, which validates `partition.conf`'s
  disk-safety policy, `users.conf`'s password policy and the branding, and said **nothing at
  all** about `bootloader.conf`: an image whose copy had lost a key its module requires was
  built, and booted, and shipped to the exercise that then died on it. The hook now refuses
  such an image, and `tests/static/test_install_boot.py` pins both halves — the six keys in
  the shipped file, and the hook's check for them.

- **The install exercise's pass condition read a file that was never written, so it could not
  have passed however well the installation went.** The verdict greps the *structured session
  log* for `unpackfs` and `bootloader`. Calamares writes that file to
  `$HOME/.cache/calamares/session.log`, and the live system's installer unit runs without a
  login shell: `HOME` was empty, so the file landed at `//.cache/calamares/session.log` — its
  own log line says that path verbatim — which is neither of the two places the guest's
  collector looked. Run 39230792183 reported `unpackfs bootloader` missing from a file that
  did not exist, while both names were sitting in the console transcript beside it. The unit
  now exports `HOME=/root`, the collector also accepts the empty-`HOME` path, and the host
  says a missing log is a missing log instead of naming modules that never ran.

  The comment beside that check claimed `rc=0` could only follow a success, "because a failed
  job stops the queue on its error page, nobody clicks anything in CI, and this script's
  deadline catches it". The evidence says otherwise: after the bootloader failure Calamares
  put up its error page and **exited 0 by itself within seconds**. The log is therefore the
  only evidence that the queue reached its end — which is exactly why the log being findable
  matters, and why that fallback was added rather than the check being weakened.

- **A test exercised `size` and a local variable overwrote it, killing the driver one minute
  into a healthy install.** `drive-ui.py` keeps the screen dimensions in a module-level `size`
  that `shot()` fills in and `to_abs()` reads; the new exec loop assigned
  `size = os.path.getsize(...)`, so the very next screendump died with
  `TypeError: 'int' object does not support item assignment`. The host then reported "the
  wizard driver stopped before the installer reported", which is what it is for — and which
  is how a driver crash and an install failure were told apart in the first place. Renamed.

- **The install exercise was emulating on a machine that has hardware virtualisation, and
  the reason was invisible in every log.** A throwaway probe run on `ubuntu-24.04` reported
  the whole cause in one line:

  ```
  crw-rw---- 1 root kvm 10, 232 /dev/kvm
  uid=1001(runner) groups=runner,adm,users,docker,systemd-journal
  NOT-WRITABLE
  ```

  The device is there, the CPU advertises `svm`, `kvm_amd` is loaded — and the runner user
  is not in the `kvm` group, so `scripts/install-boot-test.sh`'s `[ -w /dev/kvm ]` said no
  and QEMU fell back to TCG emulation. That fallback is the whole reason this exercise has
  always been budgeted in tens of minutes: run 39105685521 spent 48 minutes installing, and
  run 39222797247 — the first to use the device — spent 35. Nothing else in either run said
  so; the script's own message ("no usable KVM; booting under QEMU emulation (slower)") was
  accurate and was read past for as long as it has existed. `smoke-boot.sh` carries the same
  writability test, so the boot self-test has been emulating too.

  The three workflows that install QEMU (`smoke-boot`, `boot-menus`, `install-boot`, plus
  the stored-ISO `install-test`) now grant the device before running it, and the script
  distinguishes three states instead of two — readable and writable, present but not
  usable, absent — naming the user, printing the device's real ownership, and printing the
  cure (`sudo chmod 666 /dev/kvm`) when it exists but cannot be opened. The README,
  `docs/ROADMAP.md`, `docs/KNOWN_LIMITATIONS.md` and the 2026-10-16 boot-self-test entry
  below all claimed "the runner provides no KVM"; that came from this fallback message
  rather than from a measurement, and they are corrected.

- **The installer's partitioning choice was spelled as a value Calamares does not have, so
  the partitions page arrived with nothing selected and its disabled Next button absorbed
  forty-four minutes of clicks.** Run 39222797247 (2026-10-19) is the first exercise whose
  evidence could be read past the first page — thanks to the KVM entry above — and what it
  shows is that the walk never left the partitions page: `ui/04-partition.png` through
  `ui/18-exec.png` are that same page, `ui/19-exec.png` onward are 282-byte black frames,
  and `ui/09-install.png`, named for the page the walk believed it had reached, is the
  partitions page with both radio buttons empty. Calamares' own log agrees, and says why:

  ```
  InstallChoice Config::NoChoice "none"
  bool ChoicePage::calculateNextEnabled() const
  No partitioning choice has been made yet
  ```

  `Config.cpp`'s `installChoiceNames()` holds exactly `none, nochoice, alongside, erase,
  replace, manual`, and `installChoiceNames().find()` returns the **first** entry of that
  table — `none`, meaning no choice — for a name it does not know, silently for this key
  (the swap key three lines below it warns). The CI seed asked for `eraseDisk`, so the
  choice was never made, and every click after it was a no-op QEMU accepted without
  complaint.

  Four things carried that spelling: the seed in `scripts/install-boot-test.sh`, the
  disk-safety assertion in `0300-installer.hook.chroot`, and the two static pins holding
  that assertion (`tests/static/test_hook_assertions.py`, `tests/static/test_repository.py`).
  The hook was the worst of them — it refused the build when `partition.conf` *contained*
  `eraseDisk` and would have passed the value that actually authorises erasure (`erase`),
  so the disk-safety net guarded nothing; it now requires the shipped value to **be**
  `none`.

  The driver takes no config file's word for anything either. Every step of the walk is
  judged by the client area's bytes before and after that step, so a step that does not move
  ends the walk naming the page it could not leave, in `ui.log` where the host already reads
  it — the old check compared the welcome page against the *end* of the walk and nothing
  else, which is precisely the comparison that cannot see a walk stuck in the middle. The
  partitions page's *Erase disk* row is clicked on the page itself, which does not depend on
  the seed being right, because a radio button that is already selected stays selected when
  it is clicked again. Both halves of this fix live outside the ISO, so the stored-ISO
  exercise can prove them without a rebuild.

- **The exec loop's wake-up input did not wake anything, and the first window was waited
  for by sleeping.** Both were measured rather than guessed. The live session blanks its
  screen after ten minutes of quiet and a pointer *move* does not reset that timer: runs
  39105685521 and 39222797247 each went uniformly black at `19-exec` and stayed black for
  every frame after it, with a move sent immediately before every single dump. The loop now
  sends a bare `Shift` — `send-key` presses and releases its list together, so one qcode is
  a complete keystroke that types nothing and leaves no modifier held — and waits for the
  guest to repaint before taking the dump. It also says plainly when a frame is too small to
  be a page at all, rather than leaving that to be read later as a hung install, and gives
  up after fifteen minutes of a byte-identical progress page instead of running the clock
  out. Separately, the driver waited a fixed 60 seconds for Qt's first window — the
  emulated answer, and run 39103628321 shot a bare desktop at exactly that mark — and now
  polls for the client area to appear where a 1024x520 window's belongs, which under the
  runner's KVM is a second or two.

- **The pointer was aimed on a scale that is not pixels, and the button was pressed by a
  different device than the one that moved — so the wizard advanced nowhere and the
  exercise's own stall detector was fooled into silence.** Run 39105685521 (2026-10-18)
  burned its whole 48-minute budget, and every screendump from `02-locale` to `18-exec` is
  the **Welcome** page again. `ui.log`'s `query-mice` output is the confession:
  `QEMU PS/2 Mouse current=True absolute=False` next to `QEMU HID Tablet current=False
  absolute=True` — the pointer that would *press* was not the pointer that would *aim*.

  Three defects, each one read out of QEMU's source rather than guessed at:

  - **An `input-send-event` `abs` value is not a pixel.** QEMU's `INPUT_EVENT_ABS_MIN`
    and `INPUT_EVENT_ABS_MAX` are `0x0000` and `0x7FFF`; `qmp_input_send_event` passes the
    value through unscaled, and `hw/input/hid.c`'s `hid_pointer_event` assigns it directly
    (`e->xdx = evt->abs.value`) to the tablet's axes. The driver's (1002, 670) therefore
    landed near (39, 16) of 32767 — not on the Next button, not even on the same wall of
    the screen. Pixels are now scaled to `0x7FFF` before they go on the wire.
  - **QEMU gave every button press to the mouse, not the tablet.** `qemu_input_find_handler`
    returns the *first* handler whose mask intersects the event, and it is evaluated per
    event. The i8042 PS/2 mouse registers first with mask `BTN|REL`, so it took every
    `btn`; only `hid_tablet_handler` takes `abs`, with mask `BTN|ABS`. An `abs` move aimed
    with the tablet while the press went to the mouse. The driver now makes the tablet the
    current input handler with HMP's `mouse_set` — `qemu_mouse_set` →
    `qemu_input_handler_activate`, which moves the handler to the head of the list — sent
    over `human-monitor-command`, and reads the routing back with `query-mice` before the
    first click.
  - **The stall detector hashed the wrong frame.** `client_digest` began at x=0 rather
    than the client area's `left`, so its verdict turned on the desktop's left column
    instead of the wizard — which is how a walk that never advanced still reported a
    changed page. The digest now starts where the client area does.

  The exec loop also nudges the pointer (no button) before each screendump: from
  `19-exec` onward this run's dumps were uniform 282-byte PNGs because X had blanked the
  screen, which removes the evidence exactly when the interesting part is happening.
  Pinned by two more tests in `tests/static/test_install_boot.py`.

- **The install exercise's clicks went to the wrong pointer, in the wrong units, so the
  wizard sat untouched for 45 minutes and the verdict could only say "no report
  arrived".** Run 39049818027 (2026-10-17) clicked Next eleven times — through locale,
  keyboard, the partition page, both password fields, summary and Install — and every
  screendump from `02-locale` onward is the same **Welcome** page with a different clock
  in the panel. The coordinates were never the problem: they are right (the Next button
  is at (1002, 670) and the client area was correctly located at top 170, bottom 690,
  right 1153). The *delivery* was. `hmp_mouse_move` queues `qemu_input_queue_rel` — it is
  a **relative** move — and it is delivered to whichever pointer device registered first,
  the i8042 PS/2 mouse that every PC machine has. The live session's X server follows the
  absolute `usb-tablet` instead. So "click at (1002, 670)" went out as *move 1002 pixels
  right and 670 down*, the pointer slammed into a screen corner, and nothing after that
  could matter. Two independent mistakes hid each other: the monitor could not express an
  absolute position, and the device it addressed was not the one being read.

  The driver now speaks **QMP** (`-qmp` instead of `-monitor`), and drives the pointer
  with `input-send-event` `abs` axes addressed to the named tablet
  (`-device usb-tablet,id=astraos-tablet`, and `"device": TABLET` on every event) — the
  two axes then mean on the wire exactly what they mean in the code. Screendumps and key
  typing move to QMP as well (`screendump`, `send-key`). Because the protocol is now
  request/response, **every command's reply is checked**: a refused command is now named
  in `ui.log`, where the HMP driver could not tell a delivered click from a dropped one.
  And the walk finally **measures its own effect**: it hashes the client area of its first
  and last screendumps, and if the wizard has not moved by the end of it, the driver
  stops and the host reports an unresponsive pointer in about two minutes — with the
  host's wait loop now noticing a driver that gives up instead of running out the clock.
  The region hashed is the client area, not the screen, because the panel clock inside a
  whole-screen comparison changes every minute and would hide exactly the stall this is
  meant to catch. Pinned by two new tests in `tests/static/test_install_boot.py`.

- **Naming the tablet on each pointer event aborts QEMU, so the events carry no device
  (source; first CI run 39103628321 failed with the reason).** The change above was
  tested on 2026-10-18 and run 39103628321 reached the first click and died there, with
  `qemu1.out` holding nothing but `Unexpected error in object_property_find_err() ...:
  Property 'qemu-fixed-text-console.device' not found`, and `ui.log` ending at "the
  monitor closed while waiting for input-send-event". Naming a device on an input event
  walks the consoles, and the fixed text console `-vga std` creates has no `device`
  property to find. The events therefore omit the device, which is not a retreat:
  QEMU admits only devices with no input routing when one is omitted, and the tablet is
  this machine's only absolute pointer, so an `abs` event has exactly one possible
  home. Which device that is, and whether it is the current one, is no longer inferred
  from QEMU's internals — `query-mice` writes every pointer QEMU knows about to
  `ui.log` before the first click, so the routing is a recorded fact.

  That same run also showed the welcome screendump being taken before Qt had drawn
  anything (a 6 KB dump, no light region), which sent the client-area detection down
  its fallback with nothing in the evidence to check against. The detection now looks
  again once before believing that, and the digest that judges the walk is taken from
  whichever welcome dump the geometry actually came from. Worth noting what the run did
  prove: the fail-fast works. The same class of failure that cost run 39049818027
  forty-five minutes was caught in **5m32s**, with a named cause.

- **The install exercise's wizard walk never pressed anything: Return does nothing in
  Calamares, and its clicks aimed at a window that never existed.** Run 39024106426
  drove the whole walk — every page, the users-page typing and all — and its
  screendumps show the wizard still on its first page at the deadline. Three
  measurements on that evidence and a local Calamares 3.3.14 on the same Qt (under
  Xvfb, with the live font environment reproduced from `desktop/skel`) explain it:
  Calamares 3.3's `ViewManager` never sets a default button, so every `sendkey ret`
  was a no-op; the branding's `windowSize: 800px,520px` is clamped up to Calamares'
  own 1024x520 minimum, so the old screen-centre arithmetic missed the real buttons
  (the window was never 800x520 — and `CalamaresWindow::ensureSize` only ever grows
  height, never width); and the users page's two password fields sit side by side in
  one HBox (upstream's `page_usersetup.ui`), not stacked at +45px as the old driver
  typed into. The driver now clicks the Next button and locates the window's client
  area in its own first screendump before aiming — every target is an offset from
  that area's real edges, so wherever the window manager places the window the same
  clicks land — and the walk was reproduced end to end against a local Calamares:
  welcome → locale → keyboard → users (both fields typed, the module's "Password is
  too short" error clearing to its green check, Next enabling) → summary. The pins in
  `tests/static/test_install_boot.py` no longer let the driver press Return, and
  require the client-area detection and the measured click constants.

- **The Secure Boot exercise never ran the firmware (the machine it tried has no SMM,
  and OVMF's secboot build requires it).** `scripts/boot-menu-test.sh --medium secure`
  picked OVMF's secboot code and the Microsoft-key variable store — the right pair —
  then let QEMU choose its default machine, pc-i440fx. OVMF's secboot build is compiled
  with `SMM_REQUIRE` (Debian's own README.Debian says it "requires SMM support in
  QEMU"), and without SMM the firmware stops before it draws or prints anything. Both
  attempts (runs 38924527286 and 39024106426) timed out with a zero-byte serial log and
  a guest screen that QEMU still reported as "not initialized" — a signature that reads
  like a slow boot and is the firmware never running. The secure branch now carries the
  documented invocation — `-machine q35,smm=on`, `-global
  driver=cfi.pflash01,property=secure,value=on` (the global libvirt adds for the same
  firmware; Secure Boot's variable locking stands on it), `-global
  ICH9-LPC.disable_s3=1` — and `tests/static/test_boot_menu.py` pins all three, so the
  exercise cannot silently go back to running a firmware that cannot start. The first
  run with the fix is green (2026-10-17, run 39028358504): all three boot paths
  reached the login prompt, the secure one under enforcing firmware with the Microsoft
  keys, so the signed chain is proven rather than "carried, not proven".

- **The installer's first real start found the key it was missing (branding
  `slideshow`).** The retry that got past QEMU startup (run 38924527286) reached a
  running Calamares — and Calamares exited immediately: 3.3's branding constructor
  parses `slideshow` unconditionally, even with no `show` module in the sequence, and
  a missing key is a FATAL before the first page is drawn (`calamares-console.log`:
  `key not found: slideshow`). Earlier builds had shipped the same descriptor and
  nothing had ever started the installer, so nothing had ever read it. The descriptor
  now carries `slideshow` naming the images the package installs beside it (this is a
  QML-enabled Calamares, where a scalar value would have to name an existing `.qml`
  file); `0300-installer`'s hook refuses a descriptor without the component name,
  without the slideshow key, or naming a slideshow file that will not exist at run
  time; and two new pins keep the hook and the descriptor in agreement
  (`tests/static/test_installer_branding.py`, `tests/static/test_hook_assertions.py`).
  The attempt after that (run 39024106426) started Calamares cleanly — the branding
  fatal is gone — and failed later, in the walk driver; see the wizard-walk entry
  under Fixed.

- **The install driver's tablet gets a USB controller (its absence killed the
  exercise's first run at QEMU startup).** `scripts/install-boot-test.sh` clicks with
  absolute coordinates, which is what `-device usb-tablet` provides — but a tablet
  needs a USB bus, and the phase-1 command line had none: `qemu-system-x86_64` exited
  immediately with `No 'usb-bus' bus found for device 'usb-tablet'` (run 38919644411,
  kept in the `astraos-install-test` artifact's `qemu1.out`), the serial console
  stayed empty, and the job failed 1m37s in without the guest ever booting. The
  command now defines `qemu-xhci` before the tablet, and
  `tests/static/test_install_boot.py` pins both the presence and the order. The retry
  got past QEMU startup (run 38924527286) and failed on the branding fatal below.

- **The firewall's port check reads the `ufw status` listing ufw actually prints (its
  first run proved the firewall and failed on its own spelling).** Run 38903678646
  ended the boot self-test at `51 checks, 1 failed`: `firewall-page-allowed` demanded
  `8765/tcp … ALLOW IN …` from plain `ufw status`, but the shipped ufw (0.36.2,
  `backend_iptables.py`) blanks the direction column outside verbose mode — a check
  that could never pass, while the behaviour it stands for was proven in the same run:
  the host's probe of an unallowed port died at the firewall, the guest recorded no
  arrival, and the assistant's page answered a private-range connection. The check now
  reads `ufw status verbose` (one call, shared with the default-policy check) and
  prints the rows it saw when it fails. Run 38913161772 (commit 0e47f4d) proves it:
  `RESULT: PASS (51 checks, 0 failed)` with `firewall-page-allowed` green.

- **The installer's configuration is made true (source; its first end-to-end run is
  pending).** Every key in `installer/calamares/settings.conf` and `users.conf` was
  checked against the exact Calamares Debian 13 ships (the 3.3.14 sources), and three
  kinds of false statement came out. The sequence listed `finished` inside the exec
  phase — a done page no user would ever see, because Calamares' own ViewManager calls
  "no finished step after an exec" a weird state; the done page is now its own `show:`
  phase, as upstream's configuration has it, and `quit-at-end: false` (now stated
  explicitly) keeps it on screen until the user asks for the reboot. Two settings keys
  no Calamares in the pinned suite reads (`requirePassword`, `showPicker`) were
  removed. And `users.conf` claimed a user policy it did not have: the key that was
  supposed to keep root disabled was read by nothing (the module's default is
  `setRootPassword: true`, so the installer had been offering to set a root password,
  against plan §13.1), the shell sat under a dead top-level key instead of the `user:`
  submap, and with no `passwordRequirements` configured the module's own
  `passwordStatus()` reports the empty string as valid: an installation with no
  password was possible. `setRootPassword: false`, `user:`/`shell:` and
  `passwordRequirements: minLength: 1` replace them, the dead `username:` block is
  gone, and the build hook now refuses an image whose users.conf would offer a root
  password or accept an empty one. The first run that carried the slice
   (38909791960) died at the end of the chroot stage on the hook's own new assertion: it
   used `grep -A4E`, which GNU grep reads as `-A 4E` — "invalid context length argument"
   — so the pattern never ran and an image whose packages and other assertions were all
   in place was refused. The assertion is two plain greps now, verified against the
   shipped file before it was committed, and `tests/static/test_hook_assertions.py`
   both pins the patterns and refuses that flag shape; the installer's first end-to-end
   run is still pending, while run 38913161772 (commit 0e47f4d) built the image green
   with the fixed assertion in the chroot stage.

- **`astra doctor` no longer reads "Status: inactive" as active.** Its pattern was the
  unanchored `*"active"*`, which also matches "inactive" — the same defect the security
  tests pin in `astraos-info`. The firewall being on by default makes the misreport rarer
  but not less false; both tools now anchor on `"Status: active"*`, and the test suite
  pins both.

- **The phone exercise's host driver (first green run, 2026-10-16).** The
  first run that carried it (run 38894494223) booted, reached the desktop, and the guest
  passed `phone-armed` and `phone-localhost` — then the host half died silently at its
  first request: it loaded the pairing page through the QEMU port forward and parsed the
  HTML body as JSON, so the uncaught `JSONDecodeError` ended the driver before its first
  transcript line, and the four pairing checks that depend on the host failed. The driver
  now tolerates a non-JSON body (only the page is one), logs any unexpected failure
  instead of dying invisibly, and its stderr is kept with the evidence; the pairing arc
  itself was never in question and needed a clean re-run to prove — 38913161772
  (commit 0e47f4d) is that run: all six phone checks green with the full host
  transcript.

- **The boot self-test's kernel command line carried `findiso=/live/filesystem.squashfs`,
  and the first CI boot of a built image died because of it** (run 38864588609,
  2026-10-16). `findiso` is live-boot's parameter for an ISO *file* sitting on a
  filesystem: the guest loop-mounts exactly the named file and reads it as ISO9660.
  Pointed at the squashfs inside the medium, the guest loop-mounted the squashfs, isofs
  rejected it (`ISOFS: Unable to identify CD-ROM format`) and live-boot reported "Unable
  to find a medium containing a live file system" before the self-test could run. The
  parameter is removed; the ISO is attached as a CD-ROM and found by live-boot's own
  device scan, which is also how the ISO's own boot entry finds it - the by-hand
  VirtualBox boot of the previous image had already proven that path. The driver now also
  stops waiting as soon as the serial console shows `BOOT FAILED!` or a kernel panic
  instead of burning its whole timeout, its window carries margin over the measured
  emulated boot (the first green run clocks it — entry above), and
  `tests/static/test_smoke_boot.py` fails if `findiso` is ever added back or if the
  driver stops mirroring `LIVE_APPEND`.

- **The second CI boot reached the login prompt and never ran its self-test** (run
  38871459329, 2026-10-16). The findiso fix worked - the serial console shows the live
  system booting to `astra-live login:` - but systemd deleted the self-test unit's start
  job on the way: `Job astraos-smoke.service/start deleted to break ordering cycle`,
  `[ SKIP ] Ordering cycle found, skipping astraos-smoke.service`. The unit was
  `WantedBy=multi-user.target` while ordered `After=graphical.target`; a unit is started
  as part of the transaction of the target that wants it (which orders it before that
  target), and graphical.target is itself ordered after multi-user.target - a circle,
  and systemd breaks circles by silently deleting jobs. `[Install]` now says
  `WantedBy=graphical.target`, the target the unit already orders after; the unit's
  header comment and `tests/static/test_smoke_boot.py` record the cycle so it cannot
  return silently. The same run was the first TCG boot attempted in CI, and it never
  reported a result: the unit had been skipped by the cycle, and the serial log simply
  ends at the login prompt. That run did not establish the emulated boot's duration;
  the next run did — login prompt at 143.7 s. The workflow's self-test window is now
  120 minutes (job ceiling 150), the guest gets 4 cores and 4 GiB, the guest script
  waits for the session itself, and the unit's start timeout covers that wait. The
  README's tested-claims list was held until a run reported PASS — the next one did
  (entry above), and the README and limitations documents now record it.

- **The live session had no working DNS: `/etc/resolv.conf` was a 0-byte file.** Pinging
  an IP worked; pinging a name did not. Two authorities were both enabled —
  `NetworkManager.service` and `resolvconf.service` — and each deferred to the other:
  NetworkManager saw `resolvconf` installed and handed name resolution over to it, and
  `resolvconf` found the `/run/resolvconf/resolv.conf` symlink it manages replaced by an
  empty regular file (live-build replaces the path), so it wrote nothing. Nothing owned
  the file. The fix is that the image no longer installs `resolvconf` at all:
  NetworkManager writes `/etc/resolv.conf` itself, which is the Debian 13 way and the
  reason `resolvconf` is deprecated. This class of defect does not stop a build — apt
  resolves the set happily and the image ships broken — so
  `tests/static/test_packages.py::test_resolvconf_is_not_installed_alongside_networkmanager`
  fails if it is ever added back, the boot self-test resolves a real name as one of its
  checks, and the assistant's `set-dns` knowledge file teaches the diagnosis.

- The validator then failed that image on eight "live filesystem does NOT contain" checks at
  once, while a ninth passed. Nothing was missing: the squashfs held 152,556 inodes including
  every path the checks looked for, and the image verification hook had already confirmed the
  same paths inside the chroot it was built from. The defect was the shape of the check.
  `validate-iso.sh` sets `set -o pipefail` and piped the ~6 MB `unsquashfs -l` listing into
  `grep -q`, which exits the moment it matches: `printf` on the other side of the pipe died of
  SIGPIPE, and pipefail reported the *successful* match as a failed pipeline — exit status
  141. Every component whose match sat before the end of the listing was reported missing, and
  only the one pattern that happened to land near the end survived, which is why one check
  passing looked like evidence that the other eight were right. Listings are now written to
  files and read from them; `grep -q` reading a file cannot race. The boot-path listing, the
  `.disk/info` discovery and the squashfs listing all follow that rule, the listings share one
  work directory removed by an exit trap, and a listing with no `squashfs-root/` paths is
  reported once, as what it is, instead of nine times as a missing image. In the repository:
  `tests/static/test_scripts.py` rejects a pipeline into `grep -q` in any script that enables
  pipefail (the three other places with that shape — `bootstrap-build-environment.sh`,
  `validate-environment.sh` and `astraos-welcome` — were fixed the same way), and
  `tests/integration/test_iso_validator.py` runs the real validator against a stubbed
  `xorriso`/`unsquashfs`: it checks that every component is found in a listing whose matches
  come first, that a component which really is absent is still reported, and that one missing
  component does not become eight.

- The image's own `.disk/info` announced it as `Debian GNU/Linux 0.1.0 "Trixie" - Snapshot
  amd64 LIVE Binary 20261013-18:47`, and the validator refused it as a possibly unmodified
  Debian image — correctly, because the medium was naming Debian. The title is a literal in
  live-build's `binary_disk` (the `debian` case and the fallback case both set
  `TITLE="Debian GNU/Linux"`), no `lb` option changes it, and the only value that script
  takes from the image is `VERSION_ID` — this project's version number appearing inside a
  Debian sentence. `0800-disk-info.hook.binary` now writes the medium description in the
  binary stage, after `binary_disk` and before `binary_checksums` and `binary_iso`, taking the
  identity from the staged `distribution.env` so it cannot drift from the release, and it
  fails the build if a medium would still start with `Debian`. The hook's real output is put
  through the validator's real check by `tests/integration/test_iso_validator.py`.

- The validator's "the astraos-base package" check looked for `/var/lib/dpkg/status`, which
  exists on every Debian system: it passed on an image with no AstraOS package in it at all,
  so it was the one check that looked healthy while proving nothing. It now looks for
  `/var/lib/dpkg/info/astraos-base`, which dpkg writes only for a package it has installed.

- The 2026-10-13 CI build assembled a complete 2.0 GB live image — boot path, kernel,
  initramfs and live filesystem all present, live-build itself reporting
  "Build completed successfully" — and then the repository's own validator failed it on
  nine "live filesystem does NOT contain" checks at once. The validator, not the image,
  was wrong: it extracted the squashfs onto a path `mktemp --suffix=` had already created,
  xorriso wrote nothing onto the existing file and still exited 0, and the empty result
  was then listed by `unsquashfs`, which failed, whose error was discarded. Nine components
  were reported missing from a filesystem that was never read. The extraction now targets
  a directory that does not pre-exist, keeps each tool's stderr, verifies the size it got,
  and reports the tool's own diagnostic when something fails — and the `.disk/info`
  check beside it, which had the same shape (extract to `/dev/stdout`, discard the
  diagnostic, report "unavailable"), extracts to a real file the same way. Every
  extraction in the validator now produces either the data or the reason it could not.

- The same CI build spent ~24 of its 31 minutes, and 1.9 GB of its log, inside apt's http
  method: one queued item (`gstreamer1.0-gl` from the security mirror) printed
  `W: Tried to start delayed item ..., but failed` 12.7 million times in a hot loop while
  every other item on both mirrors fetched normally — a stuck pipelined connection, with
  the method retrying the start attempt without backoff. The build's `--apt-options` now
  carry transport-only Acquire settings (`http`/`https` `Pipeline-Depth=0`,
  `ForceIPv4=true`, `Retries=3`), which remove the pipelined queue that can strand an
  item, the instant-failing IPv6 connect path that can poison one, and turn transient
  fetch failures into a bounded retry. These change how a download is fetched, never what
  is fetched or whether signatures are verified.

- The image verification hook reported "an initramfs is in /boot" as FAIL for an image that
  had one, one assertion before the ISO would have been packed. The check asked
  `ls /boot/initrd.img-* /boot/initrd-*`: with nullglob off — it is off in dash, which is
  /bin/sh in this image — the pattern that matches nothing is passed on as its own literal
  text, `ls` reports "cannot access '/boot/initrd-*'" and the whole assertion fails. The same
  hook then opened that initramfs and found the AstraOS theme inside it. The check now loops
  over both names and tests each one, and `tests/static/test_scripts.py` rejects a command
  that is handed more than one glob — verified against the line that failed, and against the
  loop that replaced it.

- The chroot's apt configuration listed the pinned release suite in
  `config/archives/astraos.list.chroot` while live-build also wrote it from the mirror
  options, so every apt run reported each target as "configured multiple times" — inside the
  build and on any live system, where a user would see the warning without being able to act
  on it. The file now pins only the update and security suites, which live-build cannot add
  for this base release (it writes the pre-2017 "<suite>/updates" spelling, which Debian 13
  does not have).

- The credential scan stopped a real image build without saying what it had found. The
  hook searched `/etc` for the text `BEGIN PGP PRIVATE KEY` and printed the pattern it had
  searched for rather than the file that matched, so the build log held no path to
  investigate; a text search also cannot tell a leaked key from a file that merely *names*
  the armor format, which is what it matched. The check is now `astraos-scan-secrets`, a
  tool shipped in `astraos-base` and run by `0500-security.hook.chroot`, and it reports
  every match with its path and its dpkg owner. It recognises a key by its shape — a line
  that is exactly an armor header, followed before the block ends by the matching footer or
  by base64 payload — so magic(5) entries, compiled-in parser constants and documentation
  lines are reported as notes instead of failing the build. The scan also covers `/root`,
  `/home`, `/srv`, `/opt`, `/usr/local`, `/var/lib` and `/usr/share/astraos` instead of
  `/etc` alone, and it recognises the PKCS#8 armors (`-----BEGIN PRIVATE KEY-----` and
  `-----BEGIN ENCRYPTED PRIVATE KEY-----`) and the pre-2.0 `PGP SECRET KEY` spelling, none
  of which was in the fixed list of patterns it replaced. The tool is exercised against
  fixture trees by `tests/security/test_secret_scan.py`, including the magic(5) shape that
  failed the build and the requirement that a failure names the file.
- The repository scan in `tests/static/test_repository.py` used the same text search and had
  the same weakness: naming an armor header in a comment or in documentation was reported as
  a committed key. It now uses the shape rule too, so it still catches a key written into a
  file — including one missing its final line — and no longer requires an exception list to
  be told apart from a paragraph about keys.

- The security hook searched `/etc/sudoers.d` for the word `NOPASSWD` and matched the
  shipped policy's own sentence saying that no such rule exists, so a correct image was
  refused with "a passwordless sudo rule is present in /etc/sudoers.d". Both hooks now look
  for a *rule* — the pattern cannot reach past a comment marker — and a test pins it against
  the shipped policy in both directions: it must ignore the explanation, and it must still
  match a real passwordless rule. `tests/security/test_security_config.py` had always
  ignored comment lines for exactly this reason; the hooks had not.

- The installer verification hook required an *unquoted* `defaultFileSystemType: ext4` in
  the Calamares partitioning policy, while the configuration the installer package ships
  writes the value the other way YAML allows — quoted. Hooks run last, so the build died
  there with "partition.conf does not select ext4 as the default root filesystem" after
  every package had been installed, and the only way to find it was another full build.
  Both spellings are accepted now, and `tests/static/test_hook_assertions.py` compares the
  hook's pattern with the file the repository ships, in both directions: the pattern must
  still be the one the hook uses, and it must match (or, for a refusal, not match) the
  shipped file. The same module pins the partitioning-safety assertions.
- The image verification hook asserted that `/usr/bin/ssh` did not exist, while
  `config/package-lists/50-networking.list.chroot` deliberately selects `openssh-client`.
  No build could satisfy both, so the check would have failed at the very end of the next
  build. The property the project documents is that nothing *listens*: both hooks now test
  for the ssh server, and `docs/SECURITY.md` states that the client is present, is not a
  service and is never enabled. A test rejects any hook that requires a binary the package
  selection puts in the image.

- `astraos-branding`'s post-install script selected the boot-splash theme with
  `plymouth-set-default-theme`, which rewrites `/etc/plymouth/plymouthd.conf` — a file the
  `plymouth` package owns. A maintainer script runs inside the dpkg run that is configuring
  that very package, so dpkg found a configuration file that no longer matched the copy it
  had unpacked and stopped to ask which version to keep. Nothing answers that during a
  build, and the image build failed at the end of the chroot stage with "end of file on
  stdin at conffile prompt", after the entire base system had been installed. The theme is
  now selected by `config/live-build/config/hooks/live/0120-plymouth.hook.chroot`, which
  runs after every package is installed and configured; the hook rebuilds the initramfs,
  since the initramfs carries its own copy of the theme, and aborts the build if the theme,
  the tool or the rebuild is missing. The verify hook asserts both the selected theme and
  its presence in the initramfs, and a test rejects any package maintainer script that calls
  a tool rewriting another package's configuration file (verified to fail against the
  postinst as it was).

- The desktop defaults were installed into `/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/`,
  which belongs to Debian's Xfce packages: `libxfce4ui-common` owns the keyboard shortcuts
  file and `xfce4-settings` and `xfce4-session` own two more. Two packages cannot own the
  same path, and dpkg stopped the image build with "trying to overwrite". The panel layout,
  keyboard shortcuts, window-manager settings and wallpaper are now seeded through
  `/etc/skel`, which this project owns and which populates the live account and every account
  the installer creates. A test rejects a mapping back into the upstream directory.
- The installer list requested `calamares-settings-debian`, whose `/etc/calamares` tree is the
  same one `astraos-installer` owns — the second "trying to overwrite" in the same build.
  Nothing needs it: upstream `calamares` neither depends nor recommends it, only the
  `live-task-*` metapackages do. It is gone from the list, and `astraos-installer` now
  declares `Conflicts` and `Replaces` against it, so a future dependency chain produces a
  clean conflict instead of a half-finished unpack.
- `astraos-installer` declared `Depends: kpmcore`, which is a source package in Debian 13,
  not an installable binary (the library is `libkpmcore12`). apt resolved nothing and failed
  the image build after every package had been downloaded. The availability verifier checked
  only the package lists, never the dependencies the `.deb` files declare, so it now checks
  those too — including `Recommends` and alternative groups — and reports which file and
  field a bad name came from. AstraOS's own package names are excluded from that check
  because they are built by this repository.
- The AstraOS packages were staged one directory too deep. `build-packages.sh` wrote them to
  `build/live-build/live-build/config/packages.chroot`, while live-build only reads
  `config/packages.chroot` directly under its working directory. All five `.deb` files were
  built correctly and then left out of the image, so the image had no `astraos-info`, no
  branding and no installer. The identity hook caught it by asserting that the AstraOS
  packages are present after installation, and a test now rejects the repeated path segment.
- The image contained every `firmware-*` package in the Debian archive, not the reviewed
  selection in `config/package-lists/20-firmware.list.chroot`: live-build scans the archive
  and installs them all unless told not to. It also pulled in the contrib packages
  `firmware-b43-installer` and `firmware-b43legacy-installer`, which download Broadcom
  firmware from the internet in their post-install scripts; that download failed and stopped
  the build after several gigabytes had been installed. The sweep is now switched off
  (`--firmware-chroot false`), the list is authoritative and carries the hardware coverage
  the sweep provided, and the b43 gap is documented in `docs/HARDWARE_COMPATIBILITY.md`
  rather than papered over.
- A package list asked for two conflicting time daemons. `ntpsec` declares
  `Conflicts: time-daemon`, which `systemd-timesyncd` provides, so apt could not resolve the
  package set and failed after downloading all of it. `systemd-timesyncd` is the one AstraOS
  ships; a test now rejects any second time daemon.
- The `astraos-installer` control paragraph carried a comment block explaining its
  `Conflicts` and `Replaces` fields. A Debian control file has no comment syntax: dpkg-deb
  read the `#` as a field name and stopped the package build with "field name '#' must be
  followed by colon", after all five AstraOS packages had been assembled. The fields stay
  where they are; the explanation moved here and into `config/package-lists/60-installer.list.chroot`,
  which already documents why Debian's settings package is not wanted. A static test now
  checks every control template against the grammar dpkg-deb accepts — a field, an indented
  continuation, or a blank line — instead of finding out on a runner.
- The image build ran with the option set of whichever live-build happened to be installed.
  The pinned release (live-build 20250505 for Debian 13) renamed `--binary-images` to
  `--binary-image` and `--binary-compression` to `--chroot-squashfs-compression-type`, and
  removed `--tasks`, `--syslinux-timeout`, `--updates-chroot-security` and the volatile
  mirror option. The configuration now handles both spellings, and a test rejects any option
  passed without a `supports` probe. The option list was read out of the live-build package
  itself rather than guessed; the pinned release is also the one that has `--bootloaders`,
  which is what legacy BIOS boot support depends on.
- The chroot's apt failed with "The repository 'security.debian.org/debian-security
  trixie/updates Release' does not have a Release file", which stopped the build after
  bootstrapping had succeeded. The security and update suites now come from the repository's
  own archive list, which pins `trixie-security` and `trixie-updates` by name, and
  live-build's own generation of those two lines is switched off. Having two sources for the
  same suite had also produced a screenful of "configured multiple times" warnings on every
  apt run inside the chroot.
- CI assembled the image with the Ubuntu runner's older `debootstrap` and `live-build`,
  which is what produced the two problems above. The image is now built inside a
  `debian:trixie` container, so the toolchain is the release being assembled and the build
  no longer depends on the runner's distribution.
- `scripts/build-packages.sh` printed progress on stdout while `finish_package` and
  `stage_package` return a path through command substitution, so the package list captured a
  log line and the staging step looked for a file named after it. Progress goes to stderr,
  and a test enforces the split for any script that captures its own function's output.
- `auto/build` recursed: live-build runs `auto/<command>` as part of `lb <command>`, so the
  `lb build` inside `auto/build` re-ran `auto/build`, and the first build that reached the
  live-build stage died in a loop. The file is gone; the log capture and the
  ISO-existence check it performed now live in `scripts/build-iso.sh`, the process that
  starts live-build and can therefore wrap it. A test rejects any auto script that runs its
  own live-build command without the `noauto` positional.
- The auto scripts were linted as bash although live-build runs them with sh. That hid a
  `${PIPESTATUS[0]}` in `auto/build` which made every image build die with `Bad
  substitution` under dash before any package was downloaded. ShellCheck's dialect is now
  chosen per file: sh for the automatic scripts and the chroot hooks, bash for the rest.
- The image build validated a staging directory with `dpkg-deb --info` and discarded the
  error, which produced "dpkg-deb rejected the control directory for astraos-base" with no
  explanation. It now reads the produced `.deb` back and checks the name and version in it.
- Every script was committed without the executable bit, because it was first committed
  from Windows, which cannot store one. Nothing noticed locally — the files still run in
  Git Bash — and it broke the first real build on Linux, where
  `sudo ./scripts/bootstrap-build-environment.sh` failed with "command not found". Worse,
  live-build executes the chroot hooks from the checkout, so an unset bit would have failed
  the build rather than any check. The bit is now set for all 29 shebang files, and
  `tests/static/test_scripts.py` asserts the mode recorded in the git index, which is the
  only place it survives a Windows checkout.
- An absent ShellCheck was reported as a passing test. It is now reported as a skip with a
  reason, per the rule that an unperformed check is never a pass.
- `astraos-info` reported an inactive firewall as `active`. The `case` patterns were
  `*active*` and `*inactive*`, and `*active*` also matches `Status: inactive`, so the first
  match won and a fresh install — where ufw is shipped disabled by design — printed
  `firewall active`. The patterns are now anchored to the `Status:` prefix, and
  `tests/security/test_security_config.py` runs the real tool with a stub `ufw` on `PATH`
  so the reported state is checked behaviourally rather than by reading the source.
- ShellCheck findings, which only appear where ShellCheck is installed (the CI runner, not
  the development host): dead `REPO_ROOT`/`SCRIPT_DIR` assignments in
  `bootstrap-build-environment.sh` and `generate-checksums.sh`, and a `for` loop in
  `0600-cleanup.hook.chroot` written with a single-item list. That loop now preserves
  `/etc/astraos-release`, `/etc/lsb-release` and `/etc/os-release` as build provenance.
- Documentation staging: `README.md` was listed for installation into
  `/usr/share/doc/astraos/` but was copied from `docs/README.md`, which does not exist,
  so the image would have shipped with only a warning logged and no README — breaking the
  attribution pointer in `astraos-release-info`. The staging step now resolves each
  document's source path explicitly, and the packaging test asserts that `README.md` is
  taken from the repository root. Found by `tests/integration/test_packaging_mapping.py`
  on an unbuilt tree; no image has been built, so no shipped artifact is affected.

## [0.1.0] Alpha — codename Nova — unreleased

The first development release. **No image has passed structural validation or been
booted yet.** The status of
every deliverable is recorded in `README.md` and `docs/KNOWN_LIMITATIONS.md`.

### Added

**Distribution**
- Independent distribution identity: `/etc/os-release`, `/etc/astraos-release`,
  `/etc/lsb-release`, `/etc/issue`, `/etc/motd`, generated from version-controlled
  templates so the identity has one source of truth.
- Pinned Debian base: Debian 13 (trixie), amd64, with `trixie-updates` and
  `trixie-security` suites enabled and backports deliberately excluded.
- Package selection organised into eight reviewable lists: core, kernel, firmware,
  graphics, desktop, applications, networking and installer.
- Distribution utilities: `astraos-info`, `astraos-help`, `astraos-welcome`,
  `astraos-release-info`, `astraos-recovery-guide`.
- Five `.deb` packages: `astraos-base`, `astraos-branding`, `astraos-desktop`,
  `astraos-system-tools`, `astraos-installer`.

**Desktop**
- Xfce configuration applied through the documented mechanisms, so the desktop stays
  user-configurable and upgradable with upstream packages.
- Two-panel layout: a top status bar and a bottom launcher dock with a workspace
  switcher.
- Keyboard shortcuts for the launcher, terminal, file manager, browser, system
  information, screenshots, screen lock and task manager.
- AstraOS-Dark GTK theme (colour-only, built on Adwaita), AstraOS icon theme,
  Xfce skeleton defaults.
- Default applications: Firefox ESR, Thunar, xfce4-terminal, Mousepad, Atril,
  Ristretto, Parole, Xarchiver, Synaptic, GParted.

**Branding**
- Original AstraOS ring mark in colour and two monochrome variants, plus a wordmark.
- A dependency-free asset renderer (`branding/tools/render_assets.py`) that generates
  every bitmap from `config/branding.env` using only the Python standard library.
- Plymouth boot splash, GRUB menu theme, LightDM greeter theming, dark and light
  wallpapers, login background, and a brand preview page.

**Installer**
- Calamares configuration with a documented module sequence, and safety properties
  asserted at build time: the target disk is never assumed, erasing is never the
  default, partition labels are always shown, and the summary step precedes the
  destructive phase.
- Installer branding.
- No fixed or shared credentials; no autologin; the live-session account is removed
  from the installed system.

**Build system**
- `scripts/validate-environment.sh` — refuses to build on a host that cannot.
- `scripts/build-packages.sh` — builds the AstraOS packages reproducibly, driven by
  `SOURCE_DATE_EPOCH`.
- `scripts/configure-live-build.sh` — stages the live-build tree, renders templates and
  builds the packages.
- `scripts/build-iso.sh` — the single build entry point, fatal on any stage failure.
- `scripts/validate-iso.sh` — structural image validation, including inspection of the
  live filesystem contents.
- `scripts/verify-package-availability.py` — verifies every configured package against
  the real Debian archive index.
- CI: a pull-request validation workflow and a manually triggered ISO build workflow.

**Security**
- Documented sysctl defaults, sudo policy with no passwordless rules, APT signature
  policy, and a documented firewall policy that is not enabled by default.
- In-image assertions that fail the build if a passwordless sudo rule, an embedded
  private key, a disabled APT verification setting or an SSH server is present.

**Testing**
- A static test suite (`tests/run.py`) covering configuration consistency, package
  selection, branding asset validity and cross-references, desktop entries, Calamares
  safety settings, repository structure, secret scanning and shell script validation.

### Known limitations

See `docs/KNOWN_LIMITATIONS.md` for the complete list. The most significant:

- No image has passed structural validation, and none has been booted.
- Secure Boot is not supported and not claimed.
- `/etc/os-release` can be overwritten by an upgrade of Debian's `base-files`.
- The desktop theme does not include window decorations.
- No physical hardware has been tested.

### Notes

- AstraOS uses the Debian-supplied Linux kernel. It is not a from-scratch kernel, and
  the project does not present it as one.
- No AI feature is included, and nothing in the boot path depends on a network service.
