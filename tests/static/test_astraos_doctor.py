"""Tests for astraos-doctor, the health report and the report safe to share.

The doctor is the command a user runs when something is wrong and wants to say
so precisely, or when they want to paste their machine's state into a bug
report. Two properties matter more than the format of the report:

  * it only reads. It never writes, never asks for a password and never runs
    anything as root, so it is safe to run on a machine that is already unwell;
  * the shareable version removes what identifies the machine or the person, and
    says on its face that it did.

These tests run the command. A fixture root and a directory of stub commands
stand in for the machine, so what the doctor prints is checked against what the
stub printed - not against a reading of its source.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCTOR = REPO_ROOT / "packages" / "astraos-base" / "root" / "usr" / "bin" / "astraos-doctor"

DESCRIPTION = "the health report only reads, and the shareable one hides what identifies the machine"

STUBS = {
    "uname": "#!/bin/sh\ncase \"$1\" in -r) echo 6.12.113+deb13-amd64 ;; -m) echo x86_64 ;; *) echo Linux ;; esac\n",
    "hostname": "#!/bin/sh\necho astra-workstation\n",
    "id": "#!/bin/sh\necho astra\n",
    "nproc": "#!/bin/sh\necho 4\n",
    "hostname_": "",
    "sysctl": "#!/bin/sh\necho 60\n",
    "df": "#!/bin/sh\necho 'Filesystem      Size  Used Avail Use% Mounted on'\n"
          "echo '/dev/sda1        20G  19G   1.2G  95% /'\n"
          "echo '/dev/sdb1       100G  12G   88G  12% /home'\n",
    "free": "#!/bin/sh\necho '               total        used        free      shared  buff/cache   available'\n"
            "echo 'Mem:        7.7Gi       2.1Gi       1.4Gi       120Mi       4.2Gi       5.3Gi'\n",
    "systemctl": "#!/bin/sh\necho '  NetworkManager.service loaded active running Network Manager'\n",
    "journalctl": "#!/bin/sh\necho 'Oct 21 06:20:01 host kernel: [12345.678] usb 1-1: device descriptor read/64, error -71'\n",
    "ip": "#!/bin/sh\ncase \"$1\" in\n"
          "  -br) echo 'lo    UNKNOWN  127.0.0.1/8 ::1/128' ; echo 'eth0  UP     192.168.1.42/24 fe80::1/64' ;;\n"
          "  route) echo 'default via 192.168.1.1 dev eth0 proto dhcp metric 100' ;;\nesac\n",
    "lsblk": "#!/bin/sh\necho 'NAME        SIZE TYPE MOUNTPOINT'\necho '/dev/sda1   20G disk'\n",
    "lspci": "#!/bin/sh\necho '00:02.0 VGA compatible controller: Intel Corporation HD Graphics 3000 (rev 02)'\n",
}


def _fixture_root(root: Path) -> Path:
    """A root with just enough of a machine to report on."""
    (root / "etc").mkdir(parents=True, exist_ok=True)
    (root / "proc").mkdir(parents=True, exist_ok=True)
    (root / "etc" / "os-release").write_text(
        'NAME="AstraOS"\nPRETTY_NAME="AstraOS 0.2.0 Alpha"\nID=astraos\n', encoding="utf-8"
    )
    (root / "etc" / "astraos-release").write_text(
        'VERSION="0.2.0"\nCODENAME="Nova"\n', encoding="utf-8"
    )
    (root / "etc" / "machine-id").write_text("3f2a9c1b8d7e6f5041322314150607080\n", encoding="utf-8")
    (root / "proc" / "uptime").write_text("129845.22 987654.32\n", encoding="utf-8")
    (root / "proc" / "meminfo").write_text(
        "MemTotal:        8073820 kB\nMemAvailable:    5500000 kB\n"
        "SwapTotal:       2097152 kB\nSwapFree:        2097152 kB\n",
        encoding="utf-8",
    )
    (root / "proc" / "cpuinfo").write_text(
        "processor\t: 0\nmodel name\t: Intel(R) Core(TM) i5-2500S CPU @ 2.70GHz\n",
        encoding="utf-8",
    )
    (root / "proc" / "loadavg").write_text("0.42 0.31 0.28 2/512 12345\n", encoding="utf-8")
    return root


def _stub_bin(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, body in STUBS.items():
        if not body:
            continue
        path = directory / name
        # LF endings: a shell script with CRLF fails with "\r: not found".
        path.write_text(body, encoding="utf-8", newline="\n")
        path.chmod(0o755)
    return directory


def _interpreter() -> list[str]:
    """The shell that runs the doctor.

    On Linux the script runs itself - it has a shebang and the exec bit. On
    Windows there is no shebang support, so it goes through a POSIX shell (Git for
    Windows provides one).
    """
    if os.name != "nt":
        return []
    candidates = [
        Path(r"C:\Program Files\Git\bin\bash.exe"),
        Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return [str(candidate)]
    bash = shutil.which("bash")
    assert bash and "WindowsApps" not in bash, (
        "this test needs a POSIX shell to run the doctor; Git for Windows provides one"
    )
    return [bash]


def _run_doctor(root: Path, stubs: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["ASTRAOS_DOCTOR_ROOT"] = str(root)
    env["ASTRAOS_DOCTOR_BIN"] = str(stubs)
    env["PATH"] = f"{stubs}{os.pathsep}{env.get('PATH', '')}"
    env["USER"] = "astra"
    env["HOSTNAME"] = "astra-workstation"
    return subprocess.run(
        _interpreter() + [str(DOCTOR), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_the_report_says_what_the_machine_says() -> None:
    assert DOCTOR.is_file(), f"the doctor is missing: {DOCTOR}"
    with tempfile.TemporaryDirectory(prefix="astraos-doctor-") as workdir:
        work = Path(workdir)
        root = _fixture_root(work / "root")
        stubs = _stub_bin(work / "bin")

        result = _run_doctor(root, stubs)
        assert result.returncode == 0, f"the doctor failed: {result.stderr}"
        report = result.stdout

        for heading in ("Machine", "Disk", "Memory and swapping", "Services and logs",
                        "Network", "Graphics"):
            assert heading in report, f"the report has no {heading} section"
        assert "6.12.113+deb13-amd64" in report, "the kernel is missing from the report"
        assert "Intel(R) Core(TM) i5-2500S" in report, "the CPU is missing from the report"
        assert "8073820 kB" in report, "the memory is missing from the report"
        assert "36.1 hours" in report, "the uptime is missing from the report"
        assert "/dev/sda1" in report, "the nearly full disk is missing from the report"
        assert "95%" in report, "the disk's use is not shown"
        assert "NetworkManager.service" in report, "the failed unit is missing"
        assert "usb 1-1" in report, "the kernel error is missing"
        assert "192.168.1.42" in report, "the address is missing from the local report"
        assert "astra" in report, "who is running it is missing"


def test_the_shareable_report_hides_what_identifies_the_machine() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-doctor-share-") as workdir:
        work = Path(workdir)
        root = _fixture_root(work / "root")
        stubs = _stub_bin(work / "bin")

        result = _run_doctor(root, stubs, "--share")
        assert result.returncode == 0, f"the doctor failed: {result.stderr}"
        shared = result.stdout

        assert "192.168.1.42" not in shared, "the address survived the redaction"
        assert "192.168.1.1" not in shared, "the router's address survived the redaction"
        assert "astra-workstation" not in shared, "the host name survived the redaction"
        assert "3f2a9c1b8d7e6f5041322314150607080" not in shared, (
            "the machine id survived the redaction"
        )
        assert "<ip>" in shared, "the redaction did not say what it replaced"
        assert "Redacted for sharing" in shared, (
            "the report must say on its face that it was redacted"
        )
        # The facts are still there: a redacted report is less useful, not empty.
        assert "6.12.113+deb13-amd64" in shared, "the redaction took the facts with it"
        assert "/dev/sda1" in shared, "the redaction took the disk list with it"


def test_the_machine_readable_report_is_json() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-doctor-json-") as workdir:
        work = Path(workdir)
        root = _fixture_root(work / "root")
        stubs = _stub_bin(work / "bin")

        result = _run_doctor(root, stubs, "--json")
        assert result.returncode == 0, f"the doctor failed: {result.stderr}"
        try:
            document = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"the JSON report does not parse: {exc}\n{result.stdout}") from exc
        assert document["tool"] == "astraos-doctor"
        assert document["shareable"] is True, "--json implies --share"
        assert "6.12.113+deb13-amd64" in document["report"]
        assert "192.168.1.42" not in document["report"], "--json must be shareable too"


def test_the_doctor_only_reads() -> None:
    source = DOCTOR.read_text(encoding="utf-8")
    for forbidden in (
        "sudo ",
        "rm -",
        "dd if=",
        "apt-get install",
        "systemctl start",
        "systemctl stop",
        "systemctl restart",
        "chmod ",
        "chown ",
        "tee ",
        "> /",
        ">> /",
    ):
        assert forbidden not in source, (
            f"the doctor contains {forbidden!r}: it must only read, so a machine that is "
            "already unwell is not made worse by asking it for help"
        )


def test_the_help_answers_the_question() -> None:
    result = subprocess.run(
        _interpreter() + [str(DOCTOR), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--share" in result.stdout and "--json" in result.stdout
    assert "read" in result.stdout.lower()
