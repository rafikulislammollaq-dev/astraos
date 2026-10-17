#!/usr/bin/env bash
# Build the AstraOS live ISO. This is the project's main build command (plan §16).
#
# Stages (plan §16.1):
#   1. validate the host environment
#   2. configure live-build and build the AstraOS packages
#   3. run live-build
#   4. validate the resulting image structurally
#   5. generate checksums and the build manifest
#
# Every stage is fatal on failure. The script never reports success unless an ISO exists
# and passes validation (plan §16.2, §28 Rule 4).
#
# Usage:
#   ./scripts/build-iso.sh                 full build
#   ./scripts/build-iso.sh --skip-validate skip the build-host check (the build may then
#                                          fail later in live-build, where the cause is
#                                          much harder to see; use it only when the host
#                                          check itself is the thing that is wrong)
#   ./scripts/build-iso.sh --no-cache      do not reuse the live-build download cache

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=/dev/null
. "${REPO_ROOT}/config/distribution.env"
. "${REPO_ROOT}/VERSION"

BUILD_DIR="${REPO_ROOT}/${ASTRAOS_BUILD_DIR}"
LOG_DIR="${REPO_ROOT}/${ASTRAOS_LOG_DIR}"
DIST_DIR="${REPO_ROOT}/${ASTRAOS_DIST_DIR}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BUILD_LOG="${LOG_DIR}/build-${STAMP}.log"

SKIP_VALIDATE=0
for arg in "$@"; do
    case "$arg" in
        --skip-validate) SKIP_VALIDATE=1 ;;
        --no-cache)      export ASTRAOS_NO_CACHE=1 ;;
        -h|--help)       sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) printf 'unknown argument: %s\n' "$arg" >&2; exit 2 ;;
    esac
done

say()  { printf '[astraos:build] %s\n' "$*"; }
fail() { printf '[astraos:build] FAILED: %s\n' "$*" >&2; exit 1; }

# --- Privileges ---------------------------------------------------------------
# live-build mounts filesystems, runs debootstrap and chroots, so it needs root. Only the
# live-build commands are elevated. Everything else in this script — host validation,
# package building, checksums, the manifest — runs as the invoking user, so the files they
# write belong to that user and the privileged surface is one command instead of all of it.
LB_SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        # -E preserves ASTRAOS_REPO_ROOT and SOURCE_DATE_EPOCH, which auto/config reads out
        # of the environment to find the repository and to keep the build reproducible.
        LB_SUDO="$(command -v sudo) -E"
    else
        fail "live-build needs root privileges and sudo is not installed. Run this script as root, or install sudo (see docs/BUILDING.md)."
    fi
fi

# $LB_SUDO is deliberately unquoted: it is either empty or a two-word command prefix.
run_privileged() {
    # shellcheck disable=SC2086
    $LB_SUDO "$@"
}

mkdir -p "$LOG_DIR" "$DIST_DIR"
export ASTRAOS_REPO_ROOT="$REPO_ROOT"

# Tee everything into a log while preserving the exit status of the stage that fails.
run_stage() {
    local name="$1"
    shift
    say "--- stage: ${name} ---"
    local status=0
    ( "$@" ) 2>&1 | tee -a "$BUILD_LOG" || status=$?
    if [ "$status" -ne 0 ]; then
        fail "stage '${name}' exited with status ${status}. Full log: ${BUILD_LOG}"
    fi
}

printf 'AstraOS %s %s build\n' "$ASTRAOS_VERSION" "$ASTRAOS_RELEASE_STAGE"
printf '  base      : %s %s (%s)\n' "$ASTRAOS_BASE_DISTRIBUTION" "$ASTRAOS_BASE_RELEASE_VERSION" "$ASTRAOS_BASE_SUITE"
printf '  arch      : %s\n' "$ASTRAOS_ARCH"
printf '  started   : %s\n' "$STAMP"
printf '  log       : %s\n\n' "$BUILD_LOG"

{
    printf 'AstraOS build log\n'
    printf 'version=%s\n' "$ASTRAOS_VERSION"
    printf 'stage=%s\n' "$ASTRAOS_RELEASE_STAGE"
    printf 'arch=%s\n' "$ASTRAOS_ARCH"
    printf 'base=%s %s %s\n' "$ASTRAOS_BASE_DISTRIBUTION" "$ASTRAOS_BASE_RELEASE_VERSION" "$ASTRAOS_BASE_SUITE"
    printf 'started_utc=%s\n' "$STAMP"
    printf 'host=%s\n' "$(uname -a)"
} > "$BUILD_LOG"

# ---------------------------------------------------------------------------
# 1. Environment
# ---------------------------------------------------------------------------
[ "$SKIP_VALIDATE" -eq 1 ] || run_stage "validate environment" "${SCRIPT_DIR}/validate-environment.sh"

# ---------------------------------------------------------------------------
# 2. Configuration and packages
# ---------------------------------------------------------------------------
# One build per working tree. The guard lives here rather than in
# configure-live-build.sh because this script is the only entry point (the Makefile and
# CI both call it) and it is the process that lives for the whole build.
#
# It used to live in configure-live-build.sh, inside a branch that `--force` skipped -
# and the call below passed `--force` unconditionally, so from the only path that
# exists the check was dead code. Two builds then shared one tree: the second deleted
# the first's chroot mid-debootstrap, and the first failed with a missing-directory
# error that pointed at nothing, or continued against a half-deleted tree.
#
# The marker records the PID, so a marker left behind by a killed build is stale rather
# than a lock: only a build whose process is still running blocks a new one. Refusing
# on the file's existence alone would mean a human had to delete it after every crash.
IN_PROGRESS_MARKER="${BUILD_DIR}/.astraos-build-in-progress"
if [ -f "$IN_PROGRESS_MARKER" ]; then
    OTHER_PID="$(awk -F= '$1 == "pid" { print $2; exit }' "$IN_PROGRESS_MARKER" 2>/dev/null || true)"
    case "$OTHER_PID" in
        ''|*[!0-9]*) OTHER_PID="" ;;
    esac
    if [ -n "$OTHER_PID" ] && kill -0 "$OTHER_PID" 2>/dev/null; then
        fail "another build is running in ${BUILD_DIR} (pid ${OTHER_PID}).
       Two builds sharing one working directory corrupt each other, so this one stops
       before touching the tree. Wait for that build to finish, or stop it and re-run."
    fi
    say "clearing a stale in-progress marker (pid ${OTHER_PID:-unknown} is not running)"
    rm -f "$IN_PROGRESS_MARKER"
