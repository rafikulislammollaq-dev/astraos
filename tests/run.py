#!/usr/bin/env python3
"""AstraOS test runner.

Runs every test group under tests/ that can run on the current host (plan §18):

  tests/unit/          unit tests for the project's own Python
  tests/static/        configuration, package lists, assets, desktop entries, scripts
  tests/integration/   the build scripts reference things that exist
  tests/security/      the security baseline is enforced and never weakened
  tests/boot/          the automated boot harness, and whether a boot is even possible
  tests/acceptance/    the documented procedures are complete and not overclaiming

WHAT THIS SUITE IS AND IS NOT
-----------------------------
It builds nothing and boots nothing. A green run means "the repository is internally
consistent and states nothing false about itself". It does not mean the operating system
works (plan §18: "Passing a shell syntax check is not evidence that the OS boots").

A test that cannot run in this environment raises SkipTest and is reported as SKIPPED with
its reason. A skip is not a pass. Boot testing in particular skips on a machine with no
hypervisor or no built image, and says so.

Usage:
  python3 tests/run.py                     run everything
  python3 tests/run.py static              run one group
  python3 tests/run.py test_config         run one module
  python3 tests/run.py static/test_config.py
  python3 tests/run.py --list              list tests without running them
  python3 tests/run.py --verbose           show passing checks and skip reasons
  ASTRAOS_RUN_VM_TEST=1 python3 tests/run.py boot   # actually attempt a boot

Exit codes: 0 all run tests passed, 1 at least one failed, 2 the runner could not start.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import sys
import traceback
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
LIB_DIR = TESTS_DIR / "lib"

# Make the shared helpers and the config parser importable from any test, and make it
# work even for a test that forgets to set up its own sys.path.
for extra in (LIB_DIR, REPO_ROOT / "scripts" / "lib"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))


class Result:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.failures: list[tuple[str, str]] = []
        self.skips: list[tuple[str, str]] = []


def load_module(path: Path):
    """Load a test module from a path, tolerating any module name collisions."""
    unique = f"{path.parent.name}_{path.stem}"
    spec = importlib.util.spec_from_file_location(unique, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def discover(selector: str | None) -> list[Path]:
    """Find test modules, optionally narrowed by a group, module or path selector."""
    everything = sorted(TESTS_DIR.glob("*/test_*.py"))

    if not selector:
        return everything

    # Normalise "static/", "static", "static/test_config", "test_config.py", ...
    cleaned = selector.strip().rstrip("/")
    if cleaned.endswith(".py"):
        cleaned = cleaned[:-3]
    if "/" in cleaned:
        group, _, stem = cleaned.partition("/")
        return [m for m in everything if m.parent.name == group and m.stem == stem]

    # A bare word: match a group name, or a module stem in any group.
    by_group = [m for m in everything if m.parent.name == cleaned]
    if by_group:
        return by_group
    return [m for m in everything if m.stem == cleaned]


def _skip_reason(module) -> str | None:
    """A module-level SKIP attribute makes every test in the module skip."""
    reason = getattr(module, "SKIP", None)
    return str(reason) if reason else None


def run_module(path: Path, result: Result, verbose: bool) -> None:
    group = path.parent.name
    module = load_module(path)

    print(f"\n{group}/{path.name}")
    describe = getattr(module, "DESCRIPTION", "")
    if describe:
        print(f"  {describe}")

    module_skip = _skip_reason(module)
    tests = [(name, obj) for name, obj in vars(module).items()
             if name.startswith("test_") and callable(obj)]
    if not tests:
        print("  (no tests found)")
        return

    try:
        from astraos_testlib import SkipTest
    except Exception:  # noqa: BLE001 - the helper should always exist, but never crash on it
        class SkipTest(Exception):  # type: ignore[no-redef]
            pass

    for name, func in tests:
        if module_skip:
            result.skipped += 1
            result.skips.append((f"{group}/{path.name}::{name}", module_skip))
            print(f"  SKIP  {name}")
            print(f"        {module_skip}")
            continue

        # Capture anything a test prints so passing output stays quiet; always show it for
        # a failure or a skip.
        buffer = io.StringIO()
        real_stdout = sys.stdout
        sys.stdout = buffer
        try:
            func()
        except SkipTest as exc:
            sys.stdout = real_stdout
            result.skipped += 1
            reason = str(exc) or "no reason given"
            result.skips.append((f"{group}/{path.name}::{name}", reason))
            print(f"  SKIP  {name}")
            print(f"        {reason}")
            continue
        except AssertionError as exc:
            sys.stdout = real_stdout
            result.failed += 1
            detail = str(exc) or "assertion failed"
            result.failures.append((f"{group}/{path.name}::{name}", detail))
            print(f"  FAIL  {name}")
            for line in detail.splitlines():
                print(f"        {line}")
            continue
        except Exception:  # noqa: BLE001 - a crashing test is a failing test
            sys.stdout = real_stdout
            result.failed += 1
            detail = traceback.format_exc()
            result.failures.append((f"{group}/{path.name}::{name}", detail))
            print(f"  ERROR {name}")
            for line in detail.rstrip().splitlines()[-6:]:
                print(f"        {line}")
            continue
        finally:
            sys.stdout = real_stdout

        result.passed += 1
        if verbose:
            print(f"  PASS  {name}")
            for line in buffer.getvalue().splitlines():
                print(f"        {line}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("selector", nargs="?",
                        help="group name, module name, or group/module path")
    parser.add_argument("--list", action="store_true", help="list tests without running")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="show passing checks and skip reasons")
    args = parser.parse_args()

    modules = discover(args.selector)
    if not modules:
        print(f"no test modules matched {args.selector!r} under {TESTS_DIR}", file=sys.stderr)
        available = sorted({m.parent.name for m in TESTS_DIR.glob("*/test_*.py")})
        if available:
            print(f"available groups: {', '.join(available)}", file=sys.stderr)
        return 2

    if args.list:
        for path in modules:
            module = load_module(path)
            print(f"{path.parent.name}/{path.name}")
            for name in sorted(vars(module)):
                obj = vars(module)[name]
                if name.startswith("test_") and callable(obj):
                    print(f"    {name}")
        return 0

    print("AstraOS test suite")
    print(f"repository: {REPO_ROOT}")
    print(f"groups    : {', '.join(sorted({m.parent.name for m in modules}))}")
    print("these tests build nothing and boot nothing; they check that the repository is")
    print("internally consistent and claims nothing false about itself")

    result = Result()
    for path in modules:
        try:
            run_module(path, result, args.verbose)
        except Exception:  # noqa: BLE001 - a module that will not load is a failure
            result.failed += 1
            detail = traceback.format_exc()
            result.failures.append((f"{path.parent.name}/{path.name}", detail))
            print(f"\n{path.parent.name}/{path.name}")
            print("  ERROR module failed to load")
            for line in detail.rstrip().splitlines()[-6:]:
                print(f"        {line}")

    print("\n" + "=" * 62)
    print(f"passed  : {result.passed}")
    print(f"skipped : {result.skipped}")
    print(f"failed  : {result.failed}")

    if result.skips:
        print("\nskipped (NOT passes — these did not run):")
        for name, reason in result.skips:
            print(f"  {name}\n      {reason}")

    if result.failures:
        print("\nfailures:")
        for name, detail in result.failures:
            first_line = detail.strip().splitlines()[0] if detail.strip() else "failed"
            print(f"  {name}\n      {first_line}")

    if result.failed:
        print("\nRESULT: FAILED")
        return 1

    print("\nRESULT: PASSED" + (f" ({result.skipped} skipped)" if result.skipped else ""))
    print("Reminder: this does not prove the operating system boots. See")
    print("docs/INSTALLATION_VIRTUALBOX.md for the procedure that does.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
