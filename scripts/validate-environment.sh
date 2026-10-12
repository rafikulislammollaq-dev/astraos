#!/usr/bin/env bash
# AstraOS build environment validation.
#
# Plan §3 and §16.1 step 1. This script decides whether the current host can build an
# AstraOS image. It reports every finding and exits non-zero when the host cannot, so a
# caller can never proceed on a machine that is going to fail 20 minutes later.
#
# It performs NO privileged operations and changes nothing. Reading is all it does.
#
# Usage:
#   ./scripts/validate-environment.sh            full check
#   ./scripts/validate-environment.sh --quiet    summary only

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=/dev/null
. "${REPO_ROOT}/config/distribution.env"
. "${REPO_ROOT}/VERSION"

QUIET=0
[ "${1:-}" = "--quiet" ] && QUIET=1

FAIL=0
WARN=0
PASS=0

say()     { [ "$QUIET" -eq 1 ] || printf '%s\n' "$*"; }
ok()      { PASS=$((PASS + 1)); printf '  [ ok ]   %s\n' "$*"; }
warn()    { WARN=$((WARN + 1)); printf '  [warn]   %s\n' "$*"; }
bad()     { FAIL=$((FAIL + 1)); printf '  [FAIL]   %s\n' "$*"; }
# NOTE: this helper is not called "head" on purpose. Shadowing the head(1) command
# would break the "... | head -n1" calls used further down this script.
section() { [ "$QUIET" -eq 1 ] || printf '\n== %s ==\n' "$*"; }

printf 'AstraOS build environment validation\n'
printf 'Repository : %s\n' "$REPO_ROOT"

# ---------------------------------------------------------------------------
section "Host operating system"
# ---------------------------------------------------------------------------
if [ "$(uname -s)" = "Linux" ]; then
    ok "host is Linux"
else
    # Do not attempt to run Linux-only build steps on Windows or macOS. Plan §3 says
    # explicitly not to do this; report it and stop.
    bad "host is $(uname -s), not Linux. Debian Live cannot be built here."
    printf '\n'
    printf '  AstraOS image building requires a Linux host. See docs/BUILDING.md for the\n'
    printf '  supported options, and docs/ENVIRONMENT.md for what was measured on this\n'
    printf '  machine and exactly what is missing.\n'
fi

if [ -r /etc/os-release ]; then
    # shellcheck source=/dev/null
    . /etc/os-release
    say "  distribution: ${PRETTY_NAME:-unknown}"
    case "${ID:-unknown}" in
        debian|ubuntu|linuxmint|pop) ok "a Debian-derived host, which live-build expects" ;;
        *) warn "host distribution ${ID:-unknown} is not Debian-derived; live-build may still work" ;;
    esac
fi

# ---------------------------------------------------------------------------
section "Architecture"
# ---------------------------------------------------------------------------
HOST_ARCH="$(uname -m)"
say "  host architecture: ${HOST_ARCH}"
case "$HOST_ARCH" in
    x86_64|amd64) ok "host architecture matches the target (${ASTRAOS_ARCH})" ;;
    aarch64|arm64)
        bad "host is ${HOST_ARCH} but AstraOS 0.1.0 targets ${ASTRAOS_ARCH}"
        printf '           Cross-building an amd64 image from arm64 needs binfmt_misc and\n'
        printf '           qemu-user-static; that path is not implemented or tested.\n'
        ;;
    *) warn "host architecture ${HOST_ARCH} is untested for an ${ASTRAOS_ARCH} build" ;;
esac

# ---------------------------------------------------------------------------
section "Required build tools"
# ---------------------------------------------------------------------------
# Split into REQUIRED (build cannot proceed) and OPTIONAL (feature or validation lost).
REQUIRED_TOOLS="debootstrap lb xorriso mksquashfs dpkg-deb dpkg apt-get"
OPTIONAL_TOOLS="shellcheck python3 git rsync mmdebstrap xz unsquashfs file"

for tool in $REQUIRED_TOOLS; do
    if command -v "$tool" >/dev/null 2>&1; then
        ok "required tool present: ${tool}"
    else
        bad "required tool MISSING: ${tool}"
    fi
done

for tool in $OPTIONAL_TOOLS; do
    if command -v "$tool" >/dev/null 2>&1; then
        ok "optional tool present: ${tool}"
    else
        warn "optional tool missing: ${tool}"
    fi
done

