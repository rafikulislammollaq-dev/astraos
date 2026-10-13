#!/usr/bin/env bash
# Validate an AstraOS ISO structurally.
#
# Plan §6.2 and §18.2. This checks the image is a real, structurally valid bootable
# image built from the AstraOS configuration. It does NOT check that the OS boots.
#
# Being explicit about that limit matters: every check below can pass on an image that
# panics on boot. Boot testing is a separate, manual procedure
# (docs/INSTALLATION_VIRTUALBOX.md), and the manifest records that distinction.
#
# Usage: ./scripts/validate-iso.sh path/to/image.iso

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=/dev/null
. "${REPO_ROOT}/config/distribution.env"

ISO="${1:-}"
[ -n "$ISO" ] || { printf 'usage: %s path/to/image.iso\n' "$0" >&2; exit 2; }
[ -f "$ISO" ] || { printf 'ERROR: no such file: %s\n' "$ISO" >&2; exit 1; }

PASS=0
FAIL=0
WARN=0

ok()   { PASS=$((PASS + 1)); printf '  [ ok ]   %s\n' "$*" >&2; }
bad()  { FAIL=$((FAIL + 1)); printf '  [FAIL]   %s\n' "$*" >&2; }
warn() { WARN=$((WARN + 1)); printf '  [warn]   %s\n' "$*" >&2; }
section() { printf '\n== %s ==\n' "$*" >&2; }

# A tool's own diagnostic is the only thing that makes a failure actionable: an
# extraction that produced nothing looks identical to a file that was never read
# unless the tool's stderr is kept. Every extraction below captures it and calls
# this to show it.
describe_error() {
    if [ -s "$1" ]; then
        tr '\n' ' ' < "$1" | cut -c1-300
    else
        printf 'the tool produced no diagnostic'
    fi
}

# Every listing this script inspects is written to a file and read from that file, and
# nothing is ever piped into `grep -q`. `set -o pipefail` is in effect, so a `grep -q` that
# exits the moment it matches kills the writer with SIGPIPE, and pipefail then reports that
# *successful* match as a failed pipeline. That is how this script reported a complete live
# filesystem as missing eight of its nine components — a 1894 MiB squashfs with 152556
# inodes, holding every path it looked for, where only the pattern that happened to sit near
# the end of the listing survived the race. The same shape is wrong for any listing, however
# small it looks today: it is a race, not a size limit. A file has no such failure mode.
WORK_DIR="$(mktemp -d 2>/dev/null || echo "/tmp/astraos-validate-$$")"
mkdir -p "$WORK_DIR" 2>/dev/null || true
trap 'rm -rf -- "$WORK_DIR" 2>/dev/null || true' EXIT INT TERM
LISTING_FILE="${WORK_DIR}/iso-listing.txt"

SIZE="$(wc -c < "$ISO")"
printf 'Validating %s\n' "$ISO" >&2

# ---------------------------------------------------------------------------
section "File"
# ---------------------------------------------------------------------------
printf '  size: %s bytes (%s MiB)\n' "$SIZE" "$((SIZE / 1048576))" >&2

# A live desktop image with a browser and office tools cannot be small. A file this
# size is almost certainly a failed or truncated build.
if [ "$SIZE" -lt 209715200 ]; then
    bad "smaller than 200 MiB; not a plausible desktop live image"
elif [ "$SIZE" -gt 4294967296 ]; then
    warn "larger than 4 GiB; check nothing unintended was included"
else
    ok "size is plausible for a desktop live image"
fi

if command -v file >/dev/null 2>&1; then
    FILE_OUT="$(file -b "$ISO")"
    printf '  file(1) says: %s\n' "$FILE_OUT" >&2
    case "$FILE_OUT" in
        *ISO\ 9660*) ok "recognised as an ISO 9660 filesystem" ;;
        *) bad "file(1) does not recognise this as an ISO 9660 image" ;;
    esac
else
    warn "file(1) is not installed; ISO magic was not checked"
fi

