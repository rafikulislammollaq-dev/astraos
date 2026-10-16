#!/usr/bin/env bash
# Boot a built AstraOS ISO in QEMU and run its boot self-test.
#
# WHAT THIS DOES
#   1. reads the live kernel and initrd out of the ISO (read-only loop mount);
#   2. boots them in QEMU with the ISO attached as a CD-ROM. The live parameters mirror
#      LIVE_APPEND in config/live-build/auto/config (whose values come from
#      config/distribution.env), with a serial console and astraos.ci=1 added (the
#      switch the image's self-test unit conditions on). The medium is found by
#      live-boot's own device scan - nothing tells the guest where the squashfs is;
#   3. waits for "ASTRAOS-SMOKE: RESULT:" on the serial console - or gives up as soon as
#      the console shows the boot itself failed;
#   4. takes a screenshot of the booted desktop through the QEMU monitor, so a build
#      leaves behind a picture of what a person would have seen;
#   5. exits 0 only when the image reported PASS.
#
# The workflow .github/workflows/build-iso.yml runs this against the ISO it has just
# built; a person runs it against any built ISO. It is documented in docs/BUILDING.md,
# "The boot self-test".
#
# Requirements: qemu-system-x86_64, python3, an image built by this repository, and root
# (or sudo) for the loop mount. KVM is used when the host allows it; QEMU emulation is
# the fallback - slower, not different.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=/dev/null
. "${REPO_ROOT}/config/distribution.env"

TIMEOUT_MINUTES=25
OUT_DIR=""
ISO=""

usage() {
    cat <<'USAGE'
Usage: scripts/smoke-boot.sh [--timeout MINUTES] [--out DIR] ISO

Boots a built AstraOS ISO in QEMU with its own live parameters plus a serial console
and "astraos.ci=1" (the switch the image's self-test conditions on), waits for the
image to report "ASTRAOS-SMOKE: RESULT:", takes a screenshot of the booted desktop
through the QEMU monitor, and exits 0 only on PASS.

  --timeout MINUTES  how long to wait for the self-test (default 25)
  --out DIR          copy serial.log, screenshot.png and qemu.out there
  -h, --help         this text
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --timeout)
            TIMEOUT_MINUTES="$2"
            shift 2
            ;;
        --out)
            OUT_DIR="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -*)
            printf 'smoke-boot: unknown option: %s\n' "$1" >&2
            exit 2
            ;;
        *)
            ISO="$1"
            shift
            ;;
    esac
done

die() {
    printf 'smoke-boot: %s\n' "$*" >&2
    exit 1
}

say() { printf 'smoke-boot: %s\n' "$*"; }

[ -n "$ISO" ] || die "no ISO given (try --help)"
ISO="$(readlink -f "$ISO")"
[ -f "$ISO" ] || die "not a file: $ISO"

command -v qemu-system-x86_64 >/dev/null 2>&1 || die "qemu-system-x86_64 is not installed"
command -v python3 >/dev/null 2>&1 || die "python3 is not installed"

# sudo only when it is needed; a root shell (the CI runner, the build container) skips it.
# An array rather than a string: the expansion stays quoted, which matters to anything
# that reads this script later (shellcheck SC2086).
if [ "$(id -u)" -eq 0 ]; then
    SUDO=()
elif command -v sudo >/dev/null 2>&1; then
    SUDO=(sudo)
else
    die "reading the ISO needs root or sudo"
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/astraos-smoke.XXXXXX")"
QEMU_PID=""

