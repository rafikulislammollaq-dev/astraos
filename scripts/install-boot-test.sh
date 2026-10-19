#!/usr/bin/env bash
# Install a built AstraOS ISO onto a blank disk in QEMU, then boot that disk alone.
#
# WHAT THIS DOES
#   Phase 1 - install. The ISO's live kernel boots with "astraos.ci.install=1" on its
#   command line (the exact switch the image's install driver, astraos-install,
#   conditions on - deliberately not the self-test's "astraos.ci=1"). The driver
#   copies CI-only module presets out of a 9p share this script fills, asks for a
#   fixed window geometry (Calamares clamps it to its own 1024x520 minimum), and
#   starts the real Calamares UI. This script drives that UI over the QEMU monitor:
#   the Next button is clicked through the pages whose defaults are already correct
#   (locale, keyboard, the partition page - the one blank disk arrives selected with
#   Erase pre-selected - and the summary, whose Next is unconditionally enabled), and
#   the users page gets the generated password typed into its two password fields.
#   Return cannot do this: Calamares 3.3's ViewManager never designates a default
#   button, so a Return press reaches nothing, and run 39024106426 measured a whole
#   walk of Return presses that left the wizard on its first page. That run's other
#   two lessons are in the driver now too: the window is never 800x520 (the minimum
#   wins), and the users page's two password fields sit side by side, not stacked.
#   Every step starts with a screendump, so a coordinate that is wrong is visible in
#   the evidence instead of being guessed about. The pass condition is not the
#   pictures: the driver reports into the share ("done": rc=<n>) and the structural
#   log must mention the destructive modules.
#
#   POINTER INPUT - WHY QMP, AND WHY THE DRIVER CHECKS ITS OWN WORK
#     The driver speaks QMP, not the human monitor, because HMP cannot express an
#     absolute pointer position. HMP's mouse_move is a RELATIVE move, and it is
#     delivered to whichever pointer device registered first - the i8042 PS/2 mouse
#     that every PC machine has - while the live session's X server follows the
#     absolute usb-tablet instead. So a click aimed at Next (1002, 670) went out as
#     "move a thousand pixels right, six hundred down", the pointer slammed into a
#     screen corner, and nothing the driver did afterwards could matter.
#
#     Run 39049818027 (2026-10-17) measured the cost: eleven clicks and 45 minutes
#     later the wizard was still on its Welcome page, and every screenshot from 02
#     onward was that same page with a different clock in the panel. Nothing in the
#     verdict could say so - the only question the host could answer was whether the
#     guest wrote its report, and it had not, so the run reported "the installer
#     never wrote its report" and said nothing about why.
#
#     Three things follow, and all three are in the driver now:
#       * pointer moves are QMP input-send-event "abs" events addressed to the named
#         usb-tablet, so the coordinates mean what they say and reach the device the
#         guest is actually reading;
#       * every QMP reply is checked, so a refused command is named in the evidence
#         instead of passing silently - the HMP driver could not tell the difference
#         between a delivered click and a dropped one;
#       * the walk measures its own effect: the client area of the first and last
#         screendumps are hashed, and if the wizard has not changed by the end of it,
#         the driver stops and the host is told, in about two minutes, what an
#         unresponsive pointer costs instead of 45.
#
#   ...and one QMP trap, on the same subject
#     Naming the device on each input event ("device": the tablet's id) is the obvious
#     way to be explicit, and it aborts QEMU. Run 39103628321 got all the way to the
#     first click and died there: qemu1.out holds nothing but
#
#         Unexpected error in object_property_find_err() at qom/object.c:1329:
#         Property 'qemu-fixed-text-console.device' not found
#
#     because resolving a device walks the consoles, and the fixed text console that
#     -vga std creates has no "device" property to find. The events therefore carry no
#     device, which is not a retreat: QEMU's rule for an omitted one is that only
#     devices with no input routing are admissible, and the tablet is this machine's
#     only absolute pointer, so an "abs" event has exactly one possible home. Which
#     device that is, and whether it is the current one, is no longer inferred from
#     QEMU's internals - query-mice writes every pointer it knows about to ui.log
#     before the first click.
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
ISO's own Calamares UI, driven over the QEMU monitor: the Next button is clicked
through the pages whose defaults are already correct, and the generated password is
typed into the users page. The installed disk is then booted alone and its self-test
must pass in its installed mode. Exits 0 only when both halves proved what they claim.

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
# (select the disk, then Erase) is stated here. The shipped statement for each of these
# keys was commented out above, so each key appears exactly once in this copy.
#
# `erase`, and not `eraseDisk`. Calamares 3.3's Config::installChoiceNames() holds
# exactly
#     none, nochoice, alongside, erase, replace, manual
# and installChoiceNames().find() returns the FIRST entry of that table for a name that
# is not in it - "none", meaning no choice - and for this key, unlike the swap key three
# lines below it in Config.cpp, the fallback is silent. So `eraseDisk` was accepted
# without a word and meant "nothing is selected", which is what run 39222797247's own
# Calamares log records:
#
#     InstallChoice Config::NoChoice "none"
#     bool ChoicePage::calculateNextEnabled() const
#     No partitioning choice has been made yet
#
# A partition page with no choice made is a partition page whose Next button is
# disabled, and that run spent forty-four minutes clicking it.
initialPartitioningChoice: erase
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
# Ask about KVM and say what the answer was. A silent fallback to emulation is
# expensive: run 39105685521 spent 48 minutes installing where the machine's own
# hardware virtualisation was available the whole time, and the only reason it was not
# used is that /dev/kvm is root:kvm while the runner user is not in the kvm group, so a
# plain writability test said no. Name the cause, and name the cure.
ACCEL=(-cpu max)
if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    ACCEL=(-enable-kvm -cpu host)
    say "KVM acceleration enabled"
