#!/usr/bin/env bash
# Boot a built AstraOS ISO through its own boot menus and prove the live system starts.
#
# WHY THIS EXISTS
#   scripts/smoke-boot.sh boots the kernel and initrd taken out of the ISO with the ISO
#   attached as the live medium, and the ISO's own boot entries are never asked to do
#   anything. A user's machine takes the other path: firmware starts the ISO's boot
#   record (BIOS) or EFI system partition (UEFI), a bootloader menu appears, and its
#   default entry boots the kernel with the command line the menu itself carries. A
#   defective bootloader install, a missing or broken menu entry, or a menu entry whose
#   command line is wrong would all pass the smoke test and fail on that machine. This
#   script exercises that path: it is the menu, not this host, that boots the guest.
#
# WHAT THIS DOES
#   1. boots the ISO in QEMU with QEMU's own firmware starting the machine - this host
#      never supplies a kernel, an initrd or a command line;
#   2. accepts the menu's default entry: the QEMU monitor presses Enter every few
#      seconds (the menu timeout is live-build's default, which the pinned release
#      cannot change - see docs/KNOWN_LIMITATIONS.md section 3.10 - so the default
#      entry is obtained exactly the way a person who presses nothing obtains it);
#   3. waits for the live system's login prompt on the serial console. The menu entry
#      itself puts it there: console=ttyS0,115200n8 is part of LIVE_APPEND in
#      config/live-build/auto/config, so the prompt appears only when the shipped menus
#      are right. The ISO's entries do NOT carry astraos.ci=1, so the guest runs no
#      self-test and does not power off here: it stops at the login prompt, and this
#      script stops the machine;
#   4. keeps serial.log and qemu.out as evidence and exits 0 only when the prompt
#      appeared.
#
# Usage: scripts/boot-menu-test.sh --medium bios|efi|secure --out DIR [--timeout MINUTES] ISO
#
# The workflow .github/workflows/build-iso.yml runs this against the ISO it has just
# built, once per medium. On a local machine:
#
#   ./scripts/boot-menu-test.sh --medium bios   --out out-bios   dist/astraos-*.iso
#   ./scripts/boot-menu-test.sh --medium secure --out out-secure dist/astraos-*.iso
#
# efi needs the OVMF firmware (the "ovmf" package on Debian and Ubuntu). bios needs
# nothing beyond QEMU itself. secure runs the UEFI path under OVMF's Secure Boot
# firmware with the Microsoft keys enrolled, so only a signed chain - Microsoft-signed
# shim, Debian-signed GRUB, Debian-signed kernel - reaches the login prompt. No root
# is needed: nothing is mounted. KVM is used when the host allows it; QEMU emulation
# is the fallback - slower, not different.
# Documented in docs/BUILDING.md, "The boot menus".

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=/dev/null
. "${REPO_ROOT}/config/distribution.env"

TIMEOUT_MINUTES=25
MEDIUM=""
OUT_DIR=""
ISO=""

usage() {
    cat <<'USAGE'
Usage: scripts/boot-menu-test.sh --medium bios|efi|secure --out DIR [--timeout MINUTES] ISO

Boots a built AstraOS ISO in QEMU through its own boot menus - firmware, bootloader
menu, default entry - with nothing supplied by this host, waits for the live system's
login prompt on the serial console, and exits 0 only when it appears. serial.log and
qemu.out are copied to --out; on failure the last serial lines are printed.

  --medium bios|efi|secure   which firmware path to exercise (required; "secure"
                             enforces Secure Boot, so only a signed chain boots)
  --out DIR                  copy serial.log, qemu.out and (on secure) firmware.txt
                             there (required)
  --timeout MINUTES          how long to wait for the login prompt (default 25)
  -h, --help                 this text
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --medium)
            MEDIUM="$2"
            shift 2
            ;;
        --out)
            OUT_DIR="$2"
            shift 2
            ;;
        --timeout)
            TIMEOUT_MINUTES="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -*)
            printf 'boot-menu-test: unknown option: %s\n' "$1" >&2
            exit 2
            ;;
        *)
            ISO="$1"
            shift
            ;;
    esac
done

die() {
    printf 'boot-menu-test: %s\n' "$*" >&2
    exit 1
}

say() { printf 'boot-menu-test: %s\n' "$*"; }

case "$MEDIUM" in
    bios|efi|secure) ;;
    "") die "no --medium given (try --help)" ;;
    *) die "--medium must be bios, efi or secure, not '${MEDIUM}'" ;;
esac
[ -n "$ISO" ] || die "no ISO given (try --help)"
ISO="$(readlink -f "$ISO")"
[ -f "$ISO" ] || die "not a file: $ISO"
[ -n "$OUT_DIR" ] || die "no --out directory given (try --help)"

command -v qemu-system-x86_64 >/dev/null 2>&1 || die "qemu-system-x86_64 is not installed"
command -v python3 >/dev/null 2>&1 || die "python3 is not installed"