cleanup() {
    if [ -n "$QEMU_PID" ]; then
        kill "$QEMU_PID" 2>/dev/null || true
    fi
    if mountpoint -q "$WORK/iso" 2>/dev/null; then
        "${SUDO[@]}" umount "$WORK/iso" || true
    fi
    if [ -n "$OUT_DIR" ]; then
        mkdir -p "$OUT_DIR"
        cp -f "$WORK/serial.log" "$OUT_DIR/serial.log" 2>/dev/null || true
        cp -f "$WORK/qemu.out" "$OUT_DIR/qemu.out" 2>/dev/null || true
        if [ -f "$WORK/screen.png" ]; then
            cp -f "$WORK/screen.png" "$OUT_DIR/screenshot.png"
        elif [ -f "$WORK/screen.ppm" ]; then
            cp -f "$WORK/screen.ppm" "$OUT_DIR/screenshot.ppm"
        fi
    fi
    rm -rf "$WORK"
}
trap cleanup EXIT

# --- 1. the live kernel and initrd ---------------------------------------------------
mkdir -p "$WORK/iso"
"${SUDO[@]}" mount -o loop,ro "$ISO" "$WORK/iso" || die "cannot mount $ISO read-only"
KERNEL="$(ls "$WORK/iso"/live/vmlinuz* 2>/dev/null | head -n 1 || true)"
INITRD="$(ls "$WORK/iso"/live/initrd* 2>/dev/null | head -n 1 || true)"
if [ -z "$KERNEL" ] || [ -z "$INITRD" ]; then
    die "the ISO has no live/vmlinuz* + live/initrd* (is it really an AstraOS ISO?)"
fi
cp "$KERNEL" "$WORK/vmlinuz"
cp "$INITRD" "$WORK/initrd.img"
"${SUDO[@]}" umount "$WORK/iso"
say "live kernel: $(basename "$KERNEL")"

# --- 2. the kernel command line ------------------------------------------------------
# Mirrors LIVE_APPEND in config/live-build/auto/config (same values, from
# config/distribution.env), with the serial console and the self-test switch appended. If
# the two diverge, this test boots a different system than the ISO's own boot entry
# would have - and the difference is invisible.
#
# DO NOT ADD findiso HERE. An earlier version passed findiso=/live/filesystem.squashfs,
# believing it named the squashfs inside the medium. It does not: live-boot's findiso
# names an ISO *file* on a filesystem, and the guest loop-mounts exactly that file and
# reads it as ISO9660. Given the squashfs path, the guest loop-mounted the squashfs,
# isofs rejected it ("Unable to identify CD-ROM format") and live-boot reported "Unable
# to find a medium containing a live file system" - the first CI boot attempt, run
# 38864588609 on 2026-10-16, died in the initramfs for exactly this reason. A CD-ROM
# medium needs no hint: live-boot's own scan finds it, which is also how the ISO's own
# boot entry finds it. tests/static/test_smoke_boot.py keeps findiso out of this file.
APPEND="boot=live components"
APPEND="$APPEND username=${ASTRAOS_LIVE_USER}"
APPEND="$APPEND user-fullname=${ASTRAOS_LIVE_FULLNAME}"
APPEND="$APPEND hostname=${ASTRAOS_LIVE_HOSTNAME}"
APPEND="$APPEND locales=en_US.UTF-8"
APPEND="$APPEND keyboard-layouts=us keyboard-variant= timezone=UTC"
APPEND="$APPEND live-config.hostname=${ASTRAOS_LIVE_HOSTNAME}"
APPEND="$APPEND quiet splash"
APPEND="$APPEND console=ttyS0,115200n8 astraos.ci=1"

# --- 3. QEMU --------------------------------------------------------------------------
# -cpu host is only meaningful under KVM; `max` gives the guest the widest CPU that
# emulation can offer.
ACCEL=(-cpu max)
if [ -w /dev/kvm ]; then
    ACCEL=(-enable-kvm -cpu host)
    say "KVM acceleration enabled"
else
    say "no usable KVM; booting under QEMU emulation (slower)"
fi

