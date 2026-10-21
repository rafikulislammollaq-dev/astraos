# The AstraOS APT archive

An installed AstraOS updates from two places:

  * Debian 13, through the ordinary Debian sources (already configured);
  * the AstraOS archive, for AstraOS's own packages - the assistant, the
    dashboard, the installer, the system tools.

The AstraOS archive is served by GitHub Pages from the `apt` branch of the
repository:

    https://rafikulislammollaq-dev.github.io/astraos

(the exact address is in `/etc/apt/sources.list.d/astraos.list.disabled`).

## Why the line ships disabled

apt reads every `*.list` file in `/etc/apt/sources.list.d/`, and a line that
points at an archive whose signature cannot be verified makes `apt update` fail
for the entire system. That is the worst possible moment for it to happen, so
the line is shipped disabled and is enabled once the archive is signed.

## Enabling it

    # 1. install the public key (it is published next to the archive, and it is
    #    also in the release notes for the version you are on)
    sudo install -m 0644 astraos-archive-keyring.gpg \
        /usr/share/keyrings/astraos-archive-keyring.gpg

    # 2. turn the line on
    sudo mv /etc/apt/sources.list.d/astraos.list.disabled \
        /etc/apt/sources.list.d/astraos.list

    # 3. and check
    sudo apt update
    apt list --upgradable

`astraos-update --check` shows what is on offer from both archives and prints the
command to take it, and `astraos-update --snapshot` keeps a copy of your files
first, so a bad upgrade can be rolled back.
