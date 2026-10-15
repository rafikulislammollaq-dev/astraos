# Installing Extra Software On AstraOS

keywords: install, software, package, apt, astra install, synaptic, flatpak, program, application, new app, apt-get, pip

Software on AstraOS is Debian software, and there is one front door to it: `astra install
NAME`, which is a wrapper around `apt-get install --assume-yes NAME` and will ask for
your password because installing a package changes system files. Its companions are
`astra search NAME` (a search of the Debian archive, via `apt-cache search`), `astra
update` (`apt-get update`, which refreshes the package lists), `astra remove NAME`
(removes a package, after asking), `astra apps` (what is installed) and `astra repair`
(dpkg --configure -a and apt-get install --fix-broken, for a broken package database).
`apt-get` itself works if you prefer it; `astra` just spares you typing the common forms
and refuses to guess.

The graphical front end is Synaptic, which is already installed and does the same thing
with a list: search for a package, mark it for installation, apply. The Welcome
application that opens on a fresh system points at both, lists what is already here, and
offers no downloads of its own. Between them they cover the case that matters - a package
that exists in Debian trixie, installed with its dependencies sorted out by apt.

Flatpak is not installed, and this is stated plainly rather than dressed up. The image
deliberately ships no Flatpak and no PackageKit daemon; the reason is that a distribution
this size does not need two competing package systems, and Synaptic plus apt already
cover Debian's archive. The `flatpak` package does exist in Debian trixie and
`sudo apt-get install flatpak` would install it, but nothing in this release is set up
for it: no Flathub remote is configured and no application in the image is built as a
Flatpak. Treat Flatpak as something you can add, not something that is supported here,
and expect to configure the remote yourself.

The assistant will not install anything. Its whole action list is in
`/usr/lib/astraos/ai/actions.py` and contains no install, no upgrade and no package
action; the one action that can run a command refuses `sudo`, `pkexec`, `su` and `doas`
before the command is even executed. So when you ask it to install something it will
answer with the command - `astra install <name>` - and let you run it, because the
assistant runs as your user account with no password and no root, exactly like any other
program you start. This is not a missing feature; it is the boundary that keeps an
assistant from changing your system without a human in front of it.

Two things you can do without root. Programs that ship as a single executable can be
unpacked into `~/.local/bin` and run from there - `~/.local/bin` is on the default PATH
on Debian for your own account - and Python libraries can be installed into a virtual
environment with `python3 -m venv ~/venv && ~/venv/bin/pip install <name>`. The venv
matters because Debian trixie marks the system Python as externally managed, so a plain
`pip install` into it fails with an "externally-managed-environment" error. Anything that
needs `/usr` changed is apt's business and therefore yours.
