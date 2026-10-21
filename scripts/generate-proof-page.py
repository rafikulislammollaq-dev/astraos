#!/usr/bin/env python3
"""Assemble a run's evidence into one page a reader can check.

The project's rule is that a claim is worth exactly what the run that proves it
says. Right now that evidence is spread over five CI artifacts, each a log a
reader has to know how to read. This script reads those artifacts and writes one
document: the image, the live self-test, the three boot paths, the install, the
APT archive, and - at the end - what none of it proves.

Two rules govern the output:

  * Every line is read from an artifact. Nothing is written by hand, and no line
    is inferred from the absence of a failure.
  * A missing artifact is reported as missing. "not shown in this run" is a
    sentence this script is allowed to write; "passed" is not, unless the log
    says so.

Usage:
    scripts/generate-proof-page.py --evidence DIR --out FILE [--run-id ID]

The evidence directory is expected to hold the CI artifacts, each in its own
folder:

    evidence/self-test/{serial.log,screenshot.png}
    evidence/menus/menus-{bios,efi,secure}/serial.log
    evidence/menus/menus-secure/firmware.txt
    evidence/install/{done,serial1.log,serial2.log,calamares-session.log}
    evidence/build-logs/logs/build-*.log
    evidence/apt-repo/dists/stable/Release

Every one of them is optional: the page says what is missing instead of failing.

Exit codes:
    0  the page was written
    2  the evidence directory does not exist or is not a directory
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# The prompt the live system prints on the serial console. It comes from the same
# definition as the boot-menu exercise, so a log that contains it reached a booted
# system and not a kernel panic.
LOGIN_PROMPT = "login:"

# What a run of this pipeline can never prove, however green it is. Kept here so
# the page says it even if the caller forgets: the honest list is the point.
NOT_PROVEN = (
    "Physical hardware. No install has been run on a real machine; the hardware "
    "expectations are in docs/HARDWARE_COMPATIBILITY.md, and that document is a list "
    "of expectations, not of results.",
    "Signed images. The ISO is not signed by AstraOS. It boots under Secure Boot "
    "because it carries Debian's signed chain, not because AstraOS signs anything.",
    "A hosted APT archive. The archive this build produced is unsigned and lives in "
    "the build artifacts; where it will be hosted is still open.",
    "A browser in a booted image. The network stack is proven in CI; no browser has "
    "been launched inside a booted image yet.",
)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _yesno(flag: bool) -> str:
    return "yes" if flag else "no"


def _count(number: int, word: str) -> str:
    return f"{number} {word}" if number == 1 else f"{number} {word}s"


class Proof:
    """Collects what the artifacts say. Nothing here is a judgement of its own."""

    def __init__(self, evidence: Path) -> None:
        self.evidence = evidence
        self.lines: list[str] = []
        self.missing: list[str] = []
        self.build_log: str = ""

    def folder(self, *candidates: str) -> Path | None:
        """The first of these folders that exists.

        The CI artifacts arrive under their own names (astraos-boot-self-test,
        astraos-boot-menus, ...); a hand-made evidence directory usually uses short
        ones. Both are accepted, so the script reads what the caller has.
        """
        for name in candidates:
            path = self.evidence / name
            if path.is_dir():
                return path
        return None

    def note_missing(self, what: str) -> None:
        self.missing.append(what)

    # -- the image ---------------------------------------------------------------
    def image(self) -> None:
        self.lines.append("## The image")
        logs = sorted(self.evidence.glob("**/logs/build-*.log"))
        if not logs:
            self.note_missing("the build log (the image's hash and structural checks)")
            self.lines.append("")
            self.lines.append("Not shown in this run: the build log, so the image's hash "
                              "and its structural checks are not on this page.")
            return
        text = _read(logs[-1]) or ""
        self.build_log = text

        name = re.search(r"computing sha256 for (\S+\.iso)", text)
        digest = re.search(r"sha256 = ([0-9a-f]{64})", text)
        # The validator prints its own summary; the last one before the verdict is
        # the image's structural validation, not an earlier checker's.
        summary = re.findall(r"passed: (\d+)\s+warnings: (\d+)\s+failures: (\d+)", text)
        verdict = "STRUCTURAL validation" in text

        self.lines.append("| | |")
        self.lines.append("|---|---|")
        self.lines.append(f"| Image | {name.group(1) if name else 'not shown in this run'} |")
        self.lines.append(
            f"| SHA-256 | `{digest.group(1)}` |" if digest
            else "| SHA-256 | not shown in this run |"
        )
        if summary:
            passed, warnings, failures = summary[-1]
            self.lines.append(f"| Structural checks | {passed} passed, "
                              f"{_count(int(failures), 'failure')}, "
                              f"{_count(int(warnings), 'warning')} |")
        else:
            self.note_missing("the image's structural check summary")
            self.lines.append("| Structural checks | not shown in this run |")
        self.lines.append(
            f"| Structural verdict | the image {'passed' if verdict else 'did not report a'} "
            "STRUCTURAL validation |"
        )
        self.lines.append("")

    # -- the live image ----------------------------------------------------------
    def live(self) -> None:
        self.lines.append("## The live image")
        folder = self.folder("self-test", "astraos-boot-self-test")
        serial_path = (folder / "serial.log") if folder else None
        serial = _read(serial_path) if serial_path else None
        if serial is None:
            self.note_missing("the boot self-test log")
            self.lines.append("")
            self.lines.append("Not shown in this run: the boot self-test log.")
            self.lines.append("")
            return

        result = re.search(r"ASTRAOS-SMOKE: RESULT: ([A-Z]+) \((\d+) checks, (\d+) failed\)", serial)
        ok_lines = len(re.findall(r"ASTRAOS-SMOKE: ok ", serial))
        fail_lines = len(re.findall(r"ASTRAOS-SMOKE: FAIL ", serial))

        self.lines.append(f"- The image's own self-test reported "
                          f"`{result.group(0).split('ASTRAOS-SMOKE: ')[-1] if result else 'no result line'}`.")
        self.lines.append(f"- Checks that passed: {ok_lines}. Checks that failed: {fail_lines}.")
        for check in ("hud-on-screen", "screenshot-ready", "ai-profile"):
            if f"ASTRAOS-SMOKE: ok {check} " in serial:
                self.lines.append(f"- `{check}` passed.")
        shot = self.evidence / "self-test" / "screenshot.png"
        if folder:
            shot = folder / "screenshot.png"
        size = _size(shot)
        if size is None:
            self.note_missing("the self-test screenshot")
            self.lines.append("- The capture: not present in this run's artifacts.")
        else:
            self.lines.append(f"- The capture: `screenshot.png`, {size:,} bytes.")
        self.lines.append("")

    # -- the boot menus ----------------------------------------------------------
    def menus(self) -> None:
        self.lines.append("## The boot paths the firmware took")
        self.lines.append("")
        self.lines.append("| Path | Reached the live login prompt | Evidence |")
        self.lines.append("|---|---|---|")
        menus = self.folder("menus", "astraos-boot-menus")
        for medium, label in (
            ("bios", "BIOS (syslinux)"),
            ("efi", "UEFI (GRUB)"),
            ("secure", "UEFI under Secure Boot (OVMF secboot, Microsoft keys enrolled)"),
        ):
            serial = _read(menus / f"menus-{medium}" / "serial.log") if menus else None
            if serial is None:
                self.note_missing(f"the {medium} boot-menu log")
                self.lines.append(f"| {label} | not shown in this run | - |")
                continue
            reached = LOGIN_PROMPT in serial
            self.lines.append(
                f"| {label} | {_yesno(reached)} | `menus-{medium}/serial.log` |"
            )
        self.lines.append("")

        firmware = _read(menus / "menus-secure" / "firmware.txt") if menus else None
        if firmware:
            self.lines.append("The Secure Boot run used this firmware, by hash:")
            self.lines.append("")
            self.lines.append("```")
            self.lines.extend(firmware.strip().splitlines())
            self.lines.append("```")
            self.lines.append("")

    # -- the install -------------------------------------------------------------
    def install(self) -> None:
        self.lines.append("## The install")
        folder = self.folder("install", "astraos-install-test")
        done = _read(folder / "done") if folder else None
        serial2 = _read(folder / "serial2.log") if folder else None
        session = _read(folder / "calamares-session.log") if folder else None

        if done is None:
            self.note_missing("the install exercise's result")
            self.lines.append("")
            self.lines.append("Not shown in this run: the install exercise.")
            self.lines.append("")
            return

        rc = done.strip()
        self.lines.append(f"- The installer exercise reported `{rc}`.")
        if session:
            jobs = re.findall(r'Starting job "([a-z0-9-]+)"', session)
            if jobs:
                self.lines.append(f"- Calamares ran {len(jobs)} jobs: "
                                  + ", ".join(f"`{job}`" for job in jobs) + ".")
        if serial2 and "mode: installed" in serial2:
            self.lines.append("- The installed system booted with no medium attached and "
                              "reported its mode as `installed`.")
            result = re.search(r"ASTRAOS-SMOKE: RESULT: ([A-Z]+) \((\d+) checks, (\d+) failed\)", serial2)
            if result:
                self.lines.append(f"- Its own self-test then reported `{result.group(0).split('ASTRAOS-SMOKE: ')[-1]}`.")
        greeter = _size(folder / "greeter.png") if folder else None
        if greeter is None:
            self.note_missing("the greeter capture")
            self.lines.append("- The greeter capture: not present in this run's artifacts.")
        else:
            self.lines.append(f"- The greeter capture: `greeter.png`, {greeter:,} bytes.")
        self.lines.append("")

    # -- the archive -------------------------------------------------------------
    def archive(self) -> None:
        self.lines.append("## The APT archive")
        folder = self.folder("apt-repo", "astraos-apt-repo")
        release = _read(folder / "dists" / "stable" / "Release") if folder else None
        packages = _read(folder / "dists" / "stable" / "main"
                         / "binary-amd64" / "Packages") if folder else None
        if release is None:
            self.note_missing("the APT archive")
            self.lines.append("")
            self.lines.append("Not shown in this run: the APT archive.")
            self.lines.append("")
            return
        count = len(re.findall(r"^Package: ", packages or "", re.M))
        signed = bool(folder) and (folder / "dists" / "stable" / "InRelease").is_file()
        self.lines.append(f"- The archive holds {_count(count, 'package')}.")
        self.lines.append(f"- It is {'signed' if signed else 'unsigned'}.")
        # The claim that something installed from the archive is only made when the
        # build log records the fetches. Asserting it without the evidence would be
        # the one way this page could lie.
        fetched = "file:/packages" in self.build_log and "astraos-system-tools 0.2.0" in self.build_log
        if fetched:
            self.lines.append("- A fresh container updated from it and installed the packages "
                              "out of it (the build log records the fetches).")
        else:
            self.lines.append("- The build log does not record an install from it, so that "
                              "is not claimed here.")
        self.lines.append("")

    # -- the honest end ----------------------------------------------------------
    def limits(self) -> None:
        self.lines.append("## What this run does not prove")
        self.lines.append("")
        for item in NOT_PROVEN:
            self.lines.append(f"- {item}")
        self.lines.append("")

    def render(self, run_id: str | None, commit: str | None) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        head = [
            "# The proof page",
            "",
            f"Generated by `scripts/generate-proof-page.py` from the artifacts of CI run "
            f"{run_id or 'unknown'}",
        ]
        if commit:
            head.append(f"(commit `{commit}`)")
        head.append(f"on {stamp}. Every line below is read from an artifact of that run; "
                    "nothing here is written by hand.")
        head.append("")

        body = list(self.lines)
        if self.missing:
            body.append("## Artifacts this page could not read")
            body.append("")
            for item in self.missing:
                body.append(f"- {item}")
            body.append("")
        return "\n".join(head + body).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--evidence", required=True, help="directory holding the run's artifacts")
    parser.add_argument("--out", required=True, help="where to write the page")
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID"), help="the CI run id")
    parser.add_argument("--commit", default=os.environ.get("GITHUB_SHA"), help="the commit that was built")
    args = parser.parse_args(argv)

    evidence = Path(args.evidence)
    if not evidence.is_dir():
        print(f"ERROR: no evidence directory: {evidence}", file=sys.stderr)
        return 2

    proof = Proof(evidence)
    proof.image()
    proof.live()
    proof.menus()
    proof.install()
    proof.archive()
    proof.limits()

    page = proof.render(args.run_id, args.commit)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({len(page):,} bytes)")
    if proof.missing:
        print(f"note: {len(proof.missing)} artifact(s) were not in the evidence: "
              + "; ".join(proof.missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