# ---------------------------------------------------------------------------
section "Boot path"
# ---------------------------------------------------------------------------
if command -v xorriso >/dev/null 2>&1; then
    # The listing is a file, for the reason given beside the work directory at the top of
    # this script. Its diagnostic is kept as well: an empty listing is the one outcome that
    # would otherwise be indistinguishable from an image that has no bootloader at all.
    xorriso -indev "$ISO" -find / -maxdepth 3 -type f -exec lsdl -- \
        >"$LISTING_FILE" 2>"${WORK_DIR}/xorriso-find.err" || true
    if [ ! -s "$LISTING_FILE" ]; then
        warn "xorriso listed no files in the image: $(describe_error "${WORK_DIR}/xorriso-find.err")"
    fi

    if grep -q -- '/EFI/boot/bootx64.efi\|/efi/boot/bootx64.efi' "$LISTING_FILE"; then
        ok "UEFI boot loader present (EFI/boot/bootx64.efi)"
    else
        bad "no UEFI boot loader found; the image will not boot in UEFI mode"
    fi

    if grep -qi -- '/isolinux/isolinux.bin\|/isolinux/ldlinux' "$LISTING_FILE"; then
        ok "legacy BIOS boot loader present (isolinux)"
    else
        warn "no isolinux found; legacy BIOS boot may not work"
    fi

    if grep -q -- 'grub.cfg' "$LISTING_FILE"; then
        ok "GRUB configuration present"
    else
        bad "no grub.cfg found; the boot menu configuration is missing"
    fi

    # The live filesystem is what the installer unpacks onto the target disk.
    if grep -q -- 'filesystem.squashfs' "$LISTING_FILE"; then
        ok "live filesystem (filesystem.squashfs) present"
    else
        bad "filesystem.squashfs is missing; the image has no live root filesystem"
    fi

    # Kernel and initramfs: without both, the image cannot boot even if GRUB runs.
    if grep -q -- 'vmlinuz' "$LISTING_FILE"; then
        ok "kernel present in the image"
    else
        bad "no vmlinuz found"
    fi
    if grep -q -- 'initrd' "$LISTING_FILE"; then
        ok "initramfs present in the image"
    else
        bad "no initrd found"
    fi

    # The installer must be reachable from the booted system; the ISO label matters for
    # live-boot to find its own medium.
    if grep -q -- '/live/' "$LISTING_FILE"; then
        ok "/live/ directory present (live-boot layout)"
    else
        warn "no /live/ directory found; live-boot may not locate its filesystem"
    fi
else
    warn "xorriso is not installed; the ISO contents were NOT inspected"
    bad "cannot confirm the image contains a kernel, initramfs or live filesystem"
fi

# ---------------------------------------------------------------------------
section "AstraOS customisation"
# ---------------------------------------------------------------------------
# A renamed Debian ISO is not an AstraOS release (plan §6.2). These checks look for
# evidence that this image was actually produced from the AstraOS configuration.
if command -v xorriso >/dev/null 2>&1; then
    xorriso -indev "$ISO" -find / -name '.disk' -type d \
        >"${WORK_DIR}/disk-dirs.txt" 2>"${WORK_DIR}/xorriso-disk.err" || true
    if [ -s "${WORK_DIR}/disk-dirs.txt" ]; then
        # Extracting to /dev/stdout looked like a way to read a file straight out of the
        # ISO, but xorriso writes a FILE at that path (and on some hosts fails outright),
        # which left INFO empty and this check reporting a valid image as unidentified.
        # The same destination-and-diagnostics rule as the squashfs check applies: extract
        # to a path that does not pre-exist — a fresh name inside the work directory —
        # verify what came out, and keep the stderr.
        if xorriso -osirrox on -indev "$ISO" -extract /\.disk/info \
                "${WORK_DIR}/disk-info" 2>"${WORK_DIR}/xorriso-disk-info.err"; then
            INFO="$(cat "${WORK_DIR}/disk-info" 2>/dev/null || true)"
        fi
        printf '  medium info: %s\n' "${INFO:-unavailable}" >&2
        case "$INFO" in
            *AstraOS*|*astraos*) ok "medium identifies itself as AstraOS" ;;
            *Debian*)
                bad "medium identifies itself as Debian, not AstraOS; this may be an unmodified Debian image"
                ;;
            *) warn "medium identity could not be confirmed from .disk/info: $(describe_error "${WORK_DIR}/xorriso-disk-info.err")" ;;
        esac
    else
        warn "no .disk/info found; medium identity could not be confirmed"
    fi
fi

