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
# The tablet is named so the driver can address it: input events are sent to this exact
# device, not to "whatever pointer QEMU picks first".
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
#   The pointer is driven with absolute axes through input-send-event, addressed to the
#   named usb-tablet. The human monitor cannot express that: HMP's mouse_move is a
#   RELATIVE move (hmp_mouse_move queues qemu_input_queue_rel) delivered to whichever
#   pointer registered first - the i8042 PS/2 mouse, which this machine also has and
#   which the live session's X server does not read, because libinput prefers the
#   absolute tablet. Run 39049818027 spent its whole 45-minute budget that way: every
#   "absolute" coordinate went out as a thousand-pixel delta, the pointer pinned itself
#   to a screen corner, and the wizard never left its Welcome page. The evidence is the
#   screenshots - 02 through 09 are the same page with a different clock. So the
#   transport is QMP, every command's reply is checked, and the walk proves it moved.
import hashlib
import json
import os
import socket
import sys
import time

serial_path, monitor_path, shots_dir, done_path = sys.argv[1:5]
password = os.environ.get("INSTALL_TEST_PASSWORD", "")
# Must match the -device usb-tablet,id=... on the phase-1 QEMU command line above.
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
    """Locate the Calamares client area in a screendump (a P6 PPM).

    The window's content is the only large light region on the screen: the desktop,
    the title bar and the installer's sidebar are all dark. The longest run of light
    pixels is measured per row; the first and last rows whose run exceeds 500 pixels
    bound the client area vertically, and the largest run's end is its right edge (the
    sidebar covers the left part of every row, so the run never reaches the client's
    left edge). Returns {"top", "bottom", "right"} with bottom/right one pixel past
    the edge, or None when nothing qualifies.
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
    top = bottom = right = None
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
    if top is None:
        return None
    return {"top": top, "bottom": bottom, "right": right}


def client_digest(path, rect):
    """A fingerprint of the client area alone (a P6 PPM), or None if it cannot be read.

    The region the wizard occupies, hashed: two dumps that agree on this are the same
    page, however much the desktop around them (the clock, a blinking cursor) has moved
    on. That is the difference between "the clicks did nothing" and "the screen is not
    frozen", which a whole-screen byte comparison cannot tell apart.
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
    left, right = 0, min(rect["right"], width)
    top = max(0, rect["top"])
    bottom = min(rect["bottom"], height)
    digest = hashlib.sha256()
    for y in range(top, bottom):
        start = pos + y * stride + left * 3
        digest.update(data[start:start + (right - left) * 3])
    return digest.hexdigest()


def pointer_to(x, y):
    """Put the pointer at a screen position, absolutely, on the tablet.

    These are the coordinates the driver means: the pixel column and row. Sent as "abs"
    to the named device, they mean the same thing on the wire that they mean here.
    """
    return qmp(
        "input-send-event",
        {
            "device": TABLET,
            "events": [
                {"type": "abs", "data": {"axis": "x", "value": x}},
                {"type": "abs", "data": {"axis": "y", "value": y}},
            ],
        },
        pause=0.4,
    )


def click(x, y):
    """Move, then press, then release - three commands, as the tablet wants them.

    The press and the release are separate so the guest is given a real interval
    between them; a single batch arrives as one transition and some toolkits read a
    zero-length press as no press at all.
    """
    if pointer_to(x, y) is None:
        return False
    down = qmp(
        "input-send-event",
        {"device": TABLET, "events": [{"type": "btn", "data": {"down": True, "button": "left"}}]},
        pause=0.2,
    )
    if down is None:
        return False
    return qmp(
        "input-send-event",
        {"device": TABLET, "events": [{"type": "btn", "data": {"down": False, "button": "left"}}]},
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

# Qt's first window on an emulated CPU takes a while; the driver prints its marker
# before the process starts, so wait past startup rather than racing it.
time.sleep(60)
shot("01-welcome")

# The client area carries every click target. Locate it in the welcome screendump
# rather than assuming a screen position: the window manager decides where the window
# goes. Calamares itself fixes the size - its own minimum is 1024x520 and the branding
# pin (windowExpanding: noexpand, windowSize: 800px,520px) is clamped up to it - so
# only the origin has to be found. The 1153/170/690 fallback values are the ones
# measured on run 39024106426's screenshots, used only if the detection finds nothing
# plausible.
client = client_rect(shot_path("01-welcome"))
if client is None or abs(client["right"] - 1153) > 40 or abs(client["top"] - 170) > 40:
    say("client-area detection implausible (%s); using the recorded values" % client)
    client = {"top": 170, "bottom": 690, "right": 1153}
else:
    say("client area: top %(top)d bottom %(bottom)d right %(right)d" % client)

# The wizard's buttons are anchored to the client area's bottom-right corner: Next
# spans its 59x23 there, and (right-151, bottom-20) is its centre. Every offset below
# was measured on run 39024106426's screenshots and reproduced against a local
# Calamares 3.3.14 on the same Qt (under Xvfb) to within two pixels.
next_at = (client["right"] - 151, client["bottom"] - 20)
say("Next button target: %d,%d" % next_at)

# What the wizard looks like before it is touched: the reference the walk is judged
# against, so that "the clicks did nothing" is a measurement rather than an assumption.
welcome_digest = client_digest(shot_path("01-welcome"), client)

# Pages whose defaults are already correct are simply clicked through. The partition
# page arrives with the one blank disk already selected and Erase pre-selected
# (initialPartitioningChoice in the CI seed), and the summary page has no confirmation
# prompt to tick (SummaryViewStep::isNextEnabled is unconditionally true in the pinned
# Calamares).
for name, settle in (("02-locale", 10.0), ("03-keyboard", 10.0),
                     ("04-partition", 12.0), ("05-users", 12.0)):
    click(*next_at)
    time.sleep(settle)
    shot(name)

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

click(*next_at)
time.sleep(12.0)
shot("08-summary")

# The summary page's Next is relabelled Install; the button grows leftwards from its
# fixed right edge, so the same target still lands inside it.
click(*next_at)
time.sleep(15.0)
shot("09-install")

# PROVE THE POINTER MOVED, instead of assuming it did. Run 39049818027 clicked eleven
# times and the wizard was still on Welcome when the budget ran out; the driver had no
# way to notice, so the verdict could only be "the installer never wrote its report".
# The panel's clock is inside the compared region and changes every minute, so the
# whole-screen bytes never match; the client area's are hashed instead, and that region
# is the wizard itself. Unchanged across the whole walk means the clicks changed
# nothing - so stop now, name it, and let the host judge it in seconds.
walk_digest = client_digest(shot_path("09-install"), client)
if walk_digest is not None and walk_digest == welcome_digest:
    say("the wizard's client area is unchanged from the welcome page after the whole "
        "walk: the clicks did not register (pointer input is not reaching the guest)")
    sys.exit(0)
say("the wizard moved off the welcome page; the click walk registered")

# The installation itself (unpacking the image onto an emulated disk) is the long part.
# One screendump per minute until the guest writes its report; the report, not the
# pictures, is the pass condition. No clicks are sent while the exec page is up: there
# is nothing there to press, and a stray click could cancel the install.
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