# The login prompt the live system prints on its serial console. The name comes from
# the same single definition of the identity as LIVE_APPEND (config/distribution.env):
# a boot that reaches this prompt reached a usable system.
EXPECT="${ASTRAOS_LIVE_HOSTNAME} login:"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/astraos-menu.XXXXXX")"
QEMU_PID=""

cleanup() {
    if [ -n "$QEMU_PID" ]; then
        kill "$QEMU_PID" 2>/dev/null || true
        wait "$QEMU_PID" 2>/dev/null || true
    fi
    if [ -n "$OUT_DIR" ]; then
        mkdir -p "$OUT_DIR"
        cp -f "$WORK/serial.log" "$OUT_DIR/serial.log" 2>/dev/null || true
        cp -f "$WORK/qemu.out" "$OUT_DIR/qemu.out" 2>/dev/null || true
        cp -f "$WORK/firmware.txt" "$OUT_DIR/firmware.txt" 2>/dev/null || true
        cp -f "$WORK/screen.ppm" "$OUT_DIR/screen.ppm" 2>/dev/null || true
    fi
    rm -rf "$WORK"
}
trap cleanup EXIT

# --- QEMU -----------------------------------------------------------------------------
# Same accelerator policy as scripts/smoke-boot.sh: -cpu host is only meaningful under
# KVM; "max" gives emulation the widest CPU it can offer.
ACCEL=(-cpu max)
if [ -w /dev/kvm ]; then
    ACCEL=(-enable-kvm -cpu host)
    say "KVM acceleration enabled"
else
    say "no usable KVM; booting under QEMU emulation (slower)"
fi

# No kernel, no initrd, no command line: the firmware finds and runs the ISO's own boot
# path, which is the whole point of this exercise.
QEMU_ARGS=(
    -m 4096 -smp 4 -vga std
    -cdrom "$ISO"
    -boot d
    -display none -no-reboot
    -serial "file:$WORK/serial.log"
    -monitor "unix:$WORK/monitor.sock,server,nowait"
)

if [ "$MEDIUM" = efi ]; then
    # OVMF's code and variable-store images are a matched pair on modern distributions,
    # and the variable store must be writable: a private copy is used, never the system
    # file. The candidate paths cover the Debian and Ubuntu layouts.
    CODE=""
    for candidate in \
        /usr/share/OVMF/OVMF_CODE_4M.fd \
        /usr/share/OVMF/OVMF_CODE.fd \
        /usr/share/edk2/x64/OVMF_CODE.4m.fd \
        /usr/share/edk2/x64/OVMF_CODE.fd
    do
        if [ -f "$candidate" ]; then
            CODE="$candidate"
            break
        fi
    done
    [ -n "$CODE" ] || die "no OVMF firmware image found; install the ovmf package"

    VARS=""
    for candidate in \
        "$(dirname "$CODE")/$(basename "$CODE" | sed 's/CODE/VARS/')" \
        /usr/share/OVMF/OVMF_VARS_4M.fd \
        /usr/share/OVMF/OVMF_VARS.fd \
        /usr/share/edk2/x64/OVMF_VARS.4m.fd \
        /usr/share/edk2/x64/OVMF_VARS.fd
    do
        if [ -f "$candidate" ]; then
            VARS="$candidate"
            break
        fi
    done

    if [ -n "$VARS" ]; then
        cp "$VARS" "$WORK/OVMF_VARS.fd"
        say "UEFI firmware: $CODE (variable store: $VARS)"
    else
        # A blank store of the right size: OVMF formats it on first boot. The
        # distribution's own VARS image is preferred; this keeps a stripped ovmf
        # package from failing the run outright.
        say "WARNING: no OVMF variable store found; using a blank one"
        truncate -s "$(stat -c%s "$CODE")" "$WORK/OVMF_VARS.fd"
    fi

    QEMU_ARGS+=(
        -drive "if=pflash,format=raw,readonly=on,file=$CODE"
        -drive "if=pflash,format=raw,file=$WORK/OVMF_VARS.fd"
    )
fi

if [ "$MEDIUM" = secure ]; then
    # Secure Boot enforcement: OVMF's secboot firmware plus the variable store with
    # the Microsoft keys pre-enrolled (the matched pair Debian and Ubuntu ship for
    # exactly this purpose). The key store is what makes this run mean something: with
    # those keys enrolled, the firmware verifies signatures for real and only the
    # ISO's signed chain - Microsoft-signed shim, Debian-signed GRUB, Debian-signed
    # kernel - can reach the login prompt. An unsigned image would be refused before
    # GRUB ran. A blank store would leave Secure Boot unenforced, so its absence is a
    # failure with its own message, not a fallback.
    CODE=""
    for candidate in \
        /usr/share/OVMF/OVMF_CODE_4M.secboot.fd \
        /usr/share/OVMF/OVMF_CODE.secboot.fd \
        /usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd \
        /usr/share/edk2/x64/OVMF_CODE.secboot.fd
    do
        if [ -f "$candidate" ]; then
            CODE="$candidate"
            break
        fi
    done
    [ -n "$CODE" ] || die "no Secure Boot OVMF firmware found; install the ovmf package"

    VARS=""
    for candidate in \
        /usr/share/OVMF/OVMF_VARS_4M.ms.fd \
        /usr/share/OVMF/OVMF_VARS.ms.fd \
        /usr/share/edk2/x64/OVMF_VARS.ms.4m.fd \
        /usr/share/edk2/x64/OVMF_VARS.ms.fd
    do
        if [ -f "$candidate" ]; then
            VARS="$candidate"
            break
        fi
    done
    [ -n "$VARS" ] || die "no Microsoft-enrolled OVMF variable store found (OVMF_VARS_4M.ms.fd or OVMF_VARS.ms.fd); a blank store leaves Secure Boot unenforced and the run would prove nothing"

    cp "$VARS" "$WORK/OVMF_VARS.fd"
    say "Secure Boot firmware: $CODE (variables with Microsoft keys: $VARS)"
    sha256sum "$CODE" "$VARS" > "$WORK/firmware.txt"
    QEMU_ARGS+=(
        -drive "if=pflash,format=raw,readonly=on,file=$CODE"
        -drive "if=pflash,format=raw,file=$WORK/OVMF_VARS.fd"
    )
