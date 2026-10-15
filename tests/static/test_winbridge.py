"""Windows command bridge tests.

The bridge is 54 tiny wrappers in front of one 1500-line POSIX shell script. It is the
part of AstraOS a Windows migrant meets first, and until this module existed it had no
test coverage at all - which is how it came to ship with a dispatcher that never
dispatched, and still passed every check in the repository.

What was actually wrong, and what each test below is aimed at:

  * The bridge defined 49 cmd_* handlers and called none of them. Every wrapper printed
    "'dir' is a Windows command. On AstraOS: dir" - telling the user to run the command
    they had just run - and exited 127. `sh -n` cannot see this, and neither can any
    check that only reads the file's structure.

  * When the dispatcher was added, a POSIX shell ran on past the end of the case and
    reached the mapping-table fallback, so `dir` printed its listing *and then* the
    "is a Windows command" line, and returned 127 on success. Hence
    test_bridge_runs_a_command_and_stops_there, which runs the real script.

  * winpath() printed paths without a trailing newline, so collect_paths() - which
    rebuilds "$@" by splitting that captured string - concatenated every argument:
    `copy a.txt b.txt` collected "a.txtb.txt" and answered with its usage message.

  * Every *_switch() matcher used the pattern /[A-Za-z]*, which matches /w and /home
    alike, so every absolute path was swallowed as a Windows switch: `md /tmp/newdir`
    collected no paths at all. Relative paths hid it.

  * Four handlers delegated with `exec mkdir`, `exec ping`, `exec tree` and `exec
    netstat` - the very names their own wrappers shadow on PATH - so each one re-entered
    the bridge with the same arguments and looped. PATH reordering in run_real() fixed
    it, and test_no_handler_delegates_to_a_command_it_shadows keeps it fixed.

A note on what these tests can and cannot prove. They run the real script, so a broken
dispatcher fails here rather than in a virtual machine. They do not prove the commands
are reachable from a login shell: that depends on /etc/profile.d putting the wrappers on
PATH, which is checked separately by test_the_wrapper_directory_is_added_to_path.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "lib"))

from astraos_testlib import SkipTest, require_tool, run_command, strip_comments  # noqa: E402

DESCRIPTION = "the Windows command bridge dispatches, and its mapping table is consistent"

WINBRIDGE = REPO_ROOT / "packages" / "astraos-winbridge"
WINBIN = WINBRIDGE / "root" / "usr" / "lib" / "astraos" / "winbin"
BRIDGE = WINBIN / "bridge"
WINMAP = WINBIN / "winmap.txt"
PROFILE = WINBRIDGE / "root" / "etc" / "profile.d" / "astraos-winbridge.sh"
INTERACTIVE = WINBRIDGE / "root" / "usr" / "lib" / "astraos" / "shell" / "interactive.sh"

NOT_A_WRAPPER = {"bridge", "winmap.txt"}

# The line that separates the definitions from the code that runs. Everything above it
# is safe to source; everything below it acts on "$@".
DISPATCH_MARKER = "# Dispatch"


def _bridge_text() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def _bridge_code() -> str:
    """The bridge with its comments removed.

    Several checks below search for calls, and the bridge's comments quote the very
    calls they describe: cmd_md's comment shows `exec mkdir -p "$@"` as the shape of the
    recursion bug, and real_tool's docstring explains why `command -v rename` finds the
    wrapper. Searching the raw text would fail the tests that exist to catch the real
    thing, which is worse than not having them. Both of those are full-line comments,
    which is what strip_comments handles.
    """
    return strip_comments(_bridge_text())


def _wrappers() -> list[str]:
    return sorted(p.name for p in WINBIN.iterdir()
                  if p.is_file() and p.name not in NOT_A_WRAPPER)


def _mapping_rows() -> list[tuple[int, str, str, str]]:
    """(line number, windows name, linux equivalent, description) for each table row."""
    rows = []
    for number, line in enumerate(WINMAP.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("|")
        rows.append((number, *(parts + [""] * (3 - len(parts)))[:3]))
    return rows


def _bridge_library() -> str:
    """The bridge's function definitions, up to but not including its dispatch."""
    lines = _bridge_text().splitlines()
    for index, line in enumerate(lines):
        if line.strip() == DISPATCH_MARKER:
            # Drop back over the banner comment the marker sits inside.
            while index and lines[index].lstrip().startswith("#"):
                index -= 1
            return "\n".join(lines[: index + 1])
    raise AssertionError(f"{DISPATCH_MARKER!r} not found in {BRIDGE}")


