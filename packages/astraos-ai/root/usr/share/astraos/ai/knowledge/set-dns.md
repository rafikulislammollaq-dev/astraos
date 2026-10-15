# Setting DNS on AstraOS

keywords: dns, resolv.conf, nameserver, networkmanager, nmcli, resolvectl, systemd-resolved, resolvconf, no internet, name resolution, dns boot parameter

On AstraOS the DNS settings come from NetworkManager and from nothing else. The image
ships `network-manager`, `network-manager-gnome`, `modemmanager` and `wpasupplicant`,
and the build deliberately ships **no** `resolvconf` package, because the two defer to
each other and leave `/etc/resolv.conf` unwritten. NetworkManager writes
`/etc/resolv.conf` itself, which is the Debian 13 way; `resolvconf` is deprecated
upstream and is not installed here. Start with `nmcli device status`: a device that is
`connected`, with a connection listed by `nmcli connection show --active`, means
NetworkManager believes it has a working path, and the question is only what it was told
to put in `resolv.conf`.

`/etc/resolv.conf` may be a symlink, and that is the first thing to check: `ls -l
/etc/resolv.conf`. On a machine where systemd-resolved is running it points at
`/run/systemd/resolve/stub-resolv.conf` (which contains the line `nameserver 127.0.0.53`),
and `resolvectl status` is the tool that shows which DNS servers resolved actually knows
about per interface. Where NetworkManager writes the file directly it is a regular file
holding one `nameserver` line per server, usually filled in from the router by DHCP.
Either arrangement is correct. What is not correct is editing the file by hand:
NetworkManager rewrites it every time a connection comes up, so a hand-typed nameserver
survives until the next reconnect and then vanishes with no error explaining why.

To set a DNS server that sticks, change the NetworkManager connection rather than the
file. `nmcli connection show` lists the connections by name; then
`nmcli connection modify "Wired connection 1" ipv4.dns "10.0.2.3 8.8.8.8" ipv4.ignore-auto-dns yes`
followed by `nmcli connection up "Wired connection 1"` sets the servers you chose and
stops the router's DHCP answer from adding its own. The same edits work in the desktop:
the network icon, then Wired or Wi-Fi settings, has the DNS field per connection. Both
routes write into `/etc/NetworkManager/system-connections/`, which is a root-owned system
file, so the machine will ask for the user's password. This assistant cannot do it - it
runs as the user, never as root, and refuses `sudo` before it is even executed.

The failure looks like this: `ping 1.1.1.1` answers and `ping debian.org` answers
`Temporary failure in name resolution`, and every browser says it cannot find the server
while the network icon shows a normal connection. That is a DNS fault with a working
link, not a broken network. Confirm with `getent hosts debian.org`, which asks the
resolver and nothing else. AstraOS 0.1.0 had a specific version of this fault in the live
session: `/etc/resolv.conf` was a zero-byte regular file because `live-build` replaced
the path instead of leaving the `/run/resolvconf/resolv.conf` symlink, and both
`NetworkManager.service` and `resolvconf.service` were enabled and each deferred to the
other, so nothing wrote it. The fix was removing `resolvconf` from the image, and it
should not be installed again. The workaround that was documented for that live session
`echo "nameserver 10.0.2.3" | sudo tee /etc/resolv.conf` was a temporary measure that
was lost on reboot, and on a system where NetworkManager owns the file it is lost on the
next reconnect.

One AstraOS-specific override sits above all of this: a live medium booted with the
`dns=` boot parameter. live-boot reads that parameter at boot and writes the given
nameserver into `/etc/resolv.conf`, which supersedes whatever NetworkManager or DHCP
would have configured, and it stays until the next boot. If the live session resolves
through a server that is not the router's, look at the kernel command line first - in the
GRUB menu, select the entry, press `e`, and check for `dns=` on the `linux` line. Remove
the parameter (or change the address) to let NetworkManager do its job; it is a boot
entry, not a file to edit.
