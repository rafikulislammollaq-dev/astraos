#!/usr/bin/env bash
# AstraOS build cleanup (plan §16: "Implement an explicit cleanup operation").
#
# Design rules:
#   * Cleaning is EXPLICIT. Nothing in the build process deletes a previous build's output
#     to make itself simpler (plan §16.1).
#   * Nothing here is deleted without saying what and how much.
#   * `dist/` is never touched unless you ask for it by name, because it holds artifacts
#     that took a long time to produce and cannot be regenerated for free.
#   * A dry run is available for every level.
#
# Usage:
#   ./scripts/cleanup-build.sh --dry-run          show what each level would remove
#   ./scripts/cleanup-build.sh                    logs and the live-build working tree
#   ./scripts/cleanup-build.sh --packages         also the built .deb files
#   ./scripts/cleanup-build.sh --all              also generated assets and caches
#   ./scripts/cleanup-build.sh --dist             ALSO dist/: built ISO images
#
# This script deliberately does NOT use `set -e`. A cleanup that aborts on the first
# unreachable path leaves the build tree in a worse state than finishing the levels it
# can and reporting the rest. Instead every removal is counted and any failure is
# reported at the end with a non-zero exit, so a partial cleanup cannot look successful.

set -uo pipefail

ERRORS=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=/dev/null
. "${REPO_ROOT}/config/distribution.env"

BUILD_DIR="${REPO_ROOT}/${ASTRAOS_BUILD_DIR}"
LOG_DIR="${REPO_ROOT}/${ASTRAOS_LOG_DIR}"
DIST_DIR="${REPO_ROOT}/${ASTRAOS_DIST_DIR}"

DRY_RUN=0
DO_PACKAGES=0
DO_ALL=0
DO_DIST=0

for arg in "$@"; do
    case "$arg" in
        --dry-run)  DRY_RUN=1 ;;
        --packages) DO_PACKAGES=1 ;;
        --all)      DO_ALL=1 ;;
        --dist)     DO_DIST=1 ;;
        -h|--help)  sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) printf 'unknown argument: %s\n' "$arg" >&2; exit 2 ;;
    esac
done

say() { printf '[astraos:cleanup] %s\n' "$*"; }

# Report a path's size before removing it, so the user can see what is at stake.
remove() {
    local path="$1"
    if [ ! -e "$path" ]; then
        say "absent:  ${path#${REPO_ROOT}/}"
        return
    fi
    local size
    size="$(du -sh "$path" 2>/dev/null | cut -f1)"
    if [ "$DRY_RUN" -eq 1 ]; then
        say "would remove: ${path#${REPO_ROOT}/} (${size})"
        return
    fi
    if rm -rf "$path"; then
        say "removed: ${path#${REPO_ROOT}/} (${size} freed)"
    else
        printf '[astraos:cleanup] FAILED to remove: %s\n' "$path" >&2
        ERRORS=$((ERRORS + 1))
    fi
}

if [ "$DRY_RUN" -eq 1 ]; then
    say "DRY RUN: nothing will be deleted"
fi

# --- Level 1: always safe ----------------------------------------------------
say "--- level 1: logs and the live-build working tree ---"
remove "$LOG_DIR"
remove "${BUILD_DIR}/live-build"
say "kept: ${ASTRAOS_DIST_DIR}/ and the package build output"

# --- Level 2: the built packages ---------------------------------------------
if [ "$DO_PACKAGES" -eq 1 ] || [ "$DO_ALL" -eq 1 ]; then
    say "--- level 2: built packages ---"
    remove "${BUILD_DIR}/packages"
    remove "${BUILD_DIR}/package-stage"
else
    say "level 2 (built packages) not requested; pass --packages"
fi

# --- Level 3: caches and generated assets ------------------------------------
if [ "$DO_ALL" -eq 1 ]; then
    say "--- level 3: caches and generated assets ---"
    remove "${BUILD_DIR}/cache"
    # The generated assets are build INPUTS. Removing them means the next build must
    # regenerate them, which needs Python 3. Say so rather than doing it silently.
    say "note: branding/generated/ holds build inputs; regenerate with:"
    say "      python3 branding/tools/render_assets.py"
else
    say "level 3 (caches and generated assets) not requested; pass --all"
fi

# --- Level 4: release artifacts ----------------------------------------------
if [ "$DO_DIST" -eq 1 ]; then
    say "--- level 4: release artifacts ---"
    # find rather than ls: it exits 0 when nothing matches, so this does not set a
    # misleading status when dist/ is empty.
    ISO_COUNT="$(find "$DIST_DIR" -maxdepth 1 -name '*.iso' 2>/dev/null | wc -l)"
    if [ "$ISO_COUNT" -gt 0 ]; then
        say "WARNING: this deletes ${ISO_COUNT} built ISO image(s), which take a long time"
        say "         and several GB of downloads to rebuild."
    fi
    remove "${DIST_DIR}"
    if [ "$DRY_RUN" -eq 0 ]; then
        mkdir -p "$DIST_DIR"
        printf '# AstraOS release output directory.\n' > "${DIST_DIR}/.gitkeep"
    fi
else
    say "level 4 (dist/ and any built ISO) not requested; pass --dist"
fi

# --- Leftovers ---------------------------------------------------------------
say "---"
if [ -f "${BUILD_DIR}/live-build/.astraos-build-in-progress" ] && [ "$DRY_RUN" -eq 0 ]; then
    say "removing a stale build-in-progress marker"
    rm -f "${BUILD_DIR}/live-build/.astraos-build-in-progress"
fi

if [ "$DRY_RUN" -eq 0 ]; then
    REMAINING="$(du -sh "$BUILD_DIR" 2>/dev/null | cut -f1)"
    say "build/ still occupies ${REMAINING}"
    say "no source file, no documentation and no branding source was touched"
fi

# Report the outcome honestly: a partial cleanup must not look like a successful one.
if [ "$ERRORS" -gt 0 ]; then
    printf '\n[astraos:cleanup] %s path(s) could not be removed. Check permissions and re-run.\n' \
        "$ERRORS" >&2
    exit 1
fi

exit 0
