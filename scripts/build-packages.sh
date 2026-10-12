#!/usr/bin/env bash
# Build the AstraOS .deb packages.
#
# Why not dpkg-buildpackage?
#   The four AstraOS packages are simple file-installation packages. Using the full
#   Debian source-package machinery would add debhelper, fakeroot, a signed source
#   tarball and a build-dependency chain, none of which buys anything for this release.
#   dpkg-deb is used directly, and the constructed control file is validated before
#   the package is produced. plan §2.3 forbids inventing substitutes for essential
#   system components; this is packaging our own content, not replacing dpkg.
#
# Reproducibility (plan §2.4):
#   SOURCE_DATE_EPOCH is derived from the latest commit when git is available, so two
#   builds of the same content produce identical .deb files apart from nothing.
#
# Output:
#   build/packages/*.deb                            the packages
#   build/live-build/config/packages.chroot/*.deb   staged for live-build to install
#
# Usage: ./scripts/build-packages.sh [--clean]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=/dev/null
. "${REPO_ROOT}/config/distribution.env"
# shellcheck source=/dev/null
. "${REPO_ROOT}/config/branding.env"
. "${REPO_ROOT}/VERSION"

PACKAGES_DIR="${REPO_ROOT}/packages"
OUT_DIR="${REPO_ROOT}/${ASTRAOS_BUILD_DIR}/packages"
STAGE_ROOT="${REPO_ROOT}/${ASTRAOS_BUILD_DIR}/package-stage"
LIVE_PACKAGES_DIR="${REPO_ROOT}/${ASTRAOS_BUILD_DIR}/live-build/config/packages.chroot"
LOG_DIR="${REPO_ROOT}/${ASTRAOS_LOG_DIR}"

say() { printf '[astraos:packages] %s\n' "$*"; }
die() { printf '[astraos:packages] ERROR: %s\n' "$*" >&2; exit 1; }

command -v dpkg-deb >/dev/null 2>&1 || die "dpkg-deb is not installed. Run scripts/bootstrap-build-environment.sh"
command -v dpkg >/dev/null 2>&1 || die "dpkg is not installed."

CLEAN=0
for arg in "$@"; do
    case "$arg" in
        --clean) CLEAN=1 ;;
        -h|--help) sed -n '2,25p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) die "unknown argument: $arg" ;;
    esac
done

if [ "$CLEAN" -eq 1 ]; then
    say "cleaning previous package build output"
    rm -rf "$OUT_DIR" "$STAGE_ROOT"
fi

mkdir -p "$OUT_DIR" "$STAGE_ROOT" "$LOG_DIR"

# Deterministic timestamps: use the last commit time when the repository is available.
if command -v git >/dev/null 2>&1 && git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    SOURCE_DATE_EPOCH="$(git -C "$REPO_ROOT" log -1 --format=%ct 2>/dev/null || date -u +%s)"
else
    SOURCE_DATE_EPOCH="$(date -u +%s)"
fi
export SOURCE_DATE_EPOCH
say "SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}"

PACKAGE_VERSION="${ASTRAOS_VERSION}"

CODENAME_LOWER="$(printf '%s' "${ASTRAOS_CODENAME}" | tr '[:upper:]' '[:lower:]')"
RELEASE_TYPE="$(printf '%s' "${ASTRAOS_RELEASE_STAGE}" | tr '[:upper:]' '[:lower:]')"

