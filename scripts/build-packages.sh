#!/usr/bin/env bash
# Build the AstraOS .deb packages.
#
# Why not dpkg-buildpackage?
#   The four AstraOS packages are simple file-installation packages. Using the full
#   Debian source-package machinery would add debhelper, fakeroot, a signed source
#   tarball and a build-dependency chain, none of which buys anything for this release.
#   dpkg-deb is used directly, and every .deb it produces is read back afterwards and
#   checked for the right name and version. plan §2.3 forbids inventing substitutes for
#   essential system components; this is packaging our own content, not replacing dpkg.
#
# Reproducibility (plan §2.4):
#   SOURCE_DATE_EPOCH is derived from the latest commit when git is available, so two
#   builds of the same content produce identical .deb files apart from nothing.
#
# Output:
#   build/live-build/packages/*.deb                 the packages
#   build/live-build/config/packages.chroot/*.deb   staged for live-build to install
#
# Both live under ASTRAOS_BUILD_DIR ("build/live-build"), not build/packages. The
# paths above are quoted from config/distribution.env rather than written out, because
# a comment naming the wrong directory is how a cleanup target ends up deleting the
# thing it promises to keep. See the `clean` target in the Makefile.
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
# ASTRAOS_BUILD_DIR is already the live-build working directory (build/live-build), so the
# staged packages go directly under its config/. An earlier version appended /live-build
# again, which staged them into a directory live-build never reads: the .deb files were
# built correctly and then silently left out of the image, and the first sign of it was the
# identity hook failing because /usr/bin/astraos-info was missing from the chroot.
LIVE_PACKAGES_DIR="${REPO_ROOT}/${ASTRAOS_BUILD_DIR}/config/packages.chroot"
LOG_DIR="${REPO_ROOT}/${ASTRAOS_LOG_DIR}"

# Progress goes to stderr, and stdout carries only data.
#
# This is not cosmetic: stage_package and finish_package return a path through command
# substitution, so anything they print on stdout becomes part of that path. The first
# build that got this far logged "built astraos-base -> astraos-base_0.1.0_amd64.deb"
# on stdout and then tried to copy a file named after the log line.
say() { printf '[astraos:packages] %s\n' "$*" >&2; }
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

    local out="${OUT_DIR}/${name}_${PACKAGE_VERSION}_${ASTRAOS_ARCH_DEB}.deb"
    # --root-owner-group makes the archive reproducible regardless of who builds it.
    dpkg-deb --build --root-owner-group "${stage}" "$out" >/dev/null \
        || die "dpkg-deb --build failed for ${name}"

    # Read the .deb back. This validates what was actually produced rather than the
    # staging directory, and it is the only check that can catch a substitution that
    # produced a syntactically valid but wrong package: the fields are compared below.
    #
    # The reason for the rework: this used to run `dpkg-deb --info` on the staging
    # directory with stderr thrown away, and the first real CI build failed with
    # "dpkg-deb rejected the control directory for astraos-base" and no explanation. A
    # check that cannot say why it failed is worse than no check (plan §16.2, §28).
    local reported_package reported_version info_output
    info_output="$(dpkg-deb --info "$out" 2>&1)" \
        || { printf '%s\n' "$info_output" >&2; die "dpkg-deb cannot read back ${name}"; }
    dpkg-deb --contents "$out" >/dev/null \
        || die "dpkg-deb cannot list the contents of ${name}"

    reported_package="$(dpkg-deb -f "$out" Package 2>/dev/null)"
    reported_version="$(dpkg-deb -f "$out" Version 2>/dev/null)"
    [ "$reported_package" = "$name" ] \
        || die "${name}: the built package calls itself '${reported_package}'"
    [ "$reported_version" = "$PACKAGE_VERSION" ] \
        || die "${name}: the built package reports version '${reported_version}', expected '${PACKAGE_VERSION}'"

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

    # Commands shipped in /usr/bin must be executable. The mode is applied here instead of
    # being trusted from the working tree, because a checkout on a host that has no execute
    # bit (Windows) would otherwise install tools that cannot run; the first symptom of that
    # was the identity hook failing because /usr/bin/astraos-info was not executable.
    if [ -d "${stage}/usr/bin" ]; then
        find "${stage}/usr/bin" -type f -exec chmod 0755 {} +
    fi

    # Same rule for the Windows-bridge command directory: a Windows checkout has no
    # execute bits, and every file in winbin must be invokable by name.
    if [ -d "${stage}/usr/lib/astraos/winbin" ]; then
        find "${stage}/usr/lib/astraos/winbin" -type f -exec chmod 0755 {} +
    fi
    if [ -d "${stage}/usr/lib/astraos/shell" ]; then
        find "${stage}/usr/lib/astraos/shell" -type f -exec chmod 0755 {} +
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

say "assembling astraos-system-tools"
TOOLS_STAGE="$(stage_package astraos-system-tools)"