def _run_library(body: str) -> str:
    """Source the bridge's definitions and run `body` against them, returning stdout."""
    shell = require_tool("sh", "the bridge is POSIX shell and only a shell can run it")
    script = _bridge_library() + "\n" + body + "\n"
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, newline="\n") as handle:
        handle.write(script)
        path = handle.name
    try:
        result = run_command([shell, path], timeout=60)
    finally:
        Path(path).unlink(missing_ok=True)
    if result.returncode != 0:
        raise AssertionError(
            f"sourcing the bridge's own definitions failed (exit {result.returncode})\n"
            f"{result.stdout}{result.stderr}"
        )
    return result.stdout


def test_every_wrapper_is_dispatched() -> None:
    """A wrapper with no case label runs the fallback hint instead of the command.

    This is the shape the bridge shipped in: the wrappers existed, the handlers existed,
    and nothing joined them up.
    """
    text = _bridge_text()
    dispatched = set()
    for match in re.finditer(r"^\s{4}([a-z0-9_.-]+(?:\|[a-z0-9_.-]+)*)\)\s", text, re.M):
        dispatched.update(match.group(1).split("|"))
    undispatched = [w for w in _wrappers() if w not in dispatched]
    assert not undispatched, (
        "these wrappers have no case label in the bridge's dispatch, so they print a hint "
        f"and exit 127 instead of running: {undispatched}"
    )


def test_every_dispatched_command_has_a_handler() -> None:
    """A case label naming a function that does not exist fails the same way at runtime."""
    text = _bridge_text()
    defined = set(re.findall(r"^(cmd_[a-z0-9_]+)\(\)", text, re.M))
    called = set(re.findall(r"\b(cmd_[a-z0-9_]+)\s+\"?\$@", text))
    missing = sorted(called - defined)
    assert not missing, f"the dispatch calls handlers that are not defined: {missing}"


def test_no_handler_is_defined_and_unused() -> None:
    """A handler nothing calls is dead code that looks live; the dispatcher must reach all."""
    text = _bridge_text()
    defined = set(re.findall(r"^(cmd_[a-z0-9_]+)\(\)", text, re.M))
    body_after_definitions = "\n".join(
        line for line in text.splitlines() if not re.match(r"^cmd_[a-z0-9_]+\(\)", line)
    )
    unused = sorted(
        name for name in defined
        if not re.search(r"\b%s\b" % re.escape(name), body_after_definitions)
    )
    assert not unused, f"these handlers are defined but never called: {unused}"


def test_bridge_runs_a_command_and_stops_there() -> None:
    """`dir` must list the directory, exit 0, and print nothing else.

    Runs the real script rather than reading it. Before the dispatcher existed this
    printed only the hint line and exited 127; after the dispatcher was added but before
    it was made terminal, the listing appeared followed by "'dir' is a Windows command.
    On AstraOS: dir" and exit 127.
    """
    shell = require_tool("sh", "the bridge is POSIX shell and only a shell can run it")
    with tempfile.TemporaryDirectory(prefix="astraos-bridge-") as workdir:
        Path(workdir, "sentinel-file.txt").write_text("hello\n")
        result = run_command([shell, str(BRIDGE), "dir"], cwd=Path(workdir))
    assert result.returncode == 0, (
        f"`dir` exited {result.returncode}, not 0: {result.stdout}{result.stderr}"
    )
    assert "sentinel-file.txt" in result.stdout, (
        f"`dir` did not list the directory: {result.stdout!r}"
    )
    assert "is a Windows command" not in result.stdout + result.stderr, (
        "`dir` ran its handler and then fell through to the mapping-table lookup, which is "
        "what the _HANDLED guard after the dispatch case exists to prevent"
    )


def test_winpath_terminates_each_path_with_a_newline() -> None:
    """collect_paths() splits its captured output on newline, so winpath must emit one.

    Without the newline, two paths arrive as one: `copy a.txt b.txt` collected
    "a.txtb.txt" and printed its usage message.
    """
    output = _run_library(
        'collect_paths simple_path_switch alpha beta gamma\n'
    )
    fields = output.split()
    assert fields == ["alpha", "beta", "gamma"], (
        "collect_paths did not keep the arguments separate; it produced "
        f"{output.strip()!r} for three paths. winpath() must end with printf '%s\\n'."
    )


