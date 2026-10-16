#!/usr/bin/env bash
# Stage the AstraOS live-build configuration into the build tree.
#
# WHAT THIS DOES
#   1. refuses to run on a host that cannot build (calls validate-environment.sh)
#   2. creates a clean build/live-build working directory
#   3. copies config/live-build/auto/ and config/live-build/config/ into it
#   4. copies the package lists into the live-build config
#   5. renders the system templates (os-release and friends) into the staged asset tree
#   6. builds the AstraOS .deb packages and stages them for live-build
#
# Keeping the repository layout (config/, branding/, desktop/, system/) separate from the
# live-build layout (auto/, config/) means the repository does not have to mirror a
# tool's directory conventions, and the mapping happens in one reviewable place.
#
# Usage: ./scripts/configure-live-build.sh [--force]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=/dev/null
. "${REPO_ROOT}/config/distribution.env"
# shellcheck source=/dev/null
. "${REPO_ROOT}/config/branding.env"

BUILD_DIR="${REPO_ROOT}/${ASTRAOS_BUILD_DIR}"
LOG_DIR="${REPO_ROOT}/${ASTRAOS_LOG_DIR}"

say() { printf '[astraos:configure] %s\n' "$*"; }
die() { printf '[astraos:configure] ERROR: %s\n' "$*" >&2; exit 1; }

FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

export ASTRAOS_REPO_ROOT="$REPO_ROOT"

mkdir -p "$LOG_DIR"

# --- 1. Host sanity -----------------------------------------------------------
say "validating the build environment"
if ! "${SCRIPT_DIR}/validate-environment.sh" --quiet; then
    printf '\n' >&2
    printf '[astraos:configure] The build environment is not usable. Fix the failures above,\n' >&2
    printf '                     or build in CI: .github/workflows/build-iso.yml\n' >&2
    exit 1
fi

# --- 2. Working tree ---------------------------------------------------------
if [ -d "$BUILD_DIR" ] && [ "$FORCE" -eq 0 ]; then
    # Two builds sharing one working directory corrupt each other. Refuse rather than
    # silently reuse a tree that may be half-built (plan §16.4).
    if [ -f "${BUILD_DIR}/.astraos-build-in-progress" ]; then
        die "another build appears to be in progress (${BUILD_DIR}/.astraos-build-in-progress exists).
       Wait for it to finish, or remove that file if the build was killed."
    fi
    say "reusing the existing build tree (pass --force to start clean)"
else
    say "creating a clean build tree at ${BUILD_DIR}"
    rm -rf "$BUILD_DIR"
fi
mkdir -p "$BUILD_DIR"
printf '%s\n' "started $(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${BUILD_DIR}/.astraos-build-in-progress"

# --- 3. live-build configuration ---------------------------------------------
say "staging the live-build configuration"
mkdir -p "${BUILD_DIR}/auto" "${BUILD_DIR}/config"
# Only auto/config is staged. live-build runs auto/build whenever it runs a build,
# so an auto/build that calls `lb build` calls itself: the first build to get that far
# recursed until it died. The logging and the existence check that auto/build used to do
# live in scripts/build-iso.sh, which is the script that invokes lb and can therefore do
# them without re-entering live-build.
cp -a "${REPO_ROOT}/config/live-build/auto/." "${BUILD_DIR}/auto/"
chmod 0755 "${BUILD_DIR}/auto/config"

# Hooks: the .chroot hooks run in the chroot stage, the .binary hooks in the binary
# stage (0800-disk-info.hook.binary brands .disk/info after live-build writes its own
# Debian-named copy).
mkdir -p "${BUILD_DIR}/config/hooks/live"
cp -a "${REPO_ROOT}/config/live-build/config/hooks/live/." "${BUILD_DIR}/config/hooks/live/"
chmod 0755 "${BUILD_DIR}/config/hooks/live/"*.hook.chroot
chmod 0755 "${BUILD_DIR}/config/hooks/live/"*.hook.binary 2>/dev/null || true