say "assembling astraos-winbridge"
WINBRIDGE_STAGE="$(stage_package astraos-winbridge)"
# The bridge, the astra command and the shell integration are all in the tree
# already; nothing else to assemble. The stage_package chmod rules above cover
# /usr/bin and the winbin/shell directories.

say "assembling astraos-ai"
AI_STAGE="$(stage_package astraos-ai)"
# The assistant's tree is complete in the package: the astra-ai entry point in
# /usr/bin, the library in /usr/lib/astraos/ai and the web interface under
# /usr/share/astraos/ai/web, which the server reads from the system directory so a
# local copy cannot be shadowed.
#
# Nothing is generated here and nothing is downloaded here. The model, whisper.cpp and
# Piper are installed by `astra-ai setup` on the user's machine, because the build
# machines have no business fetching a gigabyte of model per ISO, and because a
# distribution that ships the model silently has decided for the user.

say "assembling astraos-hud"
HUD_STAGE="$(stage_package astraos-hud)"
# The HUD is a runnable application, so its source lives in apps/astraos-hud rather than in
# the package's own root/ tree. It is installed as an importable package under
# /usr/lib/astraos-hud, which is exactly the directory the /usr/bin/astraos-hud shim puts on
# PYTHONPATH. Those two paths are one decision written in two places, so
# tests/static/test_astra_hud.py pins them together: if they drift the launcher dies on
# ImportError and nothing else in the repository notices.
mkdir -p "${HUD_STAGE}/usr/lib/astraos-hud"
cp -a "${REPO_ROOT}/apps/astraos-hud/astraos_hud" "${HUD_STAGE}/usr/lib/astraos-hud/"
# A local run of the application can leave __pycache__ behind; it is not part of the package.
find "${HUD_STAGE}/usr/lib/astraos-hud" -type d -name '__pycache__' -prune -exec rm -rf {} +

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

# Cursor theme -> /usr/share/icons/AstraOS/cursors
#
# A cursor theme is an icon theme that carries a `Cursor Theme=` key in its top-level
# index.theme and keeps the binary cursors in a subdirectory of cursors/ that has its
# own index.theme. Both index files are written by the generator rather than kept in
# branding/icons/, because they must agree with the cursor names it actually emitted.
#
# The binary .xcursor files are installed by branding (they are generated art); the
# index.theme that points libXcursor at them is also installed here, next to the icon
# theme that owns the directory.
require_dir "${REPO_ROOT}/branding/generated/cursors"
for cursor_theme in AstraOS AstraOS-Light; do
    cursor_src="${REPO_ROOT}/branding/generated/cursors/${cursor_theme}"
    [ -d "$cursor_src" ] || die "cursor theme missing: $cursor_src (run branding/tools/render_theme_assets.py)"
    cursor_dst="${BRAND_STAGE}/usr/share/icons/AstraOS/cursors/${cursor_theme}"
    mkdir -p "$cursor_dst"
    cp -a "${cursor_src}/." "$cursor_dst/"
    cat > "${cursor_dst}/index.theme" <<EOF
[Icon Theme]
Name=${cursor_theme}
Comment=AstraOS cursor theme, generated by branding/tools/render_theme_assets.py
Inherits=
EOF
done

# The outer cursors/index.theme names the sub-theme for the icon-theme lookup.
printf '[Icon Theme]\nName=AstraOS\nComment=AstraOS cursor theme\nInherits=\n' \
    > "${BRAND_STAGE}/usr/share/icons/AstraOS/cursors/index.theme"

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

# Desktop defaults: /etc/skel only, deliberately.
#
# There is no /etc/xdg/xfce4 mapping here. That directory is owned by Debian's Xfce packages,
# which ship their own xsettings.xml, xfce4-session.xml and keyboard-shortcuts file there;
# dpkg refuses to let a second package own the same path, and the image build dies with
# "trying to overwrite ... which is also in package ...". The defaults live in desktop/skel/
# instead, which is a directory this project owns and which populates every new account.
# tests/static/test_packages.py rejects a mapping back into an upstream-owned directory.

# Skeleton home -> /etc/skel
mkdir -p "${DESKTOP_STAGE}/etc/skel"
cp -a "${REPO_ROOT}/desktop/skel/." "${DESKTOP_STAGE}/etc/skel/"

# Launchers -> /usr/share/applications
mkdir -p "${DESKTOP_STAGE}/usr/share/applications"
cp -a "${REPO_ROOT}/desktop/launchers/." "${DESKTOP_STAGE}/usr/share/applications/"

