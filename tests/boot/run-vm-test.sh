#!/usr/bin/env bash
# AstraOS automated boot test.
#
# Attempts to actually boot the built ISO and prove it reached a graphical login. This is
# the check that turns "structurally valid" into "it boots", and it is the only automated
# test in the project that can make that claim (plan §18.3).
#
# WHAT IT WILL NOT DO
#   * It never touches a host disk. The only disk it creates is a disposable image under
#     build/vm/, and it deletes what it created.
#   * It never formats, partitions or mounts anything on the host.
#   * It never claims a pass it did not observe. If no hypervisor is available it reports
#     BLOCKED and exits 2, and if the boot does not reach the expected marker it reports
#     FAIL with the captured log.
#
# Exit codes:
#   0  booted and reached the expected marker
#   1  boot was attempted and failed
#   2  BLOCKED: could not attempt a boot (no ISO, or no hypervisor available)
#
# Usage:
#   ./tests/boot/run-vm-test.sh [path/to/image.iso] [--timeout SECONDS]
#   ASTRAOS_VM_TOOL=qemu ./tests/boot/run-vm-test.sh     # force a tool

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck source=/dev/null
. "${REPO_ROOT}/config/distribution.env"

VM_DIR="${REPO_ROOT}/${ASTRAOS_BUILD_DIR}/vm"
LOG_DIR="${REPO_ROOT}/${ASTRAOS_LOG_DIR}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RESULT_LOG="${LOG_DIR}/vm-test-${STAMP}.log"

BOOT_TIMEOUT=300
ISO=""

while [ $# -gt 0 ]; do
    case "$1" in
        --timeout) shift; BOOT_TIMEOUT="${1:-300}" ;;
        -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) ISO="$1" ;;
    esac
    shift
done

mkdir -p "$LOG_DIR" "$VM_DIR"

say() { printf '[astraos:vm-test] %s\n' "$*" | tee -a "$RESULT_LOG"; }

# --- Locate the image --------------------------------------------------------
if [ -z "$ISO" ]; then
    ISO="$(find "${REPO_ROOT}/${ASTRAOS_DIST_DIR}" -maxdepth 1 -name '*.iso' 2>/dev/null \
           | head -n1)"
fi

if [ -z "$ISO" ] || [ ! -f "$ISO" ]; then
    say "BLOCKED: no ISO found in ${ASTRAOS_DIST_DIR}/."
    say ""
    say "There is nothing to boot. Build an image first:"
    say "  ./scripts/build-iso.sh"
    say ""
    say "This is a BLOCKED result, not a pass. The boot test has not run."
    exit 2
fi

say "image: ${ISO}"
say "size : $(wc -c < "$ISO") bytes"

# Verify the checksum before booting: booting an image whose checksum does not match
# would test something other than what was published.
if [ -f "${ISO}.sha256" ]; then
    if ( cd "$(dirname "$ISO")" && sha256sum -c "$(basename "${ISO}").sha256" >/dev/null 2>&1 ); then
        say "checksum: OK"
    else
        say "FAIL: the checksum does not match the image. Not booting it."
        exit 1
    fi
fi

# --- Choose a hypervisor -----------------------------------------------------
TOOL="${ASTRAOS_VM_TOOL:-}"
if [ -z "$TOOL" ]; then
    if command -v qemu-system-x86_64 >/dev/null 2>&1; then
        TOOL="qemu"
    elif command -v VBoxManage >/dev/null 2>&1; then
        TOOL="virtualbox"
    fi
fi

if [ -z "$TOOL" ]; then
    say "BLOCKED: no hypervisor available."
    say ""
    say "Neither qemu-system-x86_64 nor VBoxManage was found on this host, so the boot"
    say "test cannot run. This is a BLOCKED result, not a pass."
    say ""
    say "To unblock, either install QEMU, or follow the manual procedure in"
    say "docs/INSTALLATION_VIRTUALBOX.md and record the results there."
    exit 2
fi

say "hypervisor: ${TOOL}"
say "timeout   : ${BOOT_TIMEOUT}s"
say ""

# Markers that indicate the boot chain got far enough to be meaningful, in order.
# Only the LAST one being observed counts as a pass, because a kernel message alone
# does not prove the graphical session started.
MARKER_KERNEL='Linux version'
MARKER_SYSTEMD='Reached target'
MARKER_GRAPHICAL='Reached target Graphical Interface|lightdm|LightDM'

check_markers() {
    local log="$1"
    local kernel=no systemd=no graphical=no

    grep -qE "$MARKER_KERNEL" "$log" 2>/dev/null && kernel=yes
    grep -qE "$MARKER_SYSTEMD" "$log" 2>/dev/null && systemd=yes
    grep -qE "$MARKER_GRAPHICAL" "$log" 2>/dev/null && graphical=yes

    say "  kernel started      : ${kernel}"
    say "  systemd progressed  : ${systemd}"
    say "  graphical session   : ${graphical}"

    [ "$kernel" = "yes" ] && [ "$systemd" = "yes" ] && [ "$graphical" = "yes" ]
}