def test_collect_paths_rebuilds_multiple_arguments() -> None:
    """The end of the contract: the newline-separated string splits back into "$@"."""
    output = _run_library(
        '_PATHS="$(collect_paths simple_path_switch alpha beta gamma)"\n'
        "set -f; _ifs_old=$IFS; IFS='\n'\n"
        "set -- $_PATHS\n"
        "IFS=$_ifs_old; set +f\n"
        'printf "argc=%s\\n" "$#"\n'
        'for _x in "$@"; do printf "arg=[%s]\\n" "$_x"; done\n'
    )
    assert "argc=3" in output, f"three paths became the wrong number of arguments: {output!r}"
    for name in ("alpha", "beta", "gamma"):
        assert f"arg=[{name}]" in output, f"{name!r} did not survive the round trip: {output!r}"


def test_an_existing_absolute_path_is_not_a_switch() -> None:
    """Windows writes switches with a slash, and so does every absolute Unix path.

    /[A-Za-z]* matches /w and /home alike. Before the guard, `md /tmp/newdir` collected
    no paths at all and answered with its usage line.
    """
    output = _run_library(
        "_tmp=\"$(mktemp -d)\"\n"
        'printf "existing-dir=%s\\n" "$(looks_like_windows_switch "$_tmp" '
        '&& echo switch || echo path)"\n'
        'printf "nested-path=%s\\n" "$(looks_like_windows_switch "$_tmp/a/b" '
        '&& echo switch || echo path)"\n'
        'printf "dir-switch-on-existing=%s\\n" "$(dir_switch "$_tmp" && echo switch || echo path)"\n'
        'printf "dir-switch-on-w=%s\\n" "$(dir_switch /w && echo switch || echo path)"\n'
        'rmdir "$_tmp"\n'
    )
    assert "existing-dir=path" in output, (
        f"a directory that exists was taken for a Windows switch: {output!r}"
    )
    assert "nested-path=path" in output, (
        f"a path with more than one component was taken for a Windows switch: {output!r}"
    )
    assert "dir-switch-on-existing=path" in output, (
        f"dir_switch ignored the guard: {output!r}"
    )
    assert "dir-switch-on-w=switch" in output, (
        f"the Windows switch /w stopped being a switch: {output!r}"
    )


def test_every_switch_matcher_consults_the_guard() -> None:
    """A new matcher that forgets looks_like_windows_switch reintroduces the /home bug."""
    matchers = [
        (name, body)
        for name, body in re.findall(r"^([a-z_]+_switch)\(\)\s*\{(.*)$", _bridge_code(), re.M)
        # The guard itself is named ..._switch and does not consult anything.
        if name != "looks_like_windows_switch"
    ]
    assert matchers, "no switch matchers found; the naming convention must have changed"
    unguarded = [name for name, body in matchers if "looks_like_windows_switch" not in body]
    assert not unguarded, (
        "these switch matchers do not call looks_like_windows_switch, so they will read "
        f"absolute paths as switches: {unguarded}"
    )


def test_no_handler_delegates_to_a_command_it_shadows() -> None:
    """`exec mkdir` inside cmd_md re-enters the bridge and loops forever.

    The wrappers sit on PATH ahead of /usr/bin, so a handler that delegates by name
    reaches its own wrapper. Delegation must go through run_real(), and "is it
    installed?" probes through real_tool().
    """
    text = _bridge_code()
    shadows = set(_wrappers())
    offenders = []
    for match in re.finditer(r"\bexec\s+([A-Za-z][A-Za-z0-9_.-]*)", text):
        name = match.group(1)
        if name in shadows:
            offenders.append(f"exec {name}")
    for match in re.finditer(r"\bcommand\s+-v\s+([A-Za-z][A-Za-z0-9_.-]*)", text):
        name = match.group(1)
        if name in shadows:
            offenders.append(f"command -v {name}")
    assert not offenders, (
        "these calls resolve to the bridge's own wrapper rather than the real tool, so the "
        f"handler re-enters itself: {offenders}. Use run_real() or real_tool()."
    )


def test_every_wrapper_has_a_mapping_row() -> None:
    """The table drives `bridge --list` and `astra help`, so a missing row hides a command."""
    rows = _mapping_rows()
    named = {name for _, name, _, _ in rows}
    missing = [w for w in _wrappers() if w not in named]
    assert not missing, (
        f"these wrappers are invisible to `bridge --list` and `astra help`: {missing}"
    )


def test_mapping_rows_are_well_formed() -> None:
    for line, name, equivalent, description in _mapping_rows():
        assert name, f"line {line}: no Windows command name"
        assert equivalent, f"line {line} ({name!r}): no Linux equivalent (use NONE)"
        assert description, f"line {line} ({name!r}): no description"
        assert "|" not in name + equivalent + description, f"line {line}: too many fields"