# Archives
mkdir -p "${BUILD_DIR}/config/archives"
cp -a "${REPO_ROOT}/config/live-build/config/archives/." "${BUILD_DIR}/config/archives/"

# Static image files (config/live-build/config/includes.chroot): files that ship inside
# the image and belong to no package. The boot self-test lives here: the unit, its
# script and SELF-TEST.txt. Everything user-visible is still delivered by packages.
INCLUDES="${REPO_ROOT}/config/live-build/config/includes.chroot"
if [ -d "$INCLUDES" ]; then
    mkdir -p "${BUILD_DIR}/config/includes.chroot"
    cp -a "${INCLUDES}/." "${BUILD_DIR}/config/includes.chroot/"
    # The executable bit is set here rather than trusted from the working copy: a
    # checkout on a Windows filesystem cannot carry one, and a non-executable
    # ExecStart fails the self-test for a reason that has nothing to do with the image.
    if [ -f "${BUILD_DIR}/config/includes.chroot/usr/local/sbin/astraos-smoke" ]; then
        chmod 0755 "${BUILD_DIR}/config/includes.chroot/usr/local/sbin/astraos-smoke"
    fi
    say "  static image files staged from config/live-build/config/includes.chroot"
fi

# --- 4. Package lists ---------------------------------------------------------
say "staging the package lists"
mkdir -p "${BUILD_DIR}/config/package-lists"
cp -a "${REPO_ROOT}/config/package-lists/." "${BUILD_DIR}/config/package-lists/"

LIST_COUNT="$(ls -1 "${BUILD_DIR}/config/package-lists"/*.list.chroot 2>/dev/null | wc -l)"
[ "$LIST_COUNT" -gt 0 ] || die "no package lists were staged"
say "  ${LIST_COUNT} list(s) staged"

# --- 5. Staged asset tree -----------------------------------------------------
# Everything the hooks install at build time is staged under
# /usr/share/astraos/staged inside the chroot. The hooks are the only place that maps
# staged sources to real system paths, so the mapping stays auditable.
STAGE="${BUILD_DIR}/config/includes.chroot/usr/share/astraos/staged"
say "staging assets into the chroot include tree"
rm -rf "$STAGE"
mkdir -p "$STAGE"

cp -f "${REPO_ROOT}/config/branding.env" "${STAGE}/branding.env"
cp -f "${REPO_ROOT}/config/distribution.env" "${STAGE}/distribution.env"

mkdir -p "${STAGE}/system"
cp -a "${REPO_ROOT}/system/." "${STAGE}/system/"

mkdir -p "${STAGE}/installer"
cp -a "${REPO_ROOT}/installer/." "${STAGE}/installer/"

# Brand assets are installed by the astraos-branding PACKAGE, not by a hook. Only the
# greeter configuration is staged, because lightdm-gtk-greeter owns that path as a
# conffile and no package of ours can ship it.
mkdir -p "${STAGE}/branding/lightdm"
cp -f "${REPO_ROOT}/branding/lightdm/lightdm-gtk-greeter.conf" \
      "${STAGE}/branding/lightdm/lightdm-gtk-greeter.conf"