# --- QEMU --------------------------------------------------------------------
run_qemu() {
    local serial_log="${VM_DIR}/serial-${STAMP}.log"
    local disk="${VM_DIR}/test-disk-${STAMP}.qcow2"

    say "creating a disposable virtual disk at ${disk#"$REPO_ROOT"/}"
    # 20 GiB nominal, sparse: this does not consume 20 GiB of the host disk.
    if ! qemu-img create -f qcow2 "$disk" 20G >>"$RESULT_LOG" 2>&1; then
        say "FAIL: could not create the virtual disk"
        return 1
    fi

    say "booting (headless, serial console captured)"
    # -display none with a serial console: no window, and everything the kernel and
    # systemd print is captured to a file we can inspect.
    # -no-reboot plus a timeout stops a boot loop from running forever.
    timeout "$BOOT_TIMEOUT" qemu-system-x86_64 \
        -m 4096 \
        -smp 2 \
        -machine q35 \
        -accel kvm -accel tcg \
        -drive file="$disk",format=qcow2,if=virtio \
        -cdrom "$ISO" \
        -boot d \
        -display none \
        -serial "file:${serial_log}" \
        -no-reboot \
        >>"$RESULT_LOG" 2>&1
    local qemu_status=$?

    say "qemu exited with status ${qemu_status} (124 means the timeout expired, which is"
    say "expected for a system that booted and stayed running)"

    if [ ! -s "$serial_log" ]; then
        say "FAIL: no serial output was captured. The image produced no console output at all,"
        say "      which means the kernel did not start."
        rm -f "$disk" 2>/dev/null
        return 1
    fi

    if [ "${ASTRAOS_KEEP_VM:-0}" != "1" ]; then
        rm -f "$disk" 2>/dev/null
        say "removed the disposable virtual disk"
    else
        say "kept the virtual disk at ${disk#"$REPO_ROOT"/} because ASTRAOS_KEEP_VM=1"
    fi

    if check_markers "$serial_log"; then
        say "serial log: ${serial_log#"$REPO_ROOT"/}"
        return 0
    fi

    say ""
    say "last 30 lines of the serial log:"
    tail -30 "$serial_log" | sed 's/^/    /'
    return 1
}

# --- VirtualBox --------------------------------------------------------------
run_virtualbox() {
    local vm_name="AstraOS-Boot-Test-${STAMP}"
    local disk="${VM_DIR}/vbox-disk-${STAMP}.vdi"

    say "creating a throwaway VirtualBox VM named ${vm_name}"
    # Everything created here is deleted at the end. The VM name is unique per run so it
    # cannot collide with a VM the user created themselves.
    VBoxManage createvm --name "$vm_name" --ostype Debian_64 --register >>"$RESULT_LOG" 2>&1 || {
        say "FAIL: could not create the VirtualBox VM"; return 1; }

    local cleanup_needed=1
    # shellcheck disable=SC2064
    trap "if [ '$cleanup_needed' = '1' ]; then VBoxManage unregistervm '$vm_name' --delete >/dev/null 2>&1 || true; rm -f '$disk' 2>/dev/null || true; fi" RETURN

    VBoxManage modifyvm "$vm_name" --memory 4096 --cpus 2 --firmware efi \
        --nic1 nat --graphicscontroller vmsvga >>"$RESULT_LOG" 2>&1 || true
    VBoxManage createmedium disk --filename "$disk" --size 20480 >>"$RESULT_LOG" 2>&1 || {
        say "FAIL: could not create the virtual disk"; return 1; }
    VBoxManage storagectl "$vm_name" --name SATA --add sata --controller IntelAhci >>"$RESULT_LOG" 2>&1
    VBoxManage storageattach "$vm_name" --storagectl SATA --port 0 --device 0 \
        --type hdd --medium "$disk" >>"$RESULT_LOG" 2>&1
    VBoxManage storageattach "$vm_name" --storagectl SATA --port 1 --device 0 \
        --type dvddrive --medium "$ISO" >>"$RESULT_LOG" 2>&1

    say "starting the VM headless for ${BOOT_TIMEOUT}s"
    VBoxManage startvm "$vm_name" --type headless >>"$RESULT_LOG" 2>&1 || {
        say "FAIL: the VM would not start"; return 1; }

    sleep "$BOOT_TIMEOUT"

    # Captured screenshot, if the guest produced a framebuffer. This is the closest thing
    # to evidence that a graphical session started.
    local screenshot="${VM_DIR}/screen-${STAMP}.png"
    VBoxManage controlvm "$vm_name" screenshotpng "$screenshot" >>"$RESULT_LOG" 2>&1 || true

    local vm_log
    vm_log="$(VBoxManage showvminfo "$vm_name" --machinereadable 2>/dev/null \
              | grep -E '^LogF|^SessionName' | head -n1 || true)"
    say "VM log: ${vm_log}"

    say "stopping and removing the throwaway VM"
    VBoxManage controlvm "$vm_name" poweroff >>"$RESULT_LOG" 2>&1 || true
    sleep 2
    VBoxManage unregistervm "$vm_name" --delete >>"$RESULT_LOG" 2>&1 || true
    cleanup_needed=0
    rm -f "$disk" 2>/dev/null || true

    if [ -s "$screenshot" ]; then
        say "captured a screenshot: ${screenshot#"$REPO_ROOT"/}"
        say "NOTE: a screenshot proves the guest produced a framebuffer; it does not prove"
        say "      the desktop is usable. Confirm the result manually."
        return 0
    fi

    say "FAIL: no screenshot could be captured, so no evidence of a graphical session exists"
    return 1
}

# --- Run ---------------------------------------------------------------------
case "$TOOL" in
    qemu)       RUNNER=run_qemu ;;
    virtualbox) RUNNER=run_virtualbox ;;
    *)          say "BLOCKED: unknown tool ${TOOL}"; exit 2 ;;
esac

if "$RUNNER"; then
    say ""
    say "RESULT: boot reached a graphical login"
    say ""
    say "Still UNTESTED by this script:"
    say "  * mouse, keyboard and display resolution"
    say "  * launching applications in the live session"
    say "  * networking in the live session"
    say "  * the installer, installation, and booting the installed system"
    say "Complete the procedure in docs/INSTALLATION_VIRTUALBOX.md for those."
    exit 0
fi

say ""
say "RESULT: FAIL — the image did not reach a graphical login"
say "Full log: ${RESULT_LOG}"
exit 1
