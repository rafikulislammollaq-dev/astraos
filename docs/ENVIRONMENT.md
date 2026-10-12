# AstraOS — Build Environment Report

Measured on the development host on 2026-10-12. Every line below is the output of an
actual command, not an assumption. Re-run `./scripts/validate-environment.sh` to refresh.

## 1. Host facts (measured)

| Item | Value | How it was determined |
|---|---|---|
| Host OS | Windows (MINGW64_NT-10.0-26200), MSYS2/Git Bash 3.6.6 | `uname -a` |
| Shell available to the agent | bash 5.2.37 (Git Bash, MSYS) | `echo $BASH_VERSION` |
| CPU threads | 4 | `nproc` |
| Free disk on `C:` | 242 GB available of 476 GB | `df -h /c` |
| git | 2.53.0.windows.1 | `git --version` |
| python | 3.14.2 (Windows native) | `python --version` |
| node | v24.13.0 | `node --version` |

## 2. Build tooling status

| Tool | Status | Needed for |
|---|---|---|
| `lb` (live-build) | **NOT FOUND** | Building the live filesystem |
| `debootstrap` | **NOT FOUND** | Base rootfs construction |
| `xorriso` | **NOT FOUND** | Generating the bootable ISO |
| `mksquashfs` | **NOT FOUND** | Compressing the live filesystem |
| `mmdebstrap` | **NOT FOUND** | Fast alternative to debootstrap |
| `shellcheck` | **NOT FOUND** | Static shell validation |
| `make` | **NOT FOUND** | `make build`, `make check` shortcuts |
| `docker` | **NOT FOUND** | Containerised build fallback |
| `podman` | **NOT FOUND** | Containerised build fallback |
| `qemu-system-x86_64` | **NOT FOUND** | Automated VM boot tests |
| `VBoxManage` | **NOT FOUND** | VirtualBox acceptance tests |
| `rsync` | **NOT FOUND** | File staging |

None of these exist natively on Windows. They are Linux-only, which is expected: this
host is **not** a valid Debian Live build environment.

## 3. Linux environment availability

`wsl.exe -l -v` reports one registered distribution: **Ubuntu, WSL version 2, state Stopped.**

Attempting to start it:

```
$ wsl.exe -d Ubuntu -- bash -lc 'id'
WSL2 is unable to start since virtualization is not enabled on this machine.
Please ensure the "Virtual Machine Platform" optional component is enabled
and virtualization is turned on in your computer's firmware settings.
Error code: Wsl/Service/CreateInstance/CreateVm/HCS/HCS_E_HYPERV_NOT_INSTALLED
```

**Conclusion: no usable Linux build environment is currently available on this host.**

This is the single blocker on the critical path. It is a host-level configuration issue,
not a repository issue, and it cannot be fixed from inside the repository.

### What is required to unblock a local build

Both steps require Administrator rights and (for the first) a reboot. Neither has been
performed — no elevation was requested or attempted.

```powershell
# 1. Enable the Virtual Machine Platform subsystem (Administrator PowerShell, then reboot)
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
# reboot, then:
wsl.exe --update
```

```powershell
# 2. Install Oracle VirtualBox on the Windows host for the §19 acceptance procedure
winget install --id Oracle.VirtualBox -e
```

After step 1, `scripts/bootstrap-build-environment.sh` can install the Linux build
dependencies inside the Ubuntu distribution (approximately 1.5–2 GB of downloads,
needs roughly 15 GB of free space for the build tree and the ISO).

## 4. Consequences for the plan

Per §3 of the project plan, the build environment priority order is:
Linux host → cloud Linux machine → reproducible Linux CI → other documented environment.

| Priority | Option | Availability on this project |
|---|---|---|
| 1 | Local Linux environment | **BLOCKED** — WSL2 Virtual Machine Platform not installed |
| 2 | Cloud Linux machine | Not provisioned; would require an account and credentials the project does not hold |
| 3 | Reproducible Linux CI | **AVAILABLE** — `.github/workflows/build-iso.yml` runs on `ubuntu-24.04` (GitHub Actions) |
| 4 | Other documented environment | Any Debian/Ubuntu machine via `scripts/bootstrap-build-environment.sh` |

The project is therefore built to be **CI-first**: the ISO is produced by
`.github/workflows/build-iso.yml`, and the same scripts run locally on any Linux machine.

## 5. What was verifiable on this host — and what was not

Honest status, using the vocabulary of §27 of the plan:

| Deliverable | Status |
|---|---|
| Repository structure and configuration | TESTED (files present, validated by `tests/`) |
| Shell script syntax | TESTED via `bash -n` (bash 5.2.37) |
| ShellCheck lint | UNTESTED — `shellcheck` not installed on host |
| Configuration consistency (`tests/static`) | TESTED via `python3 tests/run.py` |
| Branding asset generation | TESTED — PNG/SVG files generated and inspected |
| ISO structural validation | BLOCKED — no ISO exists yet; requires a Linux/CI build |
| Live boot in a VM | BLOCKED — no VirtualBox, no QEMU, WSL2 unavailable |
| Installer run | BLOCKED — depends on an ISO and a disposable VM disk |
| Installed-system boot | BLOCKED — depends on the installer run |

Nothing in the rows marked BLOCKED has been claimed as passing anywhere in this
repository. See `docs/KNOWN_LIMITATIONS.md`.