# Render the templates that the hooks install into /etc. Rendering here (rather than in
# a hook) means a template error is caught before the expensive build stage begins.
render() {
    local src="$1" dst="$2"
    [ -f "$src" ] || die "template not found: $src"
    sed \
        -e "s|@@NAME@@|${ASTRAOS_NAME}|g" \
        -e "s|@@VERSION@@|${ASTRAOS_VERSION}|g" \
        -e "s|@@CODENAME@@|${ASTRAOS_CODENAME}|g" \
        -e "s|@@CODENAME_LOWER@@|$(printf '%s' "${ASTRAOS_CODENAME}" | tr '[:upper:]' '[:lower:]')|g" \
        -e "s|@@STAGE@@|${ASTRAOS_RELEASE_STAGE}|g" \
        -e "s|@@ARCH@@|${ASTRAOS_ARCH}|g" \
        -e "s|@@PRETTY_NAME@@|${ASTRAOS_PRETTY_NAME}|g" \
        -e "s|@@HOMEPAGE@@|${ASTRAOS_HOMEPAGE}|g" \
        -e "s|@@SUPPORT_URL@@|${ASTRAOS_SUPPORT_URL}|g" \
        -e "s|@@BUG_URL@@|${ASTRAOS_BUG_URL}|g" \
        -e "s|@@DOCUMENTATION_URL@@|${ASTRAOS_HOMEPAGE}/docs|g" \
        -e "s|@@BASE_DISTRIBUTION@@|${ASTRAOS_BASE_DISTRIBUTION}|g" \
        -e "s|@@BASE_RELEASE_VERSION@@|${ASTRAOS_BASE_RELEASE_VERSION}|g" \
        -e "s|@@BASE_RELEASE_CODENAME@@|${ASTRAOS_BASE_RELEASE_CODENAME}|g" \
        -e "s|@@BASE_SUITE@@|${ASTRAOS_BASE_SUITE}|g" \
        -e "s|@@DESKTOP@@|${ASTRAOS_DESKTOP}|g" \
        -e "s|@@DISPLAY_SERVER@@|${ASTRAOS_DISPLAY_SERVER}|g" \
        -e "s|@@INIT@@|${ASTRAOS_INIT}|g" \
        -e "s|@@INSTALLER@@|${ASTRAOS_INSTALLER}|g" \
        "$src" > "$dst"
    if grep -q '@@' "$dst"; then
        printf '%s ERROR: unsubstituted placeholder in %s\n' '[astraos:configure]' "$dst" >&2
        grep -n '@@' "$dst" >&2 || true
        exit 1
    fi
}

render "${REPO_ROOT}/system/os-release.in"      "${STAGE}/system/os-release"
render "${REPO_ROOT}/system/issue.in"           "${STAGE}/system/issue"
render "${REPO_ROOT}/system/issue.net.in"       "${STAGE}/system/issue.net"
render "${REPO_ROOT}/system/lsb-release.in"     "${STAGE}/system/lsb-release"
render "${REPO_ROOT}/system/motd"               "${STAGE}/system/motd"
cp -f "${REPO_ROOT}/system/default-hostname"    "${STAGE}/system/default-hostname"

say "  staged $(find "$STAGE" -type f | wc -l) file(s)"

# --- 6. AstraOS packages ------------------------------------------------------
say "building the AstraOS packages"
"${SCRIPT_DIR}/build-packages.sh"

# --- 7. Documentation into the image -----------------------------------------
DOC_DEST="${BUILD_DIR}/config/includes.chroot/usr/share/doc/astraos"
say "staging documentation into the image"
mkdir -p "$DOC_DEST"
stage_doc() {
    # $1 is the file name as it should appear in the image, $2 is its source path.
    # The name and the source differ for README.md, which lives at the repository root
    # rather than in docs/. Resolving it here keeps it from being silently skipped.
    if [ ! -f "$2" ]; then
        say "  WARNING: $2 does not exist; $1 will not be shipped in the image"
        return 0
    fi
    cp -f "$2" "${DOC_DEST}/$1"
}

stage_doc README.md "${REPO_ROOT}/README.md"
for doc in ARCHITECTURE.md BUILDING.md SECURITY.md RECOVERY.md \
           TROUBLESHOOTING.md RELEASE_PROCESS.md KNOWN_LIMITATIONS.md \
           HARDWARE_COMPATIBILITY.md INSTALLATION_VIRTUALBOX.md INSTALLATION_PHYSICAL_PC.md; do
    stage_doc "$doc" "${REPO_ROOT}/docs/${doc}"
done

say "configuration staged in ${BUILD_DIR}"
say "next: ./scripts/build-iso.sh"