elif [ -e /dev/kvm ]; then
    say "KVM exists but is not usable by $(id -un) ($(ls -ld /dev/kvm 2>/dev/null));"
    say "  booting under QEMU emulation, which is several times slower."
    say "  On a CI runner, 'sudo chmod 666 /dev/kvm' before this script makes it usable."
else
    say "no /dev/kvm on this machine; booting under QEMU emulation (slower)"
fi

say "creating a blank 20 GiB disk"
qemu-img create -f qcow2 "$WORK/disk.qcow2" 20G

say "phase 1: booting the live medium to install it onto the blank disk"
# The tablet is named so that it can be told apart from the PS/2 mouse this machine
# also has, in QEMU's own reporting and in qemu1.out if anything goes wrong. The driver
# does NOT address events to it by name - naming a device aborts QEMU here, which is
# the second lesson in the header's POINTER INPUT section.
TABLET_ID=astraos-tablet
# usb-tablet is the absolute-positioning pointer the driver clicks with, and a tablet
# device needs a USB controller to attach to: without qemu-xhci before it QEMU refuses
# the device at startup ("No 'usb-bus' bus found for device 'usb-tablet'") and dies
# before the guest ever boots.
#
# QMP, NOT HMP - the monitor protocol is the fix for a bug that cost this exercise a
# 45-minute run (see the header's POINTER INPUT section). HMP's mouse_move is relative
# and lands on the PS/2 mouse; QMP's input-send-event takes abs axes and a device name,
# which is exactly what this driver means.
qemu-system-x86_64 "${ACCEL[@]}" \
    -m 4096 -smp 4 -vga std \
    -cdrom "$ISO" \
    -kernel "$WORK/vmlinuz" -initrd "$WORK/initrd.img" -append "$APPEND" \
    -drive file="$WORK/disk.qcow2",if=virtio,format=qcow2 \
    -virtfs "local,path=$WORK/seed,mount_tag=astraos-ci,security_model=none" \
    -nic user,model=e1000 \
    -display none -no-reboot \
    -serial "file:$WORK/serial1.log" \
    -qmp "unix:$WORK/monitor1.sock,server,nowait" \
    -device qemu-xhci \
    -device "usb-tablet,id=$TABLET_ID" \
    >"$WORK/qemu1.out" 2>&1 &
QEMU_PID=$!

