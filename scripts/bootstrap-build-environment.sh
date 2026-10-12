#!/usr/bin/env bash
# Install the host packages needed to build an AstraOS image.
#
# Plan §16.3: install only necessary host-build dependencies, keep them separate from
# the software that goes INTO AstraOS, and do not sprinkle sudo everywhere.
#
# This is the ONE script in the project that elevates privileges, and it does so only
# for the package installation itself. It never runs sudo for anything else.
#
# Usage:
#   ./scripts/bootstrap-build-environment.sh            prompt for confirmation
#   ./scripts/bootstrap-build-environment.sh --yes      no prompt (for CI)
#   ./scripts/bootstrap-build-environment.sh --print    show the command only

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

ASSUME_YES=0
PRINT_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --yes|-y) ASSUME_YES=1 ;;
        --print)  PRINT_ONLY=1 ;;
        -h|--help) sed -n '2,16p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) printf 'unknown argument: %s\n' "$arg" >&2; exit 2 ;;
    esac
done

say() { printf '[astraos:bootstrap] %s\n' "$*"; }
die() { printf '[astraos:bootstrap] ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Linux" ] || die "this script only supports Linux hosts"

if [ ! -r /etc/os-release ]; then
    die "cannot identify the host distribution (/etc/os-release is missing)"
fi
# shellcheck source=/dev/null
. /etc/os-release

# --- Build dependencies --------------------------------------------------------
# live-build, debootstrap, xorriso and squashfs-tools are the core image tools.
# The rest are for validation, testing and packaging.
if command -v apt-get >/dev/null 2>&1; then
    PKG_MANAGER="apt-get"
    PACKAGES=(
        live-build
        debootstrap
        xorriso
        squashfs-tools
        mtools
        dosfstools
        parted
        gdisk
        fdisk
        gzip
        xz-utils
        zstd
        bzip2
        file
        rsync
        curl
        wget
        git
        make
        jq
        python3
        shellcheck
        coreutils
        findutils
        dpkg-dev
        fakeroot
        isolinux
        syslinux-common
        syslinux-efi
        grub-efi-amd64-bin
        grub-pc-bin
        grub2-common
        mtools
        ovmf
        qemu-system-x86
        qemu-utils
    )
else
    die "apt-get is not available. AstraOS supports Debian-derived build hosts; see docs/BUILDING.md"
fi

# De-duplicate while preserving order.
readarray -t PACKAGES < <(printf '%s\n' "${PACKAGES[@]}" | awk '!seen[$0]++')

say "host: ${PRETTY_NAME:-unknown}"
say "package manager: ${PKG_MANAGER}"
say "packages to install: ${#PACKAGES[@]}"

printf '  %s\n' "${PACKAGES[@]}"

# Do not install anything that is not actually needed: check what is already present.
MISSING=()
for pkg in "${PACKAGES[@]}"; do
    if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'install ok installed'; then
        continue
    fi
    MISSING+=("$pkg")
done

if [ "${#MISSING[@]}" -eq 0 ]; then
    say "all build dependencies are already installed"
    exit 0
fi

say "${#MISSING[@]} package(s) still needed"

# The only elevated command in the project.
CMD="apt-get update && apt-get install -y --no-install-recommends ${MISSING[*]}"

if [ "$PRINT_ONLY" -eq 1 ]; then
    printf '\nRun this as root:\n\n  %s\n\n' "$CMD"
    exit 0
fi

if [ "$(id -u)" -eq 0 ]; then
    say "running as root"
    eval "$CMD"
else
    if ! command -v sudo >/dev/null 2>&1; then
        die "not root and sudo is unavailable. Run this as root, or run: ${CMD}"
    fi
    if [ "$ASSUME_YES" -ne 1 ]; then
        printf '\nThis will install %d package(s) on this host using sudo:\n\n  %s\n\n' \
            "${#MISSING[@]}" "$CMD"
        printf 'Continue? [y/N] '
        read -r reply
        case "$reply" in
            y|Y|yes|YES) : ;;
            *) say "cancelled; nothing was installed"; exit 0 ;;
        esac
    fi
    # shellcheck disable=SC2016
    sudo sh -c "$CMD"
fi

say "build dependencies installed"
say "verify with: ./scripts/validate-environment.sh"