# The strongest structural check available without booting: confirm that the live
# filesystem actually contains the AstraOS components, not just that a squashfs exists.
# A squashfs full of Debian with AstraOS branding only on the ISO surface would pass
# every check above and fail here.
if command -v unsquashfs >/dev/null 2>&1 && command -v xorriso >/dev/null 2>&1; then
    section "Live filesystem contents"
    # The listing is taken from a file this script extracts, so an empty or unreadable
    # extraction looks exactly like an image that lacks every component. That is what
    # happened once: mktemp pre-created the destination, xorriso wrote nothing onto it and
    # still exited 0, unsquashfs then failed on the empty file, and its complaint was
    # discarded — nine paths reported missing for a filesystem that was never read. Each
    # step below therefore keeps its own error and the size it produced, and the destination
    # is a fresh name inside the work directory, so it does not exist before xorriso writes
    # it.
    TMP_SQUASH="${WORK_DIR}/filesystem.squashfs"
    LIST_FILE="${WORK_DIR}/squashfs-listing.txt"

    if ! xorriso -osirrox on -indev "$ISO" -extract /live/filesystem.squashfs \
            "$TMP_SQUASH" >/dev/null 2>"${WORK_DIR}/xorriso.err"; then
        bad "could not extract /live/filesystem.squashfs from the ISO: $(describe_error "${WORK_DIR}/xorriso.err")"
    elif [ ! -s "$TMP_SQUASH" ]; then
        bad "the extracted filesystem.squashfs is empty, so the image has no readable live filesystem: $(describe_error "${WORK_DIR}/xorriso.err")"
    else
        printf '  extracted: %s MiB\n' "$(( $(wc -c < "$TMP_SQUASH") / 1048576 ))" >&2
        # -l lists without extracting. The listing is written to a file and read from there:
        # piping it into `grep -q` is what made a complete filesystem look like it was
        # missing every AstraOS component (see the note beside the work directory).
        if ! unsquashfs -l "$TMP_SQUASH" >"$LIST_FILE" 2>"${WORK_DIR}/unsquashfs.err"; then
            bad "unsquashfs could not list the live filesystem: $(describe_error "${WORK_DIR}/unsquashfs.err")"
        elif [ ! -s "$LIST_FILE" ]; then
            bad "unsquashfs produced an empty listing for a $(( $(wc -c < "$TMP_SQUASH") / 1048576 )) MiB live filesystem: $(describe_error "${WORK_DIR}/unsquashfs.err")"
        elif ! grep -q -- 'squashfs-root/' "$LIST_FILE"; then
            # The checks below match paths as unsquashfs prints them, prefixed with the
            # directory it would extract into. A listing without a single such path means the
            # prefix assumption is wrong, and reporting that once is honest where eight
            # "does NOT contain" lines would blame the image for a defect in this script.
            bad "unsquashfs listed the live filesystem without any 'squashfs-root/' paths, so the component checks below have nothing to match: $(describe_error "${WORK_DIR}/unsquashfs.err")"
        else
        printf '  listed: %s entries\n' "$(wc -l < "$LIST_FILE")" >&2
        check_in_squashfs() {
            description="$1"; pattern="$2"
            if grep -q -- "$pattern" "$LIST_FILE"; then
                ok "live filesystem contains ${description}"
            else
                bad "live filesystem does NOT contain ${description} (looked for ${pattern})"
            fi
        }
        check_in_squashfs "the astraos-info command"        'squashfs-root/usr/bin/astraos-info'
        check_in_squashfs "the AstraOS release file"        'squashfs-root/etc/astraos-release'
        check_in_squashfs "the Xfce session"                'squashfs-root/usr/bin/xfce4-session'
        check_in_squashfs "the LightDM greeter"             'squashfs-root/usr/sbin/lightdm'
        check_in_squashfs "the Calamares installer"         'squashfs-root/usr/bin/calamares'
        check_in_squashfs "the AstraOS installer branding"  'squashfs-root/usr/share/calamares/branding/astraos'
        check_in_squashfs "the AstraOS Plymouth theme"      'squashfs-root/usr/share/plymouth/themes/astraos'
        check_in_squashfs "the AstraOS wallpaper"           'squashfs-root/usr/share/astraos/wallpapers'
        # /var/lib/dpkg/status exists on every Debian system, so this check used to pass on an
        # image containing no AstraOS package at all: it proved nothing. dpkg writes
        # /var/lib/dpkg/info/<package>.* only for a package it has actually installed.
        check_in_squashfs "the astraos-base package"        'squashfs-root/var/lib/dpkg/info/astraos-base'
        fi
    fi
else
    warn "unsquashfs or xorriso is missing; the live filesystem contents were NOT inspected"
fi

# ---------------------------------------------------------------------------
section "Checksums"
# ---------------------------------------------------------------------------
if command -v sha256sum >/dev/null 2>&1; then
    COMPUTED="$(sha256sum "$ISO" | cut -d' ' -f1)"
    printf '  sha256: %s\n' "$COMPUTED" >&2
    if [ -f "${ISO}.sha256" ]; then
        if ( cd "$(dirname "$ISO")" && sha256sum -c "$(basename "$ISO").sha256" >/dev/null 2>&1 ); then
            ok "the published checksum file matches the image"
        else
            bad "the published checksum file does NOT match the image"
        fi
    else
        warn "no checksum file exists yet; run scripts/generate-checksums.sh"
    fi
else
    bad "sha256sum is not available"
fi

# ---------------------------------------------------------------------------
printf '\n%s\n' "-------------------------------------------------------" >&2
printf 'passed: %s   warnings: %s   failures: %s\n' "$PASS" "$WARN" "$FAIL" >&2

if [ "$FAIL" -gt 0 ]; then
    printf '\nRESULT: the image FAILED structural validation.\n' >&2
    exit 1
fi

printf '\nRESULT: the image passed STRUCTURAL validation.\n' >&2
printf 'It has NOT been booted. Structural validity is not evidence that the OS boots.\n' >&2
printf 'Next step: docs/INSTALLATION_VIRTUALBOX.md\n' >&2
exit 0