say "booting $ISO (self-test timeout ${TIMEOUT_MINUTES} min)"
# The first TCG attempt (run 38871459329) never reported a result - its self-test unit
# was skipped by an ordering cycle - and the first green run (38881934636) clocked the
# emulated boot: login prompt at ~144 s. Emulated boot is the CI path, so give the guest
# what the runner can spare - four cores and 4 GiB let the parallel boot actually run in
# parallel, and zram is not asked to make up for a memory shortage a test can simply
# avoid.
qemu-system-x86_64 "${ACCEL[@]}" \
    -m 4096 -smp 4 -vga std \
    -cdrom "$ISO" \
    -kernel "$WORK/vmlinuz" -initrd "$WORK/initrd.img" -append "$APPEND" \
    -nic user,model=e1000 \
    -display none -no-reboot \
    -serial "file:$WORK/serial.log" \
    -monitor "unix:$WORK/monitor.sock,server,nowait" \
    >"$WORK/qemu.out" 2>&1 &
QEMU_PID=$!

# --- 4. wait for the self-test result --------------------------------------------------
deadline=$(( $(date +%s) + TIMEOUT_MINUTES * 60 ))
result=""
while : ; do
    if grep -q 'ASTRAOS-SMOKE: RESULT:' "$WORK/serial.log" 2>/dev/null; then
        result="$(grep 'ASTRAOS-SMOKE: RESULT:' "$WORK/serial.log" | tail -n 1)"
        break
    fi
    if grep -qE 'BOOT FAILED!|Kernel panic' "$WORK/serial.log" 2>/dev/null; then
        # live-boot or the kernel has already given up; waiting out the rest of the
        # timeout would only delay the failure report.
        say "the boot itself failed before the self-test could run"
        break
    fi
    if ! kill -0 "$QEMU_PID" 2>/dev/null; then
        say "QEMU exited before the self-test finished"
        break
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        say "the self-test did not finish within ${TIMEOUT_MINUTES} minutes"
        break
    fi
    sleep 5
done

# --- 5. a picture of the booted system -------------------------------------------------
# The guest holds the desktop for this after reporting its result.
if [ -n "$result" ] && kill -0 "$QEMU_PID" 2>/dev/null; then
    python3 - "$WORK/monitor.sock" "$WORK/screen.ppm" <<'PY'
import socket
import sys
import time

sock_path, shot_path = sys.argv[1], sys.argv[2]
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(sock_path)
time.sleep(0.5)
s.recv(65536)  # the monitor's greeting
s.sendall(("screendump %s\n" % shot_path).encode())
time.sleep(3.0)  # the write is asynchronous
s.close()
PY
    if [ -f "$WORK/screen.ppm" ] && command -v convert >/dev/null 2>&1; then
        convert "$WORK/screen.ppm" "$WORK/screen.png" || true
    fi
fi

# --- 6. finish ------------------------------------------------------------------------
if kill -0 "$QEMU_PID" 2>/dev/null; then
    # The guest powers itself off after the self-test; give it a moment to do so before
    # pulling the plug.
    for _ in $(seq 1 24); do
        kill -0 "$QEMU_PID" 2>/dev/null || break
        sleep 5
    done
    kill "$QEMU_PID" 2>/dev/null || true
    wait "$QEMU_PID" 2>/dev/null || true
    QEMU_PID=""
fi

echo
say "self-test output:"
grep 'ASTRAOS-SMOKE:' "$WORK/serial.log" 2>/dev/null | sed 's/^/  /' || true
echo

if [ -z "$result" ]; then
    say "FAILED: the image never reported a result. Last serial lines:"
    tail -n 40 "$WORK/serial.log" 2>/dev/null | sed 's/^/  /' || true
    if [ -s "$WORK/qemu.out" ]; then
        say "QEMU output:"
        tail -n 20 "$WORK/qemu.out" | sed 's/^/  /'
    fi
    exit 1
fi

case "$result" in
    *"RESULT: PASS"*)
        say "the image booted, reached the desktop, and passed its self-test"
        say "$result"
        if [ -n "$OUT_DIR" ]; then
            say "evidence kept in $OUT_DIR (serial.log, screenshot.png, qemu.out)"
        fi
        exit 0
        ;;
    *)
        say "FAILED: $result"
        exit 1
        ;;
esac