# --- 4a. the wizard driver -------------------------------------------------------------
# One screendump before every action; the pass condition stays the guest's own report.
mkdir -p "$WORK/shots"
cat > "$WORK/drive-ui.py" <<'PY'
# Drives the live installer's Calamares window over QEMU's QMP socket. The Next button
# is clicked through every page whose defaults are already correct (Calamares never
# marks a default button, so Return does nothing), and the users page gets the
# generated password typed into its two password fields. Every step starts with a
# screendump, so a wrong coordinate is visible in the evidence instead of being guessed
# about; the client area is located in the first one, because the window's position is
# the window manager's to decide.
#
# WHY QMP AND NOT HMP
#   The pointer is driven with absolute axes through input-send-event. The human monitor
#   cannot express an absolute position at all: HMP's mouse_move is a RELATIVE move
#   (hmp_mouse_move queues qemu_input_queue_rel) delivered to whichever pointer
#   registered first - the i8042 PS/2 mouse, which this machine also has - so run
#   39049818027's every coordinate went out as a thousand-pixel delta, the pointer pinned
#   itself to a screen corner, and the wizard never left its Welcome page for the whole
#   budget. The evidence was the screenshots: 02 through 09, the same page with a
#   different clock. So the transport is QMP and every command's reply is checked.
#
#   Three things about QMP's input path then have to be right, and each was wrong once.
#   None of them failed loudly, because QEMU accepts all three:
#
#     * An absolute axis is NOT in pixels. The pointer addresses the surface in
#       0..0x7FFF (include/ui/input.h's INPUT_EVENT_ABS_MIN/MAX), qmp_input_send_event
#       passes an "abs" value through unscaled, and hw/input/hid.c assigns it straight to
#       the pointer. Run 39105685521 sent pixels; the tablet read them as fractions of a
#       screen and put the pointer about 39x16 from the top-left corner while the driver
#       believed it was aiming at a button. to_abs() does the scaling a GUI would do.
#     * The device is chosen per event, as the first handler whose mask intersects the
#       event's type (ui/input.c). "abs" reaches the tablet because only it claims ABS.
#       "btn" reaches the PS/2 mouse, which registers first and claims BTN as well - so a
#       click needs the tablet made current first. HMP's mouse_set does exactly that, and
#       select_tablet() reaches it through human-monitor-command so this monitor can
#       stay a QMP one.
#     * Naming a device on the event itself is not the way to do it: it aborts QEMU. Run
#       39103628321 reached its first click and died there on "Property
#       'qemu-fixed-text-console.device' not found", because resolving a device walks the
#       consoles and -vga std's fixed text console has no such property.
#
#   The walk also has to prove it moved, and that proof has to hash the wizard rather
#   than the desktop. Run 39105685521's check started at x=0, so its verdict turned on a
#   wallpaper that finished painting between the two dumps: it announced that the clicks
#   had registered, and then watched a wizard stuck on Welcome for 45 minutes.
import hashlib
import json
import os
import socket
import sys
import time

serial_path, monitor_path, shots_dir, done_path = sys.argv[1:5]
password = os.environ.get("INSTALL_TEST_PASSWORD", "")
# The id given to the tablet on the phase-1 QEMU command line above, kept here only so
# the log can name the device it expects to be driving. Events are not addressed to it
# by name; see pointer_to() for why.
TABLET = "astraos-tablet"

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

# QMP is JSON, and asynchronous: the server greets with a "QMP" object, may interleave
# events at any point, and only answers a command with an object carrying "return" or
# "error". Buffering is decoded one whole JSON value at a time rather than one line,
# because a reply is a single line only while QEMU's pretty printing is off - and
# reading by line is how a driver silently desynchronises itself from the monitor.
_buffer = b""
_decoder = json.JSONDecoder()


def read_message():
    """The next QMP message, or None when the monitor closes."""
    global _buffer
    while True:
        text = _buffer.decode("utf-8", "replace").lstrip()
        if text:
            try:
                message, consumed = _decoder.raw_decode(text)
            except ValueError:
                pass  # a partial object; wait for the rest of it
            else:
                _buffer = text[consumed:].encode("utf-8")
                return message
        try:
            chunk = sock.recv(65536)
        except OSError:
            return None
        if not chunk:
            return None
        _buffer += chunk


def qmp(execute, arguments=None, pause=0.3):
    """One QMP command. Returns its "return", or None if QEMU refused it.

    The old HMP driver could not tell a rejected command from a delivered one, which is
    why a broken pointer went unreported for 45 minutes. Every failure is named here.
    """
    request = {"execute": execute}
    if arguments:
        request["arguments"] = arguments
    try:
        sock.sendall((json.dumps(request) + "\n").encode())
    except OSError:
        say("the monitor closed while sending %s" % execute)
        return None
    while True:
        message = read_message()
        if message is None:
            say("the monitor closed while waiting for %s" % execute)
            return None
        if "event" in message:
            continue  # an asynchronous event, not our answer
        if "error" in message:
            say("%s was refused: %s" % (execute, message["error"].get("desc", message["error"])))
            return None
        if "return" in message:
            time.sleep(pause)
            return message["return"]


greeting = read_message()
if greeting is None or "QMP" not in greeting:
    say("the monitor did not greet as QMP; the socket is not a -qmp one")
    sys.exit(0)
if qmp("qmp_capabilities") is None:
    say("QMP refused the capabilities handshake; no command will be sent")
    sys.exit(0)
say("QMP ready (tablet %s)" % TABLET)

# Which pointer QEMU delivers events to, and the units its absolute axes speak, are both
# read from QEMU later - by select_tablet(), once the screendumps have established the
# screen size those units are relative to. Both belong in the evidence rather than in
# somebody's memory of QEMU's input routing; see that function for what guessing costs.


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


def shot_path(name):
    return os.path.join(shots_dir, name + ".ppm")


def shot(name):
    path = shot_path(name)
    qmp("screendump", {"filename": path}, pause=2.5)
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