fi

say "booting $ISO through the ${MEDIUM} boot menu (waiting up to ${TIMEOUT_MINUTES} min)"
qemu-system-x86_64 "${ACCEL[@]}" "${QEMU_ARGS[@]}" >"$WORK/qemu.out" 2>&1 &
QEMU_PID=$!

# --- accept the menu's default entry --------------------------------------------------
# The monitor injects Enter on the guest keyboard: syslinux and GRUB both boot the
# highlighted default when it arrives. A menu whose own timeout already booted the entry
# simply ignores the extra keypress, so sending it early and repeatedly is safe.
press_enter() {
    python3 - "$WORK/monitor.sock" <<'PY' >/dev/null 2>&1
import socket
import sys
import time

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.settimeout(10)
try:
    sock.connect(sys.argv[1])
    time.sleep(0.2)
    try:
        sock.recv(65536)  # the monitor's greeting
    except OSError:
        pass
    sock.sendall(b"sendkey ret\n")
    time.sleep(0.2)
finally:
    sock.close()
PY
}

# --- capture the guest's screen when the serial console stays silent ------------------
# A boot that fails before the kernel starts — a firmware refusing the medium under
# Secure Boot, a bootloader that never finds its configuration — draws its reason on the
# graphical console and nowhere else. Without a capture, such a failure is an empty
# serial log and a guess: exactly the shape of the first Secure Boot attempt (run
# 38924527286). QEMU's monitor can dump the guest's framebuffer; the PPM file is kept
# beside the serial log, and the cleanup below copies it out when it exists.
screendump() {
    python3 - "$WORK/monitor.sock" "$WORK/screen.ppm" <<'PY' >/dev/null 2>&1
import socket
import sys
import time

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.settimeout(10)
try:
    sock.connect(sys.argv[1])
    time.sleep(0.2)
    try:
        sock.recv(65536)  # the monitor's greeting
    except OSError:
        pass
    sock.sendall(("screendump %s\n" % sys.argv[2]).encode())
    # QEMU writes the dump from its main loop; give it a moment before closing.
    time.sleep(1.0)
finally:
    sock.close()
PY
}

# --- wait for the login prompt --------------------------------------------------------
deadline=$(( $(date +%s) + TIMEOUT_MINUTES * 60 ))
booted=no
while : ; do
    if grep -qF "$EXPECT" "$WORK/serial.log" 2>/dev/null; then
        booted=yes
        break
    fi
    if grep -qE 'BOOT FAILED!|Kernel panic' "$WORK/serial.log" 2>/dev/null; then
        # live-boot or the kernel has already given up; waiting out the rest of the
        # timeout would only delay the failure report.
        say "the boot itself failed before the login prompt"
        screendump || true
        break
    fi
    if ! kill -0 "$QEMU_PID" 2>/dev/null; then
        # QEMU is gone; there is no framebuffer left to dump.
        say "QEMU exited before the login prompt appeared"
        break
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        say "the login prompt did not appear within ${TIMEOUT_MINUTES} minutes"
        screendump || true
        break
    fi
    press_enter || true
    sleep 5
done

# --- finish ---------------------------------------------------------------------------
if [ "$booted" = yes ]; then
    prompt="$(grep -F "$EXPECT" "$WORK/serial.log" | tail -n 1 || true)"
    say "the ${MEDIUM} boot reached the live system: ${prompt}"
    if [ -n "$OUT_DIR" ]; then
        say "evidence kept in $OUT_DIR (serial.log, qemu.out; firmware.txt on the secure medium)"
    fi
    exit 0
fi

say "FAILED: no login prompt on the serial console. Last serial lines:"
tail -n 60 "$WORK/serial.log" 2>/dev/null | sed 's/^/  /' || true
if [ -f "$WORK/screen.ppm" ]; then
    say "the guest's screen was captured; it is kept as screen.ppm beside the serial log"
fi
if [ -s "$WORK/qemu.out" ]; then
    say "QEMU output:"
    tail -n 20 "$WORK/qemu.out" | sed 's/^/  /'
fi
exit 1