# Desktop shortcuts -> /etc/skel/Desktop
#
# Three icons greet a first login: install, the welcome guide, and the assistant. They
# are not duplicates - the files just installed into /usr/share/applications are copied,
# and the assistant's comes from its own package, so a name, a comment or an icon is
# changed in exactly one place and cannot drift.
#
# THE MODE IS SET HERE, NOT TRUSTED FROM THE WORKING TREE. xfdesktop refuses to run a
# launcher that is not executable: it draws it as an "Untrusted application launcher"
# and asks before doing anything. A checkout on Windows has no execute bits at all -
# the same trap that once made the build ship a non-executable astraos-info - so the
# bit is applied to the staged copy.
mkdir -p "${DESKTOP_STAGE}/etc/skel/Desktop"
for entry in astraos-installer astraos-welcome astraos-hud; do
    cp -f "${DESKTOP_STAGE}/usr/share/applications/${entry}.desktop" \
          "${DESKTOP_STAGE}/etc/skel/Desktop/"
done
[ -f "${AI_STAGE}/usr/share/applications/astraos-ai.desktop" ] \
    || die "astraos-ai did not install a launcher, so the desktop shortcut cannot be seeded"
cp -f "${AI_STAGE}/usr/share/applications/astraos-ai.desktop" \
      "${DESKTOP_STAGE}/etc/skel/Desktop/"
chmod 0755 "${DESKTOP_STAGE}/etc/skel/Desktop/"*.desktop

# Autostart -> /etc/xdg/autostart
mkdir -p "${DESKTOP_STAGE}/etc/xdg/autostart"
cp -a "${REPO_ROOT}/desktop/autostart/." "${DESKTOP_STAGE}/etc/xdg/autostart/"

# GTK/XFWM themes -> /usr/share/themes
mkdir -p "${DESKTOP_STAGE}/usr/share/themes"
cp -a "${REPO_ROOT}/desktop/themes/." "${DESKTOP_STAGE}/usr/share/themes/"

# Compositor profile -> /etc/astraos/picom.conf
#
# NOT an autostart entry: the default session runs xfwm4's own compositor
# (reliable everywhere, including VirtualBox without 3D). `astra effects on`
# copies this profile to ~/.config/picom/picom.conf and registers the
# autostart template from /etc/astraos/autostart - both shipped here.
require_dir "${REPO_ROOT}/desktop/compositor"
mkdir -p "${DESKTOP_STAGE}/etc/astraos" "${DESKTOP_STAGE}/etc/astraos/autostart"
cp -f "${REPO_ROOT}/desktop/compositor/picom.conf" \
      "${DESKTOP_STAGE}/etc/astraos/picom.conf"
cp -f "${REPO_ROOT}/desktop/session/astraos-picom.desktop" \
      "${DESKTOP_STAGE}/etc/astraos/autostart/astraos-picom.desktop"

# Window decoration assets -> /usr/share/themes/<theme>/xfwm4
#
# The CSS in desktop/themes cannot draw a titlebar: xfwm4 loads its decorations as
# image files named <part>-<state>.png, and falls back to whatever theme it can find
# when they are missing. That fallback is why docs/KNOWN_LIMITATIONS.md 1.4 used to say
# the desktop had no decoration theme at all - naming one whose assets were not
# installed produces missing titlebars, which is worse than an ugly one.
#
# These are generated by branding/tools/render_theme_assets.py from the same
# config/branding.env metrics that scripts/build-packages.sh reads, so the drawn
# titlebar height and the height the theme declares cannot drift apart. A mismatch is
# the specific failure that produces a clipped or invisible titlebar.
require_dir "${REPO_ROOT}/branding/generated/xfwm4"
for window_theme in AstraOS-Dark AstraOS-Light; do
    decoration_src="${REPO_ROOT}/branding/generated/xfwm4/${window_theme}"
    [ -d "$decoration_src" ] || die "xfwm4 decorations missing: $decoration_src (run branding/tools/render_theme_assets.py)"
    # themerc is version-controlled text, next to the generated images it describes.
    [ -f "${REPO_ROOT}/desktop/themes/${window_theme}/xfwm4/themerc" ] \
        || die "xfwm4 theme is incomplete: ${window_theme}/xfwm4/themerc is missing"
    decoration_dst="${DESKTOP_STAGE}/usr/share/themes/${window_theme}/xfwm4"
    mkdir -p "$decoration_dst"
    cp -a "${decoration_src}/." "$decoration_dst/"
    cp -f "${REPO_ROOT}/desktop/themes/${window_theme}/xfwm4/themerc" \
        "${decoration_dst}/themerc"
done

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
DEBS+=("$(finish_package astraos-winbridge "$WINBRIDGE_STAGE")")
DEBS+=("$(finish_package astraos-ai "$AI_STAGE")")
DEBS+=("$(finish_package astraos-hud "$HUD_STAGE")")
DEBS+=("$(finish_package astraos-branding "$BRAND_STAGE")")
DEBS+=("$(finish_package astraos-desktop "$DESKTOP_STAGE")")
DEBS+=("$(finish_package astraos-installer "$INSTALLER_STAGE")")

# The paths above come back through command substitution, so a stray log line on stdout
# would travel with them and fail later as an unreadable filename. Check them here, where
# the cause is obvious.
for deb in "${DEBS[@]}"; do
    [ -f "$deb" ] || die "internal error: expected a built package, got: ${deb}"
done

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