def client_rect(path):
    """Locate the Calamares page body in a screendump (a P6 PPM).

    The page body is the only large light region on the screen: the desktop, the title
    bar and the installer's sidebar are all dark. The longest run of light pixels is
    measured per row; the first and last rows whose run exceeds 500 pixels bound the
    body vertically, and the largest run's start and end are its left and right edges
    (the sidebar covers the left part of every row, so the run begins after the window's
    own left edge). Returns {"top", "bottom", "left", "right"} with bottom/right one
    pixel past the edge, or None when nothing qualifies.

    "left" is not decoration. It was missing until run 39105685521, and the digest that
    judges the click walk defaulted it to 0 - which swallowed the desktop as well as the
    page. That run's welcome reference was taken 25 seconds after Qt first drew, while
    the wallpaper was still unpainted; by the time the walk ended the wallpaper had been
    painted, so the two digests differed for a reason that had nothing to do with the
    wizard, the driver announced the clicks had registered, and the run then spent its
    full 45 minutes watching a wizard that never left its first page. This function knew
    the left edge all along and simply did not return it.
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None
    fields = []
    pos = 0
    while len(fields) < 4 and pos < len(data):
        while pos < len(data) and data[pos:pos + 1].isspace():
            pos += 1
        start = pos
        while pos < len(data) and not data[pos:pos + 1].isspace():
            pos += 1
        fields.append(data[start:pos])
    try:
        width, height = int(fields[1]), int(fields[2])
    except (IndexError, ValueError):
        return None
    pos += 1  # the single whitespace byte that follows maxval
    stride = width * 3
    top = bottom = left = right = None
    for y in range(height):
        row = data[pos + y * stride:pos + (y + 1) * stride]
        best = run = 0
        end = 0
        for x in range(width):
            i = x * 3
            if (row[i] + row[i + 1] + row[i + 2]) // 3 > 200:
                run += 1
                if run > best:
                    best = run
                    end = x
            else:
                run = 0
        if best > 500:
            if top is None:
                top = y
            bottom = y + 1
            if right is None or end + 1 > right:
                right = end + 1
            begin = end - best + 1
            if left is None or begin < left:
                left = begin
    if top is None:
        return None
    return {"top": top, "bottom": bottom, "left": left, "right": right}


def client_digest(path, rect):
    """A fingerprint of the page body alone (a P6 PPM), or None if it cannot be read.

    The region the wizard occupies, hashed: two dumps that agree on this are the same
    page, however much the desktop around them (the clock, a blinking cursor) has moved
    on. That is the difference between "the clicks did nothing" and "the screen is not
    frozen", which a whole-screen byte comparison cannot tell apart.

    The region starts at rect["left"], not at zero, and that is the whole point: the
    desktop is not the wizard. Hashing from zero made this the check that lied in run
    39105685521 - see client_rect() for what that cost.
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None
    fields = []
    pos = 0
    while len(fields) < 4 and pos < len(data):
        while pos < len(data) and data[pos:pos + 1].isspace():
            pos += 1
        start = pos
        while pos < len(data) and not data[pos:pos + 1].isspace():
            pos += 1
        fields.append(data[start:pos])
    try:
        width, height = int(fields[1]), int(fields[2])
    except (IndexError, ValueError):
        return None
    pos += 1
    stride = width * 3
    left, right = max(0, rect["left"]), min(rect["right"], width)
    top = max(0, rect["top"])
    bottom = min(rect["bottom"], height)
    digest = hashlib.sha256()
    for y in range(top, bottom):
        start = pos + y * stride + left * 3
        digest.update(data[start:start + (right - left) * 3])
    return digest.hexdigest()


# The tablet's own units. QEMU's absolute pointers address the surface in 0..0x7FFF -
# include/ui/input.h's INPUT_EVENT_ABS_MIN/MAX - and not in pixels.
ABS_MAX = 0x7FFF