def test_mapping_table_has_no_duplicate_command_names() -> None:
    seen: dict[str, int] = {}
    duplicates = []
    for line, name, _, _ in _mapping_rows():
        if name in seen:
            duplicates.append(f"{name!r} on lines {seen[name]} and {line}")
        seen[name] = line
    assert not duplicates, (
        "the table is read by taking the first match, so a duplicate hides the other row: "
        f"{duplicates}"
    )


def test_mapping_table_is_sorted_by_command_name() -> None:
    """The file says so in its own header, and unsorted rows make the cheat sheet hard to read."""
    names = [name for _, name, _, _ in _mapping_rows()]
    out_of_order = [
        f"{a!r} before {b!r}" for a, b in zip(names, names[1:]) if a > b
    ]
    assert not out_of_order, f"rows are not in ascending order: {out_of_order}"


def test_the_wrapper_directory_is_added_to_path() -> None:
    """The wrappers are useless unless a login shell and a GUI session both get them.

    They are deliberately not installed into /usr/bin, to avoid a dpkg-level file
    conflict with coreutils' dir(1) and net-tools' netstat(1), so PATH is the only
    route in - and there are two entry points, because Xsession is not a login shell.
    """
    profile = PROFILE.read_text(encoding="utf-8")
    assert "/usr/lib/astraos/winbin" in profile, (
        f"{PROFILE.relative_to(REPO_ROOT)} does not add the wrapper directory to PATH"
    )
    xsession = WINBRIDGE / "root" / "etc" / "X11" / "Xsession.d" / "95astraos-environment"
    assert xsession.is_file(), (
        "the GUI session hook is missing, so a desktop session would never see the wrappers"
    )
    assert "astraos-winbridge.sh" in xsession.read_text(encoding="utf-8"), (
        "the GUI session hook does not source the profile script, so the wrappers are not "
        "on PATH in a desktop session"
    )


def test_the_wrapper_directory_is_prepended_to_path() -> None:
    """Prepend, not append: appending would leave coreutils in charge of `dir`.

    Seven wrappers shadow a real tool, and the whole design depends on the wrapper
    winning that contest and then handing Unix-style calls back to the real tool. The
    trade is written up in the profile script; this checks the code still makes it.
    """
    assignments = re.findall(r'PATH="([^"]+)"', PROFILE.read_text(encoding="utf-8"))
    assert assignments, "profile.d never sets PATH, so no wrapper is ever reachable"
    assert any(a.startswith("$WINBIN:") for a in assignments), (
        "profile.d adds the wrapper directory to the END of PATH, so the seven wrappers "
        f"that shadow a real tool would never run: {assignments}"
    )


def test_the_real_dir_keeps_its_own_flags() -> None:
    """`dir -1` and `dir --version` belong to coreutils, not to the Windows wrapper.

    dir is the loudest of the seven shadowed names - it is the first command a Windows
    migrant types - so the wrapper has to sit in front of the real tool, and the real
    tool still has to work afterwards. run_real() re-executes with winbin removed from
    PATH, which is what makes both true at once.
    """
    shell = require_tool("sh", "the bridge is POSIX shell and only a shell can run it")
    require_tool("dir", "this test needs the real dir(1) to delegate to")
    result = run_command([shell, str(BRIDGE), "dir", "--version"])
    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"`dir --version` exited {result.returncode}: {combined!r}. The wrapper treated a "
        "Unix flag as a Windows path instead of delegating to the real dir(1)."
    )
    assert "cannot access" not in combined, (
        f"`dir --version` was passed to ls as a filename instead of being delegated: {combined!r}"
    )


def test_type_reads_a_file_in_an_interactive_shell() -> None:
    """`type FILE` is one of the most-used cmd commands, and bash's builtin owns the name.

    Only a shell function can win that contest, and it must not exist in a script, so
    this sources interactive.sh the way profile.d does - interactively - and checks that
    the Windows meaning works and that the bash meaning still does.
    """
    bash = require_tool("bash", "interactive.sh is a bash file")
    with tempfile.TemporaryDirectory(prefix="astraos-type-") as workdir:
        Path(workdir, "note.txt").write_text("file contents here\n")
        script = (
            f". {INTERACTIVE}\n"
            "type note.txt\n"
            "type ls >/dev/null 2>&1 && printf 'names-still-work=yes\\n'\n"
        )
        # -i, because interactive.sh deliberately returns early in a non-interactive
        # shell: a function named `type` must never reach a script.
        result = run_command([bash, "-i", "-c", script], cwd=Path(workdir))
    combined = result.stdout + result.stderr
    assert "file contents here" in combined, (
        f"`type note.txt` did not print the file: {combined!r}"
    )
    assert "names-still-work=yes" in combined, (
        f"`type ls` stopped describing commands: {combined!r}"
    )
