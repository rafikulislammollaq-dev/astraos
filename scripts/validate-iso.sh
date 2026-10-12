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

ok()   { PASS=$((PASS + 1)); printf '  [ ok ]   %s\n' "$*"; }
bad()  { FAIL=$((FAIL + 1)); printf '  [FAIL]   %s\n' "$*"; }
warn() { WARN=$((WARN + 1)); printf '  [warn]   %s\n' "$*"; }
section() { printf '\n== %s ==\n' "$*"; }

SIZE="$(wc -c < "$ISO")"
printf 'Validating %s\n' "$ISO"

# ---------------------------------------------------------------------------
section "File"
# ---------------------------------------------------------------------------
printf '  size: %s bytes (%s MiB)\n' "$SIZE" "$((SIZE / 1048576))"

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
    printf '  file(1) says: %s\n' "$FILE_OUT"
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
    LISTING="$(xorriso -indev "$ISO" -find / -maxdepth 3 -type f -exec lsdl -- 2>/dev/null || true)"

    if printf '%s' "$LISTING" | grep -q '/EFI/boot/bootx64.efi\|/efi/boot/bootx64.efi'; then
        ok "UEFI boot loader present (EFI/boot/bootx64.efi)"
    else
        bad "no UEFI boot loader found; the image will not boot in UEFI mode"
    fi

    if printf '%s' "$LISTING" | grep -qi '/isolinux/isolinux.bin\|/isolinux/ldlinux'; then
        ok "legacy BIOS boot loader present (isolinux)"
    else
        warn "no isolinux found; legacy BIOS boot may not work"
    fi

    if printf '%s' "$LISTING" | grep -q 'grub.cfg'; then
        ok "GRUB configuration present"
    else
        bad "no grub.cfg found; the boot menu configuration is missing"
    fi

    # The live filesystem is what the installer unpacks onto the target disk.
    if printf '%s' "$LISTING" | grep -q 'filesystem.squashfs'; then
        ok "live filesystem (filesystem.squashfs) present"
    else
        bad "filesystem.squashfs is missing; the image has no live root filesystem"
    fi

    # Kernel and initramfs: without both, the image cannot boot even if GRUB runs.
    if printf '%s' "$LISTING" | grep -q 'vmlinuz'; then
        ok "kernel present in the image"
    else
        bad "no vmlinuz found"
    fi
    if printf '%s' "$LISTING" | grep -q 'initrd'; then
        ok "initramfs present in the image"
    else
        bad "no initrd found"
    fi

    # The installer must be reachable from the booted system; the ISO label matters for
    # live-boot to find its own medium.
    if printf '%s' "$LISTING" | grep -q '/live/'; then
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
    if xorriso -indev "$ISO" -find / -name '.disk' -type d 2>/dev/null | grep -q '.disk'; then
        INFO="$(xorriso -osirrox on -indev "$ISO" -extract /\.disk/info /dev/stdout 2>/dev/null || true)"
        printf '  medium info: %s\n' "${INFO:-unavailable}"
        case "$INFO" in
            *AstraOS*|*astraos*) ok "medium identifies itself as AstraOS" ;;
            *Debian*)
                bad "medium identifies itself as Debian, not AstraOS; this may be an unmodified Debian image"
                ;;
            *) warn "medium identity could not be confirmed from .disk/info" ;;
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
    TMP_SQUASH="$(mktemp --suffix=-astraos.squashfs 2>/dev/null || echo "/tmp/astraos-$$.squashfs")"
    section "Live filesystem contents"
    if xorriso -osirrox on -indev "$ISO" -extract /live/filesystem.squashfs "$TMP_SQUASH" >/dev/null 2>&1; then
        # -l lists without extracting. Filter to the paths that prove AstraOS is inside.
        CONTENTS="$(unsquashfs -l "$TMP_SQUASH" 2>/dev/null || true)"
        check_in_squashfs() {
            description="$1"; pattern="$2"
            if printf '%s' "$CONTENTS" | grep -q -- "$pattern"; then
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
        check_in_squashfs "the astraos-base package"        'squashfs-root/var/lib/dpkg/status'
    else
        warn "could not extract filesystem.squashfs from the ISO; contents were not inspected"
    fi
    rm -f "$TMP_SQUASH" 2>/dev/null || true
else
    warn "unsquashfs or xorriso is missing; the live filesystem contents were NOT inspected"
fi

# ---------------------------------------------------------------------------
section "Checksums"
# ---------------------------------------------------------------------------
if command -v sha256sum >/dev/null 2>&1; then
    COMPUTED="$(sha256sum "$ISO" | cut -d' ' -f1)"
    printf '  sha256: %s\n' "$COMPUTED"
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
printf '\n%s\n' "-------------------------------------------------------"
printf 'passed: %s   warnings: %s   failures: %s\n' "$PASS" "$WARN" "$FAIL"

if [ "$FAIL" -gt 0 ]; then
    printf '\nRESULT: the image FAILED structural validation.\n'
    exit 1
fi

printf '\nRESULT: the image passed STRUCTURAL validation.\n'
printf 'It has NOT been booted. Structural validity is not evidence that the OS boots.\n'
printf 'Next step: docs/INSTALLATION_VIRTUALBOX.md\n'
exit 0
