#!/usr/bin/env bash
# Install a built AstraOS ISO onto a blank disk in QEMU, then boot that disk alone.
#
# WHAT THIS DOES
#   Phase 1 - install. The ISO's live kernel boots with "astraos.ci.install=1" on its
#   command line (the exact switch the image's install driver, astraos-install,
#   conditions on - deliberately not the self-test's "astraos.ci=1"). The driver
#   copies CI-only module presets out of a 9p share this script fills, pins the
#   Calamares window so a remote pointer can aim at it, and starts the real
#   Calamares UI. This script drives that UI over the QEMU monitor: Return presses
#   the wizard's default button through the pages whose defaults are already correct
#   (locale, keyboard, the partition page - the one blank disk arrives selected with
#   Erase pre-selected - and the summary, whose Next is unconditionally enabled), and
#   the users page gets the generated password typed into its two password fields.
#   Every step starts with a screendump, so a coordinate that is wrong is visible in
#   the evidence instead of being guessed about. The pass condition is not the
#   pictures: the driver reports into the share ("done": rc=<n>) and the structural
#   log must mention the destructive modules.
#
#   Phase 2 - boot the result. The installed disk image is converted, loop-mounted on
#   this host, and its GRUB configuration is edited to add the serial console and the
#   installed-mode switches to every kernel line (the guest's self-test reads them
#   from /proc/cmdline). The disk then boots with no ISO attached: a real firmware
#   boot of the real installed system. The image's own self-test runs in its
#   installed mode - greeter instead of a session, no autologin, no live account,
#   the installer's lock-down verified from outside the installer - and this script
#   additionally requires the login prompt to name the installed account's hostname.
#
# WHY THE PASSWORD IS GENERATED HERE
#   The users module cannot preset a password, so the host must type one. It is
#   generated per run, passed to the typing helper through the environment, and
#   written to no file, log or artifact.
#
# Requirements: qemu-system-x86_64, qemu-img, python3, losetup, an image built by this
# repository, and root (or sudo) for the loop mounts. KVM is used when the host allows
# it; QEMU emulation is the fallback - slower, not different.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=/dev/null
. "${REPO_ROOT}/config/distribution.env"

TIMEOUT_MINUTES=40
OUT_DIR=""
ISO=""

usage() {
    cat <<'USAGE'
Usage: scripts/install-boot-test.sh [--timeout MINUTES] [--out DIR] ISO

Boots a built AstraOS ISO in QEMU and installs it onto a blank disk through the
ISO's own Calamares UI, driven over the QEMU monitor: Return advances the pages whose
defaults are already correct, and the generated password is typed into the users
page. The installed disk is then booted alone and its self-test must pass in its
installed mode. Exits 0 only when both halves proved what they claim.

  --timeout MINUTES  how long each half may take (default 40)
  --out DIR          copy the evidence there (serial logs, UI screendumps, the
                     Calamares session log, the patched grub.cfg, the greeter shot)
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
            printf 'install-boot: unknown option: %s\n' "$1" >&2
            exit 2
            ;;
        *)
            ISO="$1"
            shift
            ;;
    esac
done

die() {
    printf 'install-boot: %s\n' "$*" >&2
    exit 1
}

say() { printf 'install-boot: %s\n' "$*"; }

[ -n "$ISO" ] || die "no ISO given (try --help)"
ISO="$(readlink -f "$ISO")"
[ -f "$ISO" ] || die "not a file: $ISO"

command -v qemu-system-x86_64 >/dev/null 2>&1 || die "qemu-system-x86_64 is not installed"
command -v qemu-img >/dev/null 2>&1 || die "qemu-img is not installed"
command -v python3 >/dev/null 2>&1 || die "python3 is not installed"
command -v losetup >/dev/null 2>&1 || die "losetup is not installed"

# sudo only when it is needed; a root shell (the CI runner, the build container) skips
# it. An array rather than a string: the expansion stays quoted (shellcheck SC2086).
if [ "$(id -u)" -eq 0 ]; then
    SUDO=()
elif command -v sudo >/dev/null 2>&1; then
    SUDO=(sudo)
else
    die "loop-mounting the installed disk needs root or sudo"
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/astraos-install.XXXXXX")"
ROOT_MNT="$WORK/rootmnt"
QEMU_PID=""
QEMU2_PID=""
UI_DRIVER_PID=""
LOOP=""