# ---------------------------------------------------------------------------
# substitute SRC DST
#
# Renders @@PLACEHOLDER@@ tokens from the pinned configuration. This is the single
# templating path: package control files and the files installed into /etc all come
# from version-controlled templates instead of hand-maintained duplicates (plan §2.4).
# ---------------------------------------------------------------------------
substitute() {
    local src="$1" dst="$2"
    [ -f "$src" ] || die "template not found: $src"
    sed \
        -e "s|@@PACKAGE@@|${1##*/}|g" \
        -e "s|@@VERSION@@|${PACKAGE_VERSION}|g" \
        -e "s|@@ARCH@@|${ASTRAOS_ARCH_DEB}|g" \
        -e "s|@@CODENAME@@|${ASTRAOS_CODENAME}|g" \
        -e "s|@@CODENAME_LOWER@@|${CODENAME_LOWER}|g" \
        -e "s|@@STAGE@@|${ASTRAOS_RELEASE_STAGE}|g" \
        -e "s|@@RELEASE_TYPE@@|${RELEASE_TYPE}|g" \
        -e "s|@@NAME@@|${ASTRAOS_NAME}|g" \
        -e "s|@@VENDOR@@|${BRAND_VENDOR}|g" \
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

    # Refuse to ship an unsubstituted placeholder: a literal @@VERSION@@ in a shipped
    # file is worse than a build failure.
    if grep -q '@@' "$dst"; then
        printf '%s ERROR: unsubstituted placeholder while rendering %s:\n' '[astraos:packages]' "$src" >&2
        grep -n '@@' "$dst" >&2 || true
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# render_control SRC DST PACKAGE_NAME
# ---------------------------------------------------------------------------
render_control() {
    local src="$1" dst="$2" name="$3"
    [ -f "$src" ] || die "control template not found: $src"
    # The package name comes from the directory, so @@PACKAGE@@ is replaced first.
    sed "s|@@PACKAGE@@|${name}|g" "$src" > "${src}.named"
    substitute "${src}.named" "$dst"
    rm -f "${src}.named"
}

# ---------------------------------------------------------------------------
# finish_package NAME
#
# Completes the staged DEBIAN directory and produces the .deb.
# ---------------------------------------------------------------------------
finish_package() {
    local name="$1" stage="$2"
    local debian="${stage}/DEBIAN"

    # Maintainer scripts must be executable inside the control archive.
    local script
    for script in postinst preinst postrm prerm; do
        if [ -f "${debian}/${script}" ]; then
            chmod 0755 "${debian}/${script}"
        fi
    done

    # conffiles: one absolute path per line. Sorted for reproducible output.
    if [ -f "${debian}/conffiles" ]; then
        sort -u -o "${debian}/conffiles" "${debian}/conffiles"
    fi

    # Installed-Size (KiB), as dpkg-deb expects it in control.
    local installed_size
    installed_size="$(du -sk --exclude=./DEBIAN "${stage}" 2>/dev/null | cut -f1 || echo 0)"
    if ! grep -q '^Installed-Size:' "${debian}/control"; then
        # Insert after the Version field to keep the conventional field order.
        sed -i "/^Version:/a Installed-Size: ${installed_size}" "${debian}/control"
    fi

    # md5sums for every regular file we install.
    (
        cd "$stage"
        find . -type f ! -path './DEBIAN/*' -printf '%P\0' 2>/dev/null \
            | sort -z \
            | xargs -0 -r md5sum > DEBIAN/md5sums
    )

    # Validate the control file before building.
    if command -v dpkg-deb >/dev/null 2>&1; then
        dpkg-deb --info "${stage}" >/dev/null 2>&1 \
            || die "dpkg-deb rejected the control directory for ${name}"
    fi

    local out="${OUT_DIR}/${name}_${PACKAGE_VERSION}_${ASTRAOS_ARCH_DEB}.deb"
    # --root-owner-group makes the archive reproducible regardless of who builds it.
    dpkg-deb --build --root-owner-group "${stage}" "$out" >/dev/null \
        || die "dpkg-deb --build failed for ${name}"

    local size
    size="$(stat -c %s "$out" 2>/dev/null || wc -c < "$out")"
    say "built ${name} -> $(basename "$out") (${size} bytes)"
    printf '%s\n' "$out"
}

# ---------------------------------------------------------------------------
# stage_package NAME
# ---------------------------------------------------------------------------
stage_package() {
    local name="$1"
    local src="${PACKAGES_DIR}/${name}"
    local stage="${STAGE_ROOT}/${name}"

    [ -d "$src" ] || die "package source not found: ${src}"
    rm -rf "$stage"
    mkdir -p "${stage}/DEBIAN"

    render_control "${src}/control.in" "${stage}/DEBIAN/control" "$name"

    # Plain file tree.
    if [ -d "${src}/root" ]; then
        cp -a "${src}/root/." "$stage/"
    fi

    # conffiles list, one path per line, comments allowed.
    if [ -f "${src}/conffiles" ]; then
        grep -v '^[[:space:]]*#' "${src}/conffiles" \
            | sed '/^[[:space:]]*$/d' > "${stage}/DEBIAN/conffiles"
    fi

    # Maintainer scripts.
    local script
    for script in postinst preinst postrm prerm; do
        if [ -f "${src}/${script}" ]; then
            cp -f "${src}/${script}" "${stage}/DEBIAN/${script}"
        fi
    done

    printf '%s' "$stage"
}

# ---------------------------------------------------------------------------
# Package content assembly
#
# The mapping from repository source trees to installed paths lives here, in one
# place, so "what ends up where" is auditable without reading four build scripts.
# ---------------------------------------------------------------------------

say "assembling astraos-base"
BASE_STAGE="$(stage_package astraos-base)"

# system/ holds the version-controlled templates that become files in /etc. Rendering
# them here keeps one source of truth for the release identity (plan §2.4).
mkdir -p "${BASE_STAGE}/etc/sysctl.d" "${BASE_STAGE}/usr/share/doc/astraos-base"
substitute "${REPO_ROOT}/system/astraos-release.in" "${BASE_STAGE}/etc/astraos-release"
cp -f "${REPO_ROOT}/system/sysctl/60-astraos.conf" "${BASE_STAGE}/etc/sysctl.d/60-astraos.conf"
cp -f "${REPO_ROOT}/LICENSE" "${BASE_STAGE}/usr/share/doc/astraos-base/copyright"
chmod 0755 "${BASE_STAGE}/usr/bin/astraos-info"

say "assembling astraos-system-tools"
TOOLS_STAGE="$(stage_package astraos-system-tools)"

say "assembling astraos-branding"
BRAND_STAGE="$(stage_package astraos-branding)"
require_dir() { [ -e "$1" ] || die "branding asset missing: $1 (run branding/tools/render_assets.py)"; }
require_dir "${REPO_ROOT}/branding/generated"
require_dir "${REPO_ROOT}/branding/logos"

# Wallpapers and splash art -> /usr/share/astraos/wallpapers
mkdir -p "${BRAND_STAGE}/usr/share/astraos/wallpapers"
cp -a "${REPO_ROOT}/branding/generated/"*.png "${BRAND_STAGE}/usr/share/astraos/wallpapers/"

# Vector marks -> /usr/share/astraos/logos
mkdir -p "${BRAND_STAGE}/usr/share/astraos/logos"
cp -a "${REPO_ROOT}/branding/logos/." "${BRAND_STAGE}/usr/share/astraos/logos/"

# Icon theme -> /usr/share/icons/AstraOS
mkdir -p "${BRAND_STAGE}/usr/share/icons/AstraOS"
cp -a "${REPO_ROOT}/branding/icons/." "${BRAND_STAGE}/usr/share/icons/AstraOS/"

# Plymouth theme -> /usr/share/plymouth/themes/astraos
# The theme script refers to fixed filenames, so the generated art is renamed here.
# If a rename is wrong the splash silently loses its background, so both files are
# checked for existence first.
PLYMOUTH_DIR="${BRAND_STAGE}/usr/share/plymouth/themes/astraos"
mkdir -p "$PLYMOUTH_DIR"
cp -a "${REPO_ROOT}/branding/plymouth/astraos/." "$PLYMOUTH_DIR/"
require_dir "${REPO_ROOT}/branding/generated/astraos-splash-boot-1920x1080.png"
cp -f "${REPO_ROOT}/branding/generated/astraos-splash-boot-1920x1080.png" \
      "$PLYMOUTH_DIR/astraos-splash-boot.png"
cp -f "${REPO_ROOT}/branding/generated/astraos-logo-512.png" \
      "$PLYMOUTH_DIR/astraos-logo.png"

# GRUB theme -> /usr/share/astraos/grub-theme (referenced from /etc/default/grub)
GRUB_DIR="${BRAND_STAGE}/usr/share/astraos/grub-theme"
mkdir -p "$GRUB_DIR"
cp -a "${REPO_ROOT}/branding/grub/astraos/." "$GRUB_DIR/"
cp -f "${REPO_ROOT}/branding/generated/astraos-splash-boot-1920x1080.png" \
      "$GRUB_DIR/astraos-splash-boot.png"

# LightDM assets -> /usr/share/astraos/lightdm (the greeter config itself is written by
# the identity hook, because lightdm-gtk-greeter owns that path as a conffile).
mkdir -p "${BRAND_STAGE}/usr/share/astraos/lightdm"
cp -a "${REPO_ROOT}/branding/lightdm/." "${BRAND_STAGE}/usr/share/astraos/lightdm/"

# LightDM drop-ins: these paths are not owned by any Debian package, so we can ship them.
mkdir -p "${BRAND_STAGE}/etc/lightdm/lightdm.conf.d"
cp -f "${REPO_ROOT}/branding/lightdm/lightdm.conf.d/50-astraos.conf" \
      "${BRAND_STAGE}/etc/lightdm/lightdm.conf.d/50-astraos.conf"

# Documentation shipped in the image.
mkdir -p "${BRAND_STAGE}/usr/share/doc/astraos-branding"
cp -f "${REPO_ROOT}/branding/README.md" "${BRAND_STAGE}/usr/share/doc/astraos-branding/README.md" 2>/dev/null || true

say "assembling astraos-desktop"
DESKTOP_STAGE="$(stage_package astraos-desktop)"

# XFCE system-wide defaults -> /etc/xdg/xfce4
mkdir -p "${DESKTOP_STAGE}/etc/xdg/xfce4"
cp -a "${REPO_ROOT}/desktop/xfce/xdg/." "${DESKTOP_STAGE}/etc/xdg/xfce4/"

# Skeleton home -> /etc/skel
mkdir -p "${DESKTOP_STAGE}/etc/skel"
cp -a "${REPO_ROOT}/desktop/skel/." "${DESKTOP_STAGE}/etc/skel/"

# Launchers -> /usr/share/applications
mkdir -p "${DESKTOP_STAGE}/usr/share/applications"
cp -a "${REPO_ROOT}/desktop/launchers/." "${DESKTOP_STAGE}/usr/share/applications/"

# Autostart -> /etc/xdg/autostart
mkdir -p "${DESKTOP_STAGE}/etc/xdg/autostart"
cp -a "${REPO_ROOT}/desktop/autostart/." "${DESKTOP_STAGE}/etc/xdg/autostart/"

# GTK/XFWM themes -> /usr/share/themes
mkdir -p "${DESKTOP_STAGE}/usr/share/themes"
cp -a "${REPO_ROOT}/desktop/themes/." "${DESKTOP_STAGE}/usr/share/themes/"

say "assembling astraos-installer"
INSTALLER_STAGE="$(stage_package astraos-installer)"
mkdir -p "${INSTALLER_STAGE}/etc/calamares"
cp -a "${REPO_ROOT}/installer/calamares/." "${INSTALLER_STAGE}/etc/calamares/"
mkdir -p "${INSTALLER_STAGE}/usr/share/calamares/branding"
cp -a "${REPO_ROOT}/installer/branding/astraos" \
      "${INSTALLER_STAGE}/usr/share/calamares/branding/"
# Calamares branding requires a raster logo; reuse the generated ring mark.
cp -f "${REPO_ROOT}/branding/generated/astraos-logo-512.png" \
      "${INSTALLER_STAGE}/usr/share/calamares/branding/astraos/logo.png"
cp -f "${REPO_ROOT}/branding/generated/astraos-login-background-1920x1080.png" \
      "${INSTALLER_STAGE}/usr/share/calamares/branding/astraos/welcome.png"

# ---------------------------------------------------------------------------
# Build them all
# ---------------------------------------------------------------------------
DEBS=()
DEBS+=("$(finish_package astraos-base "$BASE_STAGE")")
DEBS+=("$(finish_package astraos-system-tools "$TOOLS_STAGE")")
DEBS+=("$(finish_package astraos-branding "$BRAND_STAGE")")
DEBS+=("$(finish_package astraos-desktop "$DESKTOP_STAGE")")
DEBS+=("$(finish_package astraos-installer "$INSTALLER_STAGE")")

# ---------------------------------------------------------------------------
# Stage for live-build
# ---------------------------------------------------------------------------
say "staging packages for live-build in ${LIVE_PACKAGES_DIR}"
mkdir -p "$LIVE_PACKAGES_DIR"
rm -f "${LIVE_PACKAGES_DIR}"/*.deb
cp -f "${DEBS[@]}" "$LIVE_PACKAGES_DIR/"

# Record the package manifest now; scripts/generate-manifest.sh re-uses it.
MANIFEST="${OUT_DIR}/astraos-packages.txt"
: > "$MANIFEST"
for deb in "${DEBS[@]}"; do
    printf '%s  %s  %s\n' \
        "$(basename "$deb")" \
        "$(stat -c %s "$deb" 2>/dev/null || wc -c < "$deb")" \
        "$(md5sum "$deb" | cut -d' ' -f1)" >> "$MANIFEST"
done

say "wrote package manifest: ${MANIFEST}"
say "done: ${#DEBS[@]} package(s)"
