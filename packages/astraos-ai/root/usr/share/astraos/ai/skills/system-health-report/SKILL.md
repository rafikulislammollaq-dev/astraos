# System Health Report

keywords: health, report, system, disk, memory, cpu, journalctl, errors, failed, network, diagnostics, slow, check, monitoring, read-only

when: the user asks whether the machine is healthy, wants a system report, or says the computer is slow or misbehaving

---

## Steps
1. Get the machine's identity: run_command `fastfetch`. It prints the kernel, the CPU model, the memory, the uptime and the graphics in one screen. If it is not installed, run_command `cat /proc/cpuinfo` for the processor and run_command `cat /proc/meminfo` for memory, which is the same information from the kernel.
2. Check the disks: run_command `df -h`. Read the `Use%` and the `Mounted on` columns. Note every filesystem above 80 percent by name.
3. Check memory: run_command `free -h`. Report `total`, `used`, `free` and the swap line. Used plus free is the total; if used is nearly the total, the machine is out of RAM and swapping.
4. Check the kernel's swapping behaviour: run_command `sysctl vm.swappiness`. A high number means the kernel moves memory to disk early, which is why a machine with free RAM can feel slow on spinning disks.
5. Check for units that failed: run_command `systemctl --failed`. This needs no root, prints nothing when nothing failed, and a listed unit is the single most useful line in the report.
6. Read this boot's errors: run_command `journalctl -p 3 -xb --no-pager`. `-p 3` is priority err and worse, `-b` is this boot, `-x` adds the explanation text, `--no-pager` prints instead of opening a pager.
7. Check the network: run_command `ip -br addr` for one line per interface and its address, then run_command `ip route` for the default route. An interface with no address is the whole problem more often than not.
8. Write the report with five headings - Machine, Disk, Memory, Services and logs, Network - and put the three things worth acting on at the top, each with the command that produced the number.
9. State plainly what you did not check and could not check. Do not fix anything: no step here changes the system. If a fix is needed, print the exact command for the user to run themselves and say that it needs their password.

## Notes

Every command in this skill is read-only. `fastfetch`, `df`, `free`, `sysctl`, `systemctl --failed`, `journalctl`, `ip` and `cat /proc/...` all only read. There is no repair action in the catalog, and this assistant never runs anything as root - it refuses `sudo`, `pkexec`, `su` and `doas` before they are executed, which is the correct behaviour and not a bug.

`df -h` sizes are rounded, so a disk at 80 percent with a "5.0G" total really is at 80 percent - do not report it as 80.1. `journalctl -p 3 -xb` prints the last boot's errors only; a machine that was rebooted since the problem started has already lost the evidence, and saying so is better than reporting a clean boot as healthy.

`systemctl --failed` is never empty on a machine with a failed unit, but a failed unit is not always the user's problem - a printer unit failing on a machine with no printer is a description of the machine, not a fault. Name the unit, say what it is, and let the user decide whether it matters.