cleanup() {
    if [ -n "$UI_DRIVER_PID" ]; then
        kill "$UI_DRIVER_PID" 2>/dev/null || true
    fi
    if [ -n "$QEMU_PID" ]; then
        kill "$QEMU_PID" 2>/dev/null || true
    fi
    if [ -n "$QEMU2_PID" ]; then
        kill "$QEMU2_PID" 2>/dev/null || true
    fi
    if mountpoint -q "$WORK/iso" 2>/dev/null; then
        "${SUDO[@]}" umount "$WORK/iso" || true
    fi
    if mountpoint -q "$ROOT_MNT" 2>/dev/null; then
        "${SUDO[@]}" umount "$ROOT_MNT" || true
    fi
    if [ -n "$LOOP" ]; then
        "${SUDO[@]}" losetup -d "$LOOP" 2>/dev/null || true
    fi
    if [ -n "$OUT_DIR" ]; then
        mkdir -p "$OUT_DIR/ui"
        cp -f "$WORK/serial1.log" "$WORK/serial2.log" "$WORK/qemu1.out" "$WORK/qemu2.out" \
            "$WORK/ui.out" "$OUT_DIR/" 2>/dev/null || true
        cp -f "$WORK/seed/done" "$OUT_DIR/done" 2>/dev/null || true
        cp -f "$WORK/seed/calamares-console.log" "$OUT_DIR/calamares-console.log" 2>/dev/null || true
        cp -f "$WORK/seed/calamares-session.log" "$OUT_DIR/calamares-session.log" 2>/dev/null || true
        cp -f "$WORK/seed/settings-installed.conf" "$OUT_DIR/settings-installed.conf" 2>/dev/null || true
        cp -f "$WORK/seed/configs.sha256" "$OUT_DIR/configs.sha256" 2>/dev/null || true
        cp -f "$WORK/grub-original.cfg" "$WORK/grub-patched.cfg" "$OUT_DIR/" 2>/dev/null || true
        if [ -f "$WORK/greeter.png" ]; then
            cp -f "$WORK/greeter.png" "$OUT_DIR/greeter.png"
        elif [ -f "$WORK/greeter.ppm" ]; then
            cp -f "$WORK/greeter.ppm" "$OUT_DIR/greeter.ppm"
        fi
        cp -f "$WORK"/shots/* "$OUT_DIR/ui/" 2>/dev/null || true
    fi
    rm -rf "$WORK"
}
trap cleanup EXIT

convert_shots() {
    command -v convert >/dev/null 2>&1 || return 0
    for ppm in "$WORK"/shots/*.ppm; do
        [ -f "$ppm" ] || continue
        convert "$ppm" "${ppm%.ppm}.png" 2>/dev/null && rm -f "$ppm" || true
    done
}

# --- 0. the password the wizard will be given ------------------------------------------
# Lowercase letters and digits only: the typing helper feeds QEMU's sendkey, which
# names keys by US layout ("a".."z", "0".."9"), so no modifier key and no layout
# surprise is involved. Generated here, used here, written to no file: not into the
# seed, not into the UI log, not into the evidence. The machine it protects is
# destroyed when the run ends.
PASSWORD="$(python3 - <<'PY'
import secrets
import string
print("".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(12)))
PY
)"
[ -n "$PASSWORD" ] || die "could not generate a password"
say "generated a ${#PASSWORD}-character password (typed into the wizard; written to no file)"

# --- 1. the seed: the shipped configs plus CI-only additions ---------------------------
# The guest must run on exactly the configuration the ISO carries plus this exercise's
# switches. The additions are made on COPIES of the files this repository ships, never
# edited into them - and never as duplicate keys: a YAML document cannot hold the same
# top-level key twice, and the parser silently picks one of the two values. The shipped
# partition.conf states both partitioning choices (the disk-safety rule: nobody's disk
# is erased without an active choice), so this copy comments those two lines out before
# appending the exercise's own; the shipped users.conf states neither of the keys
# appended here. A runtime check below refuses a finished copy with a repeated key:
# Calamares reads this copy as the truth.
mkdir -p "$WORK/seed/modules"

cp "$REPO_ROOT/installer/calamares/modules/partition.conf" "$WORK/seed/modules/partition.conf"
for key in initialPartitioningChoice initialSwapChoice; do
    sed -i -E "s#^${key}:.*#\\# CI install exercise replaced this line; the exercise's own choice is appended below.#" \
        "$WORK/seed/modules/partition.conf"
done
cat >> "$WORK/seed/modules/partition.conf" <<'EOF'

# --- appended by scripts/install-boot-test.sh (present only in CI) ---
# The exercise has exactly one disk and no one to ask; the choice a person would make
# (select the disk, then Erase) is made once, up front. The shipped statement for each
# of these keys - where present - was commented out above, so each key appears exactly
# once in this copy.
initialPartitioningChoice: eraseDisk
initialSwapChoice: none
EOF

cp "$REPO_ROOT/installer/calamares/modules/users.conf" "$WORK/seed/modules/users.conf"
cat >> "$WORK/seed/modules/users.conf" <<'EOF'

# --- appended by scripts/install-boot-test.sh (present only in CI) ---
# The host drives this page with keystrokes, and a fixed identity is what makes the
# finished system recognisable from the outside. Each preset is a value with an
# editable flag (the shape the users module's own documentation uses); editable: false
# has the module protect the field from later edits. The password cannot be preset -
# the module has no key for it - so the host types the generated one into the page.
presets:
    fullName:
        value: "AstraOS CI"
        editable: false
    loginName:
        value: "astraos-ci"
        editable: false
hostname:
    template: astraos-ci
EOF

# Neither copy may repeat a top-level key: a duplicated YAML key does not merge - one
# of the two values silently wins. This checks the artifact the guest will actually
# read, not the intention with which it was written.
for seed_conf in "$WORK/seed/modules/partition.conf" "$WORK/seed/modules/users.conf"; do
    repeated="$(grep -oE '^[A-Za-z][A-Za-z0-9_]*:' "$seed_conf" | sort | uniq -d | tr '\n' ' ')"
    if [ -n "$repeated" ]; then
        die "$(basename "$seed_conf") repeats the top-level key(s) ${repeated}after the CI additions; a duplicated YAML key silently picks one value"
    fi
done

# --- 2. the live kernel and initrd -----------------------------------------------------
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

# --- 3. the live kernel command line ---------------------------------------------------
# Mirrors LIVE_APPEND in config/live-build/auto/config the same way smoke-boot.sh does
# (same values, from config/distribution.env), with the serial console and the install
# switch. The switch is the exact word astraos.ci.install=1: the install driver's unit
# conditions on it, the boot self-test's unit conditions on astraos.ci=1 (the exact
# word, not the bare prefix), and a self-test that screenshots the desktop and powers
# the machine off in the middle of an install would eat the exercise. The two switches
# therefore never cross.
APPEND="boot=live components"
APPEND="$APPEND username=${ASTRAOS_LIVE_USER}"
APPEND="$APPEND user-fullname=${ASTRAOS_LIVE_FULLNAME}"
APPEND="$APPEND hostname=${ASTRAOS_LIVE_HOSTNAME}"
APPEND="$APPEND locales=en_US.UTF-8"
APPEND="$APPEND keyboard-layouts=us keyboard-variant= timezone=UTC"
APPEND="$APPEND live-config.hostname=${ASTRAOS_LIVE_HOSTNAME}"
APPEND="$APPEND quiet splash"
APPEND="$APPEND console=ttyS0,115200n8 astraos.ci.install=1"

# --- 4. QEMU, phase 1 ------------------------------------------------------------------
ACCEL=(-cpu max)
if [ -w /dev/kvm ]; then
    ACCEL=(-enable-kvm -cpu host)
    say "KVM acceleration enabled"
else
    say "no usable KVM; booting under QEMU emulation (slower)"
fi

say "creating a blank 20 GiB disk"
qemu-img create -f qcow2 "$WORK/disk.qcow2" 20G

say "phase 1: booting the live medium to install it onto the blank disk"
# usb-tablet is the absolute-positioning pointer the driver clicks with, and a tablet
# device needs a USB controller to attach to: without qemu-xhci before it QEMU refuses
# the device at startup ("No 'usb-bus' bus found for device 'usb-tablet'") and dies
# before the guest ever boots.
qemu-system-x86_64 "${ACCEL[@]}" \
    -m 4096 -smp 4 -vga std \
    -cdrom "$ISO" \
    -kernel "$WORK/vmlinuz" -initrd "$WORK/initrd.img" -append "$APPEND" \
    -drive file="$WORK/disk.qcow2",if=virtio,format=qcow2 \
    -virtfs "local,path=$WORK/seed,mount_tag=astraos-ci,security_model=none" \
    -nic user,model=e1000 \
    -display none -no-reboot \
    -serial "file:$WORK/serial1.log" \
    -monitor "unix:$WORK/monitor1.sock,server,nowait" \
    -device qemu-xhci \
    -device usb-tablet \
    >"$WORK/qemu1.out" 2>&1 &
QEMU_PID=$!

# --- 4a. the wizard driver -------------------------------------------------------------
# One screendump before every action; the pass condition stays the guest's own report.
mkdir -p "$WORK/shots"
cat > "$WORK/drive-ui.py" <<'PY'
# Drives the live installer's Calamares window over QEMU's monitor: Return advances
# every page whose defaults are already correct, and the users page gets the generated
# password typed into its two fields. Every step starts with a screendump, so a wrong
# coordinate is visible in the evidence instead of being guessed about.
import os
import socket
import sys
import time

serial_path, monitor_path, shots_dir, done_path = sys.argv[1:5]
password = os.environ.get("INSTALL_TEST_PASSWORD", "")

log = open(os.path.join(shots_dir, "ui.log"), "w", buffering=1)


def say(msg):
    log.write("ui: %s\n" % msg)


if not password:
    say("no password in the environment; refusing to drive the wizard")
    sys.exit(1)

sock = None
for _ in range(120):
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(monitor_path)
        break
    except OSError:
        sock = None
        time.sleep(1)
if sock is None:
    say("cannot reach the QEMU monitor; giving up")
    sys.exit(0)
time.sleep(0.5)
try:
    sock.recv(65536)  # the monitor's greeting
except OSError:
    pass


def hmp(command, pause=0.3):
    sock.sendall((command + "\n").encode())
    time.sleep(pause)


def serial_text():
    try:
        with open(serial_path, "rb") as handle:
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return ""


def wait_for(needle, timeout_s, what):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if needle in serial_text():
            return True
        time.sleep(3)
    say("timed out waiting for %s" % what)
    return False


size = {"w": 1280, "h": 800}


def shot(name):
    path = os.path.join(shots_dir, name + ".ppm")
    hmp("screendump %s" % path, pause=2.5)
    for _ in range(10):
        if os.path.exists(path):
            try:
                with open(path, "rb") as handle:
                    header = handle.read(64).split()
                size["w"], size["h"] = int(header[1]), int(header[2])
                break
            except (OSError, IndexError, ValueError):
                pass
        time.sleep(0.5)
    say("screendump %s (%dx%d)" % (name, size["w"], size["h"]))


def click(x, y):
    hmp("mouse_move %d %d" % (x, y), pause=0.4)
    hmp("mouse_button 1", pause=0.2)
    hmp("mouse_button 0", pause=0.5)


def type_text(text):
    for char in text:
        hmp("sendkey %s" % char, pause=0.08)


def enter(delay):
    hmp("sendkey ret", pause=delay)


say("waiting for the install driver to start Calamares")
if not wait_for("ASTRAOS-INSTALL: starting calamares", 1500, "the driver's start marker"):
    say("giving up; the serial console keeps whatever happened")
    sys.exit(0)

# Qt's first window on an emulated CPU takes a while; the driver prints its marker
# before the process starts, so wait past startup rather than racing it.
time.sleep(60)
shot("01-welcome")

# Pages whose defaults are already correct: Return presses the wizard's default button
# (Next). The partition page arrives with the one blank disk already selected and Erase
# pre-selected (initialPartitioningChoice in the CI seed), and the summary page has no
# confirmation prompt to tick (SummaryViewStep::isNextEnabled is unconditionally true
# in the pinned Calamares).
enter(10.0)
shot("02-locale")
enter(10.0)
shot("03-keyboard")
enter(12.0)
shot("04-partition")
enter(12.0)
shot("05-users")

# The users page: identity fields are preset and protected; the password fields are the
# only thing that needs typing. The window is pinned to 800x520 in the centre of the
# screen (the driver appends windowExpanding: noexpand and a fixed windowSize to the
# branding), so the fields sit at fixed offsets from the screen centre; the dumps above
# re-measure the screen for the offsets. A move-only dump before each click shows where
# the pointer is going, which is the calibration record if a click lands wrong.
x0 = (size["w"] - 800) // 2
y0 = (size["h"] - 520) // 2

hmp("mouse_move %d %d" % (x0 + 520, y0 + 300), pause=0.4)
shot("05a-pointer-password")
click(x0 + 520, y0 + 300)
type_text(password)
shot("06-password-typed")

hmp("mouse_move %d %d" % (x0 + 520, y0 + 345), pause=0.4)
shot("06a-pointer-confirm")
click(x0 + 520, y0 + 345)
type_text(password)
shot("07-confirm-typed")

enter(12.0)
shot("08-summary")
enter(15.0)
shot("09-install")

# The installation itself (unpacking the image onto an emulated disk) is the long part.
# One screendump per minute until the guest writes its report; the report, not the
# pictures, is the pass condition. No extra Return is sent while the exec page is up:
# the default button there is not Next.
number = 10
deadline = time.time() + 55 * 60
while time.time() < deadline:
    if os.path.exists(done_path):
        break
    time.sleep(60)
    shot("%02d-exec" % number)
    number += 1

if os.path.exists(done_path):
    time.sleep(5)
    shot("%02d-finished" % number)
    say("the guest wrote its report")
else:
    say("the guest never wrote its report; giving up")
PY

INSTALL_TEST_PASSWORD="$PASSWORD" python3 "$WORK/drive-ui.py" \
    "$WORK/serial1.log" "$WORK/monitor1.sock" "$WORK/shots" "$WORK/seed/done" \
    >"$WORK/ui.out" 2>&1 &
UI_DRIVER_PID=$!

# --- 5. wait for the installer's report ------------------------------------------------
deadline=$(( $(date +%s) + TIMEOUT_MINUTES * 60 ))
while : ; do
    if [ -s "$WORK/seed/done" ]; then
        break
    fi
    if grep -qE 'BOOT FAILED!|Kernel panic' "$WORK/serial1.log" 2>/dev/null; then
        say "the live boot itself failed before the installer could run"
        break
    fi
    if ! kill -0 "$QEMU_PID" 2>/dev/null; then
        say "QEMU exited before the installer reported"
        break
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        say "the installer did not finish within ${TIMEOUT_MINUTES} minutes"
        break
    fi
    sleep 10
done

# The driver reports and then powers the machine off; the disk image must not be read
# (converted, mounted) while QEMU still has it open.
if kill -0 "$QEMU_PID" 2>/dev/null; then
    for _ in $(seq 1 24); do
        kill -0 "$QEMU_PID" 2>/dev/null || break
        sleep 5
    done
    kill "$QEMU_PID" 2>/dev/null || true
fi
wait "$QEMU_PID" 2>/dev/null || true
QEMU_PID=""
if [ -n "$UI_DRIVER_PID" ]; then
    kill "$UI_DRIVER_PID" 2>/dev/null || true
    wait "$UI_DRIVER_PID" 2>/dev/null || true
    UI_DRIVER_PID=""
fi

convert_shots

phase1_rc=""
if [ -s "$WORK/seed/done" ]; then
    phase1_rc="$(sed -n 's/^rc=//p' "$WORK/seed/done" | head -n 1)"
fi

# The exit code alone is thin evidence about what happened on the disk; the structural
# log must also show the destructive modules ran. (Quitting at all is already the shape
# of success: the CI driver sets quit-at-end: true, and the wizard reaches the end of
# its sequence - and therefore quits by itself - only after the exec phase succeeded; a
# failed job stops the queue on its error page, nobody clicks anything in CI, and this
# script's deadline catches it.)
phase1_ok=0
if [ "$phase1_rc" = "0" ]; then
    missing=""
    for token in unpackfs bootloader; do
        grep -q "$token" "$WORK/seed/calamares-session.log" 2>/dev/null || missing="$missing $token"
    done
    if [ -z "$missing" ]; then
        phase1_ok=1
    else
        say "the installer exited 0 but its session log never mentions:$missing"
    fi
fi

problems=()
if [ "$phase1_ok" -ne 1 ]; then
    if [ -z "$phase1_rc" ]; then
        problems+=("phase 1: the installer never wrote its report")
    else
        problems+=("phase 1: Calamares exited rc=${phase1_rc}")
    fi
fi

# --- 6. phase 2: patch the installed system's boot, then boot the disk alone -----------
if [ "$phase1_ok" -eq 1 ]; then
    say "phase 2: patching the installed system's kernel command line"
    qemu-img convert -O raw "$WORK/disk.qcow2" "$WORK/disk.raw"
    LOOP="$("${SUDO[@]}" losetup -Pf --show "$WORK/disk.raw")"
    [ -n "$LOOP" ] || die "losetup did not return a loop device"
    for _ in $(seq 1 40); do
        ls "${LOOP}"p* >/dev/null 2>&1 && break
        sleep 0.5
    done

    # The root partition is the one whose /etc/os-release is AstraOS's; that is a fact
    # about the product, not about Calamares' partitioning choices.
    ROOT_PART=""
    mkdir -p "$ROOT_MNT"
    for part in "${LOOP}"p*; do
        [ -b "$part" ] || continue
        if "${SUDO[@]}" mount -o ro "$part" "$ROOT_MNT" 2>/dev/null; then
            if [ -f "$ROOT_MNT/etc/os-release" ] && grep -q 'AstraOS' "$ROOT_MNT/etc/os-release"; then
                ROOT_PART="$part"
                "${SUDO[@]}" umount "$ROOT_MNT"
                break
            fi
            "${SUDO[@]}" umount "$ROOT_MNT"
        fi
    done
    [ -n "$ROOT_PART" ] || die "no partition on the installed disk carries an AstraOS /etc/os-release"

    "${SUDO[@]}" mount -o rw "$ROOT_PART" "$ROOT_MNT"
    say "installed root: $ROOT_PART"
    [ -f "$ROOT_MNT/boot/grub/grub.cfg" ] || die "the installed system has no /boot/grub/grub.cfg to patch"
    "${SUDO[@]}" cp "$ROOT_MNT/boot/grub/grub.cfg" "$WORK/grub-original.cfg"

    # Every kernel line gets the serial console and the installed-mode switches; the
    # self-test reads the switches from /proc/cmdline. username= is what tells the
    # installed self-test which account name must NOT exist on the installed system.
    patch_append="console=ttyS0,115200n8 astraos.ci=1 astraos.ci.installed=1 username=${ASTRAOS_LIVE_USER}"
    "${SUDO[@]}" sed -i -E "s#^([[:space:]]*linux[[:space:]]+[^[:space:]]+.*)\$#\1 ${patch_append}#" "$ROOT_MNT/boot/grub/grub.cfg"
    "${SUDO[@]}" cp "$ROOT_MNT/boot/grub/grub.cfg" "$WORK/grub-patched.cfg"

    if ! grep -q 'astraos.ci.installed=1' "$WORK/grub-patched.cfg"; then
        die "patching grub.cfg appended nothing; the installed boot would run no self-test"
    fi
    patched_count="$(grep -c 'astraos.ci.installed=1' "$WORK/grub-patched.cfg" || true)"
    say "patched ${patched_count} kernel line(s) in the installed GRUB configuration"

    "${SUDO[@]}" sync
    "${SUDO[@]}" umount "$ROOT_MNT"
    "${SUDO[@]}" losetup -d "$LOOP"
    LOOP=""

    say "phase 2: booting the installed disk alone (no ISO attached)"
    qemu-system-x86_64 "${ACCEL[@]}" \
        -m 4096 -smp 4 -vga std \
        -drive file="$WORK/disk.raw",if=virtio,format=raw \
        -nic user,model=e1000 \
        -display none -no-reboot \
        -serial "file:$WORK/serial2.log" \
        -monitor "unix:$WORK/monitor2.sock,server,nowait" \
        >"$WORK/qemu2.out" 2>&1 &
    QEMU2_PID=$!

    # --- 7. wait for the installed system's self-test ----------------------------------
    deadline=$(( $(date +%s) + TIMEOUT_MINUTES * 60 ))
    result2=""
    while : ; do
        if grep -q 'ASTRAOS-SMOKE: RESULT:' "$WORK/serial2.log" 2>/dev/null; then
            result2="$(grep 'ASTRAOS-SMOKE: RESULT:' "$WORK/serial2.log" | tail -n 1)"
            break
        fi
        if grep -qE 'Kernel panic' "$WORK/serial2.log" 2>/dev/null; then
            say "the installed kernel panicked"
            break
        fi
        if ! kill -0 "$QEMU2_PID" 2>/dev/null; then
            say "QEMU exited before the installed self-test finished"
            break
        fi
        if [ "$(date +%s)" -ge "$deadline" ]; then
            say "the installed self-test did not finish within ${TIMEOUT_MINUTES} minutes"
            break
        fi
        sleep 5
    done

    # A picture of the greeter, taken while the guest still holds the screen after its
    # report. Same best-of-three guard as smoke-boot.sh: a flat capture (the known
    # QEMU stdvga blanking defect) is retried, and the shot with the most content is
    # the one kept.
    if [ -n "$result2" ] && kill -0 "$QEMU2_PID" 2>/dev/null; then
        attempt=1
        best=""
        best_sd=""
        while [ "$attempt" -le 3 ]; do
            python3 - "$WORK/monitor2.sock" "$WORK/greeter-$attempt.ppm" <<'PY'
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
            shot="$WORK/greeter-$attempt.ppm"
            stats=""
            if [ -f "$shot" ] && command -v convert >/dev/null 2>&1; then
                stats="$(convert "$shot" -colorspace Gray -format '%[fx:mean] %[fx:standard_deviation]' info: 2>/dev/null || true)"
            fi
            sd="$(printf '%s\n' "$stats" | awk '{print $2}')"
            say "greeter screenshot attempt ${attempt}: mean/sd = ${stats:-unknown}"
            if [ -f "$shot" ]; then
                if [ -z "$best" ] || awk -v a="$sd" -v b="$best_sd" 'BEGIN { exit (a > b) ? 0 : 1 }'; then
                    best="$shot"
                    best_sd="$sd"
                fi
                if awk -v a="$sd" 'BEGIN { exit (a > 0.01) ? 0 : 1 }'; then
                    break
                fi
            fi
            attempt=$((attempt + 1))
            sleep 2
        done
        if [ -n "$best" ]; then
            cp -f "$best" "$WORK/greeter.ppm"
            if command -v convert >/dev/null 2>&1; then
                convert "$WORK/greeter.ppm" "$WORK/greeter.png" || true
            fi
            if ! awk -v a="$best_sd" 'BEGIN { exit (a > 0.01) ? 0 : 1 }'; then
                say "WARNING: the kept greeter screenshot is a flat image (standard deviation ${best_sd:-unknown})"
            fi
        fi
    fi

    if kill -0 "$QEMU2_PID" 2>/dev/null; then
        # The guest powers itself off after the self-test; give it a moment first.
        for _ in $(seq 1 24); do
            kill -0 "$QEMU2_PID" 2>/dev/null || break
            sleep 5
        done
        kill "$QEMU2_PID" 2>/dev/null || true
    fi
    wait "$QEMU2_PID" 2>/dev/null || true
    QEMU2_PID=""

    if [ -z "$result2" ]; then
        problems+=("phase 2: the installed system never reported a result")
    else
        case "$result2" in
            *"RESULT: PASS"*) : ;;
            *) problems+=("phase 2: ${result2}") ;;
        esac
        grep -q 'ASTRAOS-SMOKE: mode: installed' "$WORK/serial2.log" 2>/dev/null \
            || problems+=("phase 2: the self-test did not run in installed mode")
        grep -q 'astraos-ci login:' "$WORK/serial2.log" 2>/dev/null \
            || problems+=("phase 2: the login prompt never showed 'astraos-ci login:'")
    fi
fi

# --- 8. the verdicts --------------------------------------------------------------------
echo
say "install driver output:"
grep 'ASTRAOS-INSTALL:' "$WORK/serial1.log" 2>/dev/null | sed 's/^/  /' || true
if [ -n "$phase1_rc" ]; then
    say "Calamares exit report: rc=${phase1_rc}"
fi
echo
say "installed system's self-test:"
grep 'ASTRAOS-SMOKE:' "$WORK/serial2.log" 2>/dev/null | sed 's/^/  /' || true
echo

if [ "${#problems[@]}" -eq 0 ]; then
    say "the ISO booted, installed itself onto a blank disk through its own installer, and the installed system booted alone, showed a greeter, and passed its self-test in installed mode"
    if [ -n "$OUT_DIR" ]; then
        say "evidence kept in $OUT_DIR (serial1.log, serial2.log, ui/, calamares-session.log, grub-patched.cfg, greeter.png)"
    fi
    exit 0
fi

for problem in "${problems[@]}"; do
    say "FAILED: ${problem}"
done
say "last lines of the first serial console:"
tail -n 40 "$WORK/serial1.log" 2>/dev/null | sed 's/^/  /' || true
echo
say "last lines of the second serial console:"
tail -n 40 "$WORK/serial2.log" 2>/dev/null | sed 's/^/  /' || true
exit 1
