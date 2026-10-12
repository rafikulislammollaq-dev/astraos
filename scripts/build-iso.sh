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
#   ./scripts/build-iso.sh --skip-validate reuse an existing ISO, validate only
#   ./scripts/build-iso.sh --no-cache      do not reuse live-build caches

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
    lb clean --purge >/dev/null 2>&1 || true
fi

LB_STATUS=0
# `lb build` calls auto/config and auto/build, both of which are ours.
lb build 2>&1 | tee -a "$BUILD_LOG" || LB_STATUS=$?
if [ "$LB_STATUS" -ne 0 ]; then
    fail "live-build exited with status ${LB_STATUS}. Check ${BUILD_LOG} and the live-build log in build/live-build/"
fi

# ---------------------------------------------------------------------------
# 4. Locate and validate the image
# ---------------------------------------------------------------------------
ISO_NAME="$(cat "${BUILD_DIR}/.last-iso-name" 2>/dev/null || true)"
if [ -z "$ISO_NAME" ]; then
    # auto/build should have written this. Fall back to a search rather than assuming.
    ISO_NAME="$(find "$BUILD_DIR" -maxdepth 1 -name '*.iso' -printf '%f\n' 2>/dev/null | head -n1)"
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