fi
mkdir -p "$BUILD_DIR"
{
    printf 'started=%s\n' "$STAMP"
    printf 'pid=%s\n'     "$$"
    printf 'log=%s\n'     "$BUILD_LOG"
} > "$IN_PROGRESS_MARKER"
# Cleared on every exit path. This is tidiness rather than the lock: if this script dies
# without running the trap, the next run sees a dead PID and clears the marker itself.
trap 'rm -f "$IN_PROGRESS_MARKER" 2>/dev/null || true' EXIT INT TERM

run_stage "configure live-build" "${SCRIPT_DIR}/configure-live-build.sh" --force

# ---------------------------------------------------------------------------
# 3. Build
# ---------------------------------------------------------------------------
say "--- stage: live-build ---"
say "this stage downloads and installs the full package set; expect several GB and"
say "tens of minutes. It will request elevated privileges for mounting and debootstrap."

cd "$BUILD_DIR"
if [ "${ASTRAOS_NO_CACHE:-0}" = "1" ]; then
    say "clearing live-build caches as requested"
    run_privileged lb clean --purge >/dev/null 2>&1 || true
fi

LB_STATUS=0
# auto/config is ours and `lb config` runs it. There is deliberately no auto/build: lb runs
# that when it runs a build, so an auto/build containing `lb build` calls itself. This
# script is the wrapper instead — it owns the log and the status, which is where they
# belong, because it is the process that started lb.
#
# tee runs unprivileged so the log file belongs to the invoking user, and `pipefail` is
# what makes the pipeline report lb's failure rather than tee's success (plan §16.2).
run_privileged lb build 2>&1 | tee -a "$BUILD_LOG" || LB_STATUS=$?
if [ "$LB_STATUS" -ne 0 ]; then
    fail "live-build exited with status ${LB_STATUS}. Check ${BUILD_LOG} and the live-build log in build/live-build/"
fi

# ---------------------------------------------------------------------------
# 4. Locate and validate the image
# ---------------------------------------------------------------------------
ISO_NAME="$(cat "${BUILD_DIR}/.last-iso-name" 2>/dev/null || true)"
if [ -z "$ISO_NAME" ]; then
    # live-build does not record the output name anywhere convenient, so find it. The
    # newest match wins, because a reused build tree can hold an older image.
    ISO_NAME="$(find "$BUILD_DIR" -maxdepth 1 -name '*.iso' -printf '%T@ %f\n' 2>/dev/null \
                | sort -rn | head -n1 | cut -d' ' -f2-)"
fi
[ -n "$ISO_NAME" ] || fail "live-build reported success but no ISO was found in ${BUILD_DIR}"

ISO_PATH="${BUILD_DIR}/${ISO_NAME}"
[ -f "$ISO_PATH" ] || fail "expected ISO not found: ${ISO_PATH}"

mkdir -p "$DIST_DIR"
FINAL_NAME="astraos-${ASTRAOS_VERSION}-${ASTRAOS_RELEASE_STAGE,,}-${ASTRAOS_ARCH}.iso"
cp -f "$ISO_PATH" "${DIST_DIR}/${FINAL_NAME}"
say "image copied to ${DIST_DIR}/${FINAL_NAME}"

run_stage "validate image" "${SCRIPT_DIR}/validate-iso.sh" "${DIST_DIR}/${FINAL_NAME}"

# ---------------------------------------------------------------------------
# 5. Checksums and manifest
# ---------------------------------------------------------------------------
run_stage "generate checksums" "${SCRIPT_DIR}/generate-checksums.sh" "${DIST_DIR}/${FINAL_NAME}"
run_stage "generate manifest" "${SCRIPT_DIR}/generate-manifest.sh" "${DIST_DIR}/${FINAL_NAME}"

# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
rm -f "${BUILD_DIR}/.astraos-build-in-progress" 2>/dev/null || true

ISO_SIZE="$(wc -c < "${DIST_DIR}/${FINAL_NAME}")"
SHA256="$(sha256sum "${DIST_DIR}/${FINAL_NAME}" | cut -d' ' -f1)"

printf '\n'
printf '================================================================\n'
printf ' AstraOS image built\n'
printf '================================================================\n'
printf ' image      : %s\n' "${DIST_DIR}/${FINAL_NAME}"
printf ' size       : %s bytes\n' "$ISO_SIZE"
printf ' sha256     : %s\n' "$SHA256"
printf ' checksums  : %s/%s.sha256\n' "$ASTRAOS_DIST_DIR" "$FINAL_NAME"
printf ' manifest   : %s/%s.manifest\n' "$ASTRAOS_DIST_DIR" "$FINAL_NAME"
printf ' log        : %s\n' "$BUILD_LOG"
printf '\n'
printf ' This image has been validated STRUCTURALLY only. It has NOT been booted.\n'
printf ' Boot it in a virtual machine before considering it usable:\n'
printf '   docs/INSTALLATION_VIRTUALBOX.md\n'
printf '================================================================\n'