def to_abs(pixels, extent):
    """A pixel column or row, as the absolute pointer's own units.

    A GUI does this scaling before the event leaves it (qemu_input_queue_abs calls
    qemu_input_scale_axis with the surface size). A QMP client has to do it itself:
    qmp_input_send_event copies an "abs" value through untouched, and hw/input/hid.c
    assigns it straight to the pointer - hid_pointer_event's "e->xdx = evt->abs.value".

    This was wrong until run 39105685521, and wrong quietly. That run sent the pixel
    coordinates 1002 and 670 as raw logical units, and the tablet reads those as
    1002/32767 and 670/32767 of the screen: the top-left corner, about 39x16. Every
    click landed on the wallpaper while the driver believed it had aimed at a button -
    the same shape of mistake as the HMP one it replaced, and just as invisible, because
    the commands were accepted and the replies were valid.
    """
    return max(0, min(ABS_MAX, pixels * ABS_MAX // extent))


def select_tablet():
    """Make the absolute tablet the pointer QEMU delivers input events to.

    qmp_input_send_event routes each event on its own. With no device named it takes the
    first handler whose mask *intersects* the event's type (ui/input.c's
    qemu_input_find_handler), so "btn" goes to whichever device registered first and
    claims BTN - and that is the PS/2 mouse, not the USB tablet. The tablet's own mask is
    INPUT_EVENT_MASK_BTN | INPUT_EVENT_MASK_ABS (hw/input/hid.c), so it can carry a whole
    click by itself, but only from the front of the list.

    HMP's mouse_set is exactly that reordering: qemu_mouse_set() calls
    qemu_input_handler_activate(), which moves the named handler to the head. It is
    reached through human-monitor-command so the phase-1 monitor can stay a QMP one.

    Run 39105685521 is why this exists. Its query-mice line reads
    "QEMU PS/2 Mouse current=True" beside "QEMU HID Tablet current=False", and its
    clicks were therefore button events on the PS/2 mouse while every position went to
    the tablet - two devices, one click, and no complaint from either.
    """
    mice = qmp("query-mice") or []
    for entry in mice:
        say("mouse index=%s name=%s current=%s absolute=%s"
            % (entry.get("index"), entry.get("name"),
               entry.get("current"), entry.get("absolute")))
    for entry in mice:
        if not entry.get("absolute"):
            continue
        if entry.get("current"):
            say("%s is already the current pointer" % entry.get("name"))
            return True
        if qmp("human-monitor-command",
               {"command-line": "mouse_set %d" % entry["index"]}) is None:
            say("could not make %s the current pointer; its clicks will be missed"
                % entry.get("name"))
            return False
        say("%s is now the current pointer (mouse_set %d)"
            % (entry.get("name"), entry["index"]))
        return True
    say("QEMU reports no absolute pointer at all; clicks can only land wherever the "
        "relative one happens to have left the pointer")
    return False


def pointer_to(x, y):
    """Put the pointer at a pixel position, absolutely.

    x and y are pixel columns and rows - what the geometry above measures and what a
    screendump shows - and they are converted to the pointer's units here, at the
    boundary, so that nothing above has to think about them.

    The events deliberately carry no "device". Naming the tablet is the obvious way to
    be explicit and it aborts QEMU: run 39103628321 reached the first click and died
    there, with qemu1.out holding nothing but

        Unexpected error in object_property_find_err() at qom/object.c:1329:
        Property 'qemu-fixed-text-console.device' not found

    Resolving a device walks the consoles, and the fixed text console -vga std creates
    has no "device" property to find. Targeting is done by select_tablet() instead,
    which moves the tablet to the front of the handler list rather than naming it on
    every event.
    """
    return qmp(
        "input-send-event",
        {
            "events": [
                {"type": "abs", "data": {"axis": "x", "value": to_abs(x, size["w"])}},
                {"type": "abs", "data": {"axis": "y", "value": to_abs(y, size["h"])}},
            ]
        },
        pause=0.4,
    )


def click(x, y):
    """Move, then press, then release.

    The press and the release are separate so the guest is given a real interval
    between them; a single batch arrives as one transition and some toolkits read a
    zero-length press as no press at all.

    All three have to be delivered by the same device, which is why select_tablet()
    runs first. Batching them into one call would not achieve that: input-send-event
    routes each event individually, so a batch of {abs, btn} still sends the abs to one
    device and the btn to another.
    """
    if pointer_to(x, y) is None:
        return False
    down = qmp(
        "input-send-event",
        {"events": [{"type": "btn", "data": {"down": True, "button": "left"}}]},
        pause=0.2,
    )
    if down is None:
        return False
    return qmp(
        "input-send-event",
        {"events": [{"type": "btn", "data": {"down": False, "button": "left"}}]},
        pause=0.5,
    ) is not None


def type_text(text):
    # The password is lower-case letters and digits, which are QKeyCode names as they
    # stand, so each character is one send-key. Nothing is echoed into the log.
    for char in text:
        qmp("send-key", {"keys": [{"type": "qcode", "data": char}]}, pause=0.08)


say("waiting for the install driver to start Calamares")
if not wait_for("ASTRAOS-INSTALL: starting calamares", 1500, "the driver's start marker"):
    say("giving up; the serial console keeps whatever happened")
    sys.exit(0)

# The client area carries every click target. Locate it in the welcome screendump
# rather than assuming a screen position: the window manager decides where the window
# goes. Calamares itself fixes the size - its own minimum is 1024x520 and the branding
# pin (windowExpanding: noexpand, windowSize: 800px,520px) is clamped up to it - so
# only the origin has to be found. The 1153/170/690 fallback values are the ones
# measured on run 39024106426's screenshots, used only if the detection finds nothing
# plausible.
def plausible(rect):
    """A client area is believable only if it is where a 1024x520 window's would be."""
    return (rect is not None
            and abs(rect["right"] - 1153) <= 40
            and abs(rect["top"] - 170) <= 40)


# Qt's first window takes a while, and how long depends on the CPU the guest was given.
# The driver prints its marker before that process starts, so the window has to be waited
# for - but a fixed wait is the wrong instrument in both directions. Run 39103628321 shot
# 60 seconds after the marker and got a bare desktop (a 6 KB screendump, no light region
# at all), and the recorded fallback then supplied geometry with nothing in the evidence
# to check it against, which is the state this detection exists to avoid. Under the
# runner's own KVM the same window is up in a second or two, and a fixed minute is spent
# watching a page that has been ready all along. So look for it, and believe it only when
# it is where a 1024x520 window belongs.
#
# 01-welcome keeps the first look, because a bare desktop there is the evidence for why
# the wait happened at all; every retry overwrites 01b, so what survives under that name
# is the look the geometry was measured from.
welcome_shot = "01-welcome"
client = None
for attempt in range(9):
    time.sleep(5.0 if attempt else 20.0)
    if attempt:
        welcome_shot = "01b-welcome-retry"
    shot(welcome_shot)
    client = client_rect(shot_path(welcome_shot))
    if plausible(client):
        break

if plausible(client):
    say("page body: top %(top)d bottom %(bottom)d left %(left)d right %(right)d" % client)
else:
    say("page-body detection still implausible (%s); using the recorded values" % client)
    # 126 is the window's left edge on the layout these values were measured from, so
    # the fallback region is the whole window rather than the page body alone. What
    # matters is only that it excludes the desktop: a digest that reaches x=0 is not
    # measuring the wizard at all (see client_rect).
    client = {"top": 170, "bottom": 690, "left": 126, "right": 1153}

# The wizard's buttons are anchored to the client area's bottom-right corner: Next
# spans its 59x23 there, and (right-151, bottom-20) is its centre. Every offset below
# was measured on run 39024106426's screenshots and reproduced against a local
# Calamares 3.3.14 on the same Qt (under Xvfb) to within two pixels.
next_at = (client["right"] - 151, client["bottom"] - 20)
say("Next button target: %d,%d" % next_at)

# What the wizard looks like before it is touched: the reference the walk is judged
# against, so that "the clicks did nothing" is a measurement rather than an assumption.
# It is hashed from whichever welcome screendump the geometry above came from.
welcome_digest = client_digest(shot_path(welcome_shot), client)

# Before a single click: which device QEMU will deliver them to. Both previous runs
# failed here without QEMU ever complaining, so this is the one step whose absence is
# invisible - and it is the reason a "btn" event is not enough on its own.
select_tablet()

# The walk. Pages whose defaults are already correct are clicked straight through, and
# the summary page has no confirmation prompt to tick (SummaryViewStep::isNextEnabled is
# unconditionally true in the pinned Calamares) - but the partition page does not arrive
# with its choice made and cannot be clicked through at all. See the two notes below.
#
# Nothing here is believed on the strength of having been clicked: walk_next() judges
# every step by the page body's bytes, before against after.
walk_reached = [(welcome_shot, welcome_digest)]


def walk_next(name, settle):
    """Click Next, and return True only if the page afterwards is not the page before.

    Run 39222797247 is why this is not simply "click and hope". It is the first run whose
    evidence could be read past the first page, and it shows the walk never left the
    partitions page: that page arrived with no partitioning choice made, Calamares
    disables Next until one is made, and a click on a disabled button is a no-op that
    QEMU accepts without a word of complaint. The driver believed it had walked the whole
    wizard, and said so, because the only comparison it ever made was the welcome page
    against the END of the walk - and those do differ. Its frame 09-install, named for the
    page the walk thought it had reached, is the partitions page with both radio buttons
    empty; 18-exec, nine minutes later, is that same page; 19-exec onward are black.

    One extra click is allowed, for a page that is slow to draw. After that the walk stops
    and names the page it could not leave, because that is worth far more than the rest of
    the budget spent clicking at a wizard nobody can move.
    """
    before_name, before = walk_reached[-1]
    for attempt in (1, 2):
        click(*next_at)
        time.sleep(settle)
        shot(name)
        after = client_digest(shot_path(name), client)
        if after is not None and after != before:
            walk_reached.append((name, after))
            return True
        say("%s: the page body is unchanged after a click on Next; clicking once more in "
            "case the page is slow to draw" % name)
    say("%s: the wizard is still showing %s after two clicks on Next - either that page's "
        "Next is disabled, or the click is not reaching it" % (name, before_name))
    return False


for name, settle in (("02-locale", 10.0), ("03-keyboard", 10.0), ("04-partition", 12.0)):
    if not walk_next(name, settle):
        sys.exit(0)

# The partitions page is the one page that cannot be clicked through, so its choice is
# made here, on the row itself. Nothing about it depends on the seed being right: a radio
# button that is already selected stays selected when it is clicked again, so this is the
# same action whether or not `initialPartitioningChoice` took effect - which is the point,
# because that key silently meant "no choice" for as long as it read `eraseDisk`.
#
# The target is the row's LABEL, not its little radio circle: Calamares' ChoicePage makes
# each choice a QRadioButton and sets the icon on it, so the indicator, the icon and the
# text are one widget and every part of the row activates it - and the label is the part
# with room around it. The offsets are from the client area's top-left corner, measured on
# this run's own 1280x800 screendump: the 20-pixel-tall "Erase disk" row at y=239, its text
# beginning at x=413, the corner itself at 129,170.
erase_at = (client["left"] + 311, client["top"] + 69)
pointer_to(*erase_at)
shot("04a-pointer-erase")
click(*erase_at)
time.sleep(2.0)
shot("04b-erase-chosen")

if not walk_next("05-users", 12.0):
    sys.exit(0)

# The users page: identity fields are preset and protected; the password fields are the
# only thing that needs typing. Both sit on one row, side by side (upstream's
# page_usersetup.ui puts them in one HBox - the vertical stacking the old driver
# assumed never existed). Their centres are fixed offsets from the client area's top
# and right edges, measured the same way as the button. A move-only dump before each
# click shows where the pointer is going, which is the calibration record if a click
# lands wrong.
password_at = (client["right"] - 726, client["top"] + 224)
confirm_at = (client["right"] - 521, client["top"] + 224)

pointer_to(*password_at)
shot("05a-pointer-password")
click(*password_at)
type_text(password)
shot("06-password-typed")

pointer_to(*confirm_at)
shot("06a-pointer-confirm")
click(*confirm_at)
type_text(password)
shot("07-confirm-typed")

if not walk_next("08-summary", 12.0):
    sys.exit(0)

# The summary page's Next is relabelled Install; the button grows leftwards from its
# fixed right edge, so the same target still lands inside it. This step gets the longest
# settle of the walk: what follows the click that starts an installation is a page the
# job queue has to build.
if not walk_next("09-install", 20.0):
    sys.exit(0)

# Whether the pointer reached the guest at all used to be one hopeful comparison here -
# the welcome page against the end of the walk - and run 39222797247 showed how much that
# could miss. Every transition is proven as it happens now, so there is nothing left to
# check at this point: the walk cannot reach this line without having left every page it
# clicked. What the single comparison could not do was name the page it was stuck on;
# walk_next() does that, and writes it to ui.log where the host reads it.

# The installation itself is the long part - minutes rather than seconds even on the
# runner's own KVM, because it writes a 2.4 GB image onto a fresh disk and then
# configures everything it wrote. One screendump per minute until the guest writes its
# report; the report, not the pictures, is the pass condition. No clicks are sent while
# the exec page is up: there is nothing there to press, and a stray click could cancel
# the install.
#
# The one input this loop does send is a bare Shift - send-key presses and releases its
# list together, so a single "shift" is a complete keystroke that types nothing and
# leaves no modifier held. It is a KEY, and not the pointer move the previous version
# sent, for a reason the evidence gives twice: the live session blanks its own screen
# after ten minutes of quiet, a pointer MOVE does not reset that timer, and runs
# 39105685521 and 39222797247 each had their exec page go uniformly black at 19-exec and
# stay black for every frame after it - with a move sent before every single dump. Four
# hundred bytes of "the screen is off" is not evidence, and both runs lost the second
# half of what they were paid for. The pause afterwards is for the guest, which has to
# repaint before a dump is worth taking.
number = 10
deadline = time.time() + 55 * 60
exec_page = walk_reached[-1][1]
unchanged = 0
while time.time() < deadline:
    if os.path.exists(done_path):
        break
    time.sleep(60)
    qmp("send-key", {"keys": [{"type": "qcode", "data": "shift"}]}, pause=0.3)
    time.sleep(2.0)
    shot("%02d-exec" % number)
    # NOT `size`: that name is the module's screen-size dict, which shot() fills in and
    # to_abs() reads, and rebinding it here broke the very next screendump with
    # "TypeError: 'int' object does not support item assignment" (run 39230792183, one
    # minute into a healthy install, which is why the run reported a dead driver instead
    # of the bootloader failure it actually died of).
    dump_bytes = os.path.getsize(shot_path("%02d-exec" % number))
    digest = client_digest(shot_path("%02d-exec" % number), client)
    if dump_bytes < 20000:
        # A real page of this wizard is about 3.4 MB of PPM; a bare desktop was 6 KB in
        # run 39103628321 and a blanked screen about 300 bytes. Anything this small is not
        # a page, so it is said plainly rather than being read later as a hung install.
        say("%02d-exec is only %d bytes: the guest is drawing no page at all"
            % (number, dump_bytes))
    elif digest == exec_page:
        unchanged += 1
        if unchanged == 8:
            say("the installer's page has been byte-identical for eight minutes; the "
                "installation is not making progress")
        elif unchanged == 15:
            say("the installer's page has been byte-identical for fifteen minutes; "
                "giving up on it rather than spending the rest of the budget")
            break
    else:
        unchanged = 0
        exec_page = digest
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
init_failure=""
driver_failure=""
while : ; do
    if [ -s "$WORK/seed/done" ]; then
        break
    fi
    # The driver walks the wizard first and only then watches for the report. When it
    # gives up on that walk it knows something the host cannot see from the outside, and
    # the remaining budget would only be spent watching a wizard nobody is driving.
    # Run 39049818027 paid 45 minutes this way against a wizard that had never left its
    # first page. The driver logs its own reason to shots/ui.log, which is evidence.
    if [ -z "$driver_failure" ] && ! kill -0 "$UI_DRIVER_PID" 2>/dev/null; then
        wait "$UI_DRIVER_PID" 2>/dev/null || true
        driver_failure="the wizard driver stopped before the installer reported"
        say "$driver_failure; its last words were:"
        tail -n 3 "$WORK/shots/ui.log" 2>/dev/null | sed 's/^/install-boot:   /' || true
        break
    fi
    if grep -qE 'BOOT FAILED!|Kernel panic' "$WORK/serial1.log" 2>/dev/null; then
        say "the live boot itself failed before the installer could run"
        break
    fi
    # An installer that cannot initialize never draws a page: Calamares opens on
    # "Calamares Initialization Failed" and sits there, and the driver clicks its
    # pages' coordinates until the deadline. The installer streams its console
    # log into the seed share while it runs, so this failure is caught in seconds.
    # Run 38940011841 measured the 45-minute version: a settings.conf without
    # modules-search, which 0300-installer.hook.chroot now refuses to build.
    if [ -z "$init_failure" ] \
        && grep -qa 'Calamares Initialization Failed' "$WORK/seed/calamares-console.log" 2>/dev/null; then
        init_failure="Calamares failed to initialize and never drew a page"
        say "$init_failure (its console log is kept with the evidence)"
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
# log must also show the destructive modules ran. It has to be, because rc=0 does NOT mean
# the install succeeded - run 39230792183 proves it, and it also disproves what this
# comment used to claim. The bootloader job failed, Calamares put up its error page,
# nobody clicked anything, and it exited 0 on its own within seconds:
#
#   ERROR: Installation failed: "Bad main script file"
#   Calamares will quit when the dialog closes.
#   Shutting down Calamares... Finished shutdown.
#
# So the log is the only evidence that the queue reached its end, and it has to be a log
# that exists. The structured session log is preferred; Calamares' console transcript
# (`calamares -d`) is the fallback, and it carries the same `Starting job "x" ( n / 27 )`
# lines. Requiring a file that is never written would not make this exercise stricter, it
# would make it unpassable - which is exactly what happened here: this loop reported
# `unpackfs bootloader` missing from a session log that did not exist, while both names
# were sitting in the console log next to it. Which file was read is said out loud.
phase1_ok=0
if [ "$phase1_rc" = "0" ]; then
    install_log=""
    for candidate in "$WORK/seed/calamares-session.log" "$WORK/seed/calamares-console.log"; do
        if [ -s "$candidate" ]; then
            install_log="$candidate"
            break
        fi
    done
    if [ -z "$install_log" ]; then
        say "the installer exited 0 and left no Calamares log at all; there is nothing to check that against"
    else
        say "reading ${install_log##*/} for the modules that must have run"
        missing=""
        for token in unpackfs bootloader; do
            grep -q "$token" "$install_log" 2>/dev/null || missing="$missing $token"
        done
        if [ -z "$missing" ]; then
            phase1_ok=1
        else
            say "the installer exited 0 but ${install_log##*/} never mentions:$missing"
        fi
    fi
fi

problems=()
if [ -n "$init_failure" ]; then
    problems+=("phase 1: ${init_failure}")
elif [ -n "$driver_failure" ]; then
    problems+=("phase 1: ${driver_failure}")
elif [ "$phase1_ok" -ne 1 ]; then
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
if [ -n "$init_failure" ]; then
    say "the installer's console log reports:"
    grep -aE 'Found [0-9]+ modules|ERROR: Module|Initialization Failed' \
        "$WORK/seed/calamares-console.log" 2>/dev/null | head -n 6 | sed 's/^/  /' || true
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