if command -v lb >/dev/null 2>&1; then
    say "  live-build version: $(lb --version 2>/dev/null | head -n1)"
    # AstraOS relies on a hybrid BIOS+UEFI image. Confirm the option exists rather than
    # discovering it halfway through configuration (auto/config probes the same thing).
    if lb config --help 2>&1 | grep -q -- '--bootloaders'; then
        ok "live-build supports --bootloaders (hybrid BIOS+UEFI)"
    else
        warn "live-build has no --bootloaders; the ISO will be UEFI-only"
    fi
fi

# ---------------------------------------------------------------------------
section "Privileges"
# ---------------------------------------------------------------------------
# live-build needs root for debootstrap and for mounting. The scripts use sudo rather
# than requiring the whole session to run as root, so check that sudo is usable.
if [ "$(id -u)" -eq 0 ]; then
    warn "running as root; the scripts prefer to elevate per command via sudo"
elif command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    ok "sudo is available without a password (typical in CI)"
elif command -v sudo >/dev/null 2>&1; then
    warn "sudo is present but needs a password; the build will prompt"
else
    bad "neither root nor sudo is available; the build cannot mount or debootstrap"
fi

# ---------------------------------------------------------------------------
section "Disk space"
# ---------------------------------------------------------------------------
AVAIL_MIB="$(df -Pm "$REPO_ROOT" 2>/dev/null | awk 'NR==2{print $4}')"
if [ -n "${AVAIL_MIB:-}" ]; then
    say "  available under ${REPO_ROOT}: ${AVAIL_MIB} MiB"
    if [ "$AVAIL_MIB" -lt "${ASTRAOS_MIN_FREE_SPACE_MIB:-15000}" ]; then
        bad "less than ${ASTRAOS_MIN_FREE_SPACE_MIB} MiB free; a build tree plus the ISO needs more"
    else
        ok "enough free space (at least ${ASTRAOS_MIN_FREE_SPACE_MIB} MiB)"
    fi
else
    warn "could not determine free disk space"
fi

# ---------------------------------------------------------------------------
section "Network and package repositories"
# ---------------------------------------------------------------------------
if command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1; then
    fetch() {
        if command -v curl >/dev/null 2>&1; then
            curl -fsS --max-time 20 -o /dev/null "$1"
        else
            wget -q --timeout=20 -O /dev/null "$1"
        fi
    }
    if fetch "${ASTRAOS_DEBIAN_MIRROR}/dists/${ASTRAOS_BASE_SUITE}/Release"; then
        ok "main mirror reachable: ${ASTRAOS_DEBIAN_MIRROR} (${ASTRAOS_BASE_SUITE})"
    else
        bad "cannot reach ${ASTRAOS_DEBIAN_MIRROR} for suite ${ASTRAOS_BASE_SUITE}"
    fi
    if fetch "${ASTRAOS_DEBIAN_SECURITY_MIRROR}/dists/${ASTRAOS_SECURITY_SUITE}/Release"; then
        ok "security mirror reachable: ${ASTRAOS_SECURITY_SUITE}"
    else
        warn "cannot reach the security mirror; the image would ship without security updates"
    fi
else
    warn "curl and wget are both missing; repository reachability was not checked"
fi

# ---------------------------------------------------------------------------
section "Repository configuration"
# ---------------------------------------------------------------------------
for file in config/distribution.env config/branding.env config/live-build/auto/config VERSION; do
    if [ -f "${REPO_ROOT}/${file}" ]; then
        ok "present: ${file}"
    else
        bad "MISSING: ${file}"
    fi
done

LIST_COUNT="$(ls -1 "${REPO_ROOT}/config/package-lists"/*.list.chroot 2>/dev/null | wc -l)"
if [ "$LIST_COUNT" -gt 0 ]; then
    ok "${LIST_COUNT} package list(s) found"
else
    bad "no package lists found in config/package-lists"
fi

if [ -f "${REPO_ROOT}/branding/generated/astraos-wallpaper-dark-1920x1080.png" ]; then
    ok "generated branding assets are present"
else
    warn "generated branding assets are missing; run: python3 branding/tools/render_assets.py"
fi

# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
printf '\n%s\n' "-----------------------------------------------"
printf 'passed: %s   warnings: %s   failures: %s\n' "$PASS" "$WARN" "$FAIL"

if [ "$FAIL" -gt 0 ]; then
    printf '\nRESULT: this host CANNOT build an AstraOS image.\n'
    printf 'See docs/BUILDING.md. The ISO build can also run in CI:\n'
    printf '  .github/workflows/build-iso.yml\n'
    exit 1
fi

printf '\nRESULT: this host can build an AstraOS image.\n'
printf 'Next: ./scripts/build-iso.sh\n'
exit 0
