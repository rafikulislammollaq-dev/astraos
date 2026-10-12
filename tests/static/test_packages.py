"""Package selection tests.

Structural checks on config/package-lists/ that catch the mistakes most likely to slip
through: a package requested twice with different names, a malformed line, or a line
that is actually a comment or a task metapackage.

Live availability against the Debian archive is verified separately by
scripts/verify-package-availability.py, which needs network access. These tests must
pass offline.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import astraos_env  # noqa: E402

DESCRIPTION = "package lists are well formed and internally consistent"

# A Debian package name: lowercase letters, digits, plus, minus and dots; must start
# with an alphanumeric.
VALID_NAME = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")


def test_package_lists_exist() -> None:
    lists = astraos_env.package_lists()
    assert lists, "no *.list.chroot files found in config/package-lists"
    assert len(lists) >= 6, (
        f"only {len(lists)} package list(s) found; the plan expects the selection to be "
        "split into reviewable categories (core, kernel, firmware, graphics, desktop, "
        "applications, networking, installer)"
    )


def test_every_entry_is_a_valid_package_name() -> None:
    bad: list[str] = []
    for filename, packages in astraos_env.package_lists().items():
        for package in packages:
            if not VALID_NAME.match(package):
                bad.append(f"{filename}: {package!r}")
    assert not bad, (
        "these package list entries are not valid Debian package names:\n  "
        + "\n  ".join(bad)
    )


def test_packages_do_not_install_into_upstream_config_directories() -> None:
    """Two packages cannot own the same path, and dpkg stops the build when they try.

    Both failures this guards against were real:

      * `/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml` is owned by
        libxfce4ui-common, and xsettings.xml and xfce4-session.xml are owned by the Xfce
        settings and session packages. AstraOS ships its desktop defaults in /etc/skel
        instead, which it owns.
      * `/etc/calamares/**` is owned by calamares-settings-debian. AstraOS keeps its own
        tree there and declares Conflicts/Replaces, which is the documented way to take a
        path over — so that one is allowed, but only with the declaration present.

    The upstream file lists change between releases, so this is checked against the mapping
    rather than against a snapshot of Debian's contents.
    """
    packaging = astraos_env.REPO_ROOT.joinpath("scripts/build-packages.sh").read_text(
        encoding="utf-8"
    )
    code = "\n".join(
        line for line in packaging.splitlines() if not line.lstrip().startswith("#")
    )

    assert "/etc/xdg/xfce4/xfconf" not in code, (
        "the packaging step installs into /etc/xdg/xfce4/xfconf, which Debian's Xfce packages "
        "own. dpkg will refuse the second owner and stop the image build. Ship desktop "
        "defaults through /etc/skel instead."
    )

    installer = astraos_env.REPO_ROOT.joinpath(
        "packages/astraos-installer/control.in"
    ).read_text(encoding="utf-8")
    if "/etc/calamares" in code:
        for field in ("Conflicts: calamares-settings-debian", "Replaces: calamares-settings-debian"):
            assert field in installer, (
                f"astraos-installer installs an /etc/calamares tree without declaring "
                f"{field!r}, so installing it alongside Debian's settings package would fail "
                "the build with 'trying to overwrite'"
            )


def test_control_files_declare_parseable_dependencies() -> None:
    """The `.deb` files declare dependencies too, and apt resolves them during the build.

    `scripts/verify-package-availability.py` checks those names against the real archive, but
    a parser that quietly returned nothing would make that check vacuous — and a missing
    dependency is not caught anywhere else, which is how `Depends: kpmcore` reached a build
    that had already downloaded every package.
    """
    groups = astraos_env.control_dependencies()
    assert len(groups) >= 20, (
        f"only {len(groups)} dependency group(s) were parsed out of the package control "
        "files, so the availability check is not seeing them"
    )

    bad: list[str] = []
    for alternatives, source in groups:
        for name in alternatives:
            if not VALID_NAME.match(name):
                bad.append(f"{source}: {name!r}")
    assert not bad, "these parsed dependency names are malformed:\n  " + "\n  ".join(bad)

    names = {name for alternatives, _ in groups for name in alternatives}
    assert "astraos-base" in names, (
        "no AstraOS package declares a dependency on astraos-base, so the parser is not "
        "reading the fields it should"
    )


def test_no_firmware_installer_packages_are_listed() -> None:
    """`firmware-*-installer` packages download firmware at install time.

    They contain no firmware: their post-install script fetches it from the internet. Debian
    ships them from contrib for exactly that reason, because the firmware itself is not
    redistributable. In a build chroot that download either fails — which is what happened,
    with firmware-b43-installer, after several gigabytes had been installed — or worse,
    succeeds and bakes an unauditable blob chosen by a third party into the image.

    A user with an affected card installs the installer on the installed system instead.
    """
    offenders: list[str] = []
    for filename, packages in astraos_env.package_lists().items():
        for package in packages:
            if re.fullmatch(r"firmware-.*-installer", package):
                offenders.append(f"{filename}: {package}")

    assert not offenders, (
        "these firmware installers are listed. They download firmware at install time rather "
        "than containing it, so the build cannot produce a complete image from them:\n  "
        + "\n  ".join(offenders)
    )


def test_firmware_needing_licence_acceptance_is_not_listed() -> None:
    """Firmware that waits for debconf to accept a licence cannot be installed unattended.

    firmware-ipw2x00 and firmware-ivtv ask for licence acceptance in their post-install
    script. In a non-interactive build nothing answers, dpkg fails, and apt rolls the whole
    installation back — after every package has been downloaded. These are the two packages
    live-build's own firmware stage specially preseeds, which is the only reason they ever
    appeared to install; AstraOS does not accept a licence on a user's behalf instead.
    """
    needing_prompts = {"firmware-ipw2x00", "firmware-ivtv"}

    offenders: list[str] = []
    for filename, packages in astraos_env.package_lists().items():
        for package in packages:
            if package in needing_prompts:
                offenders.append(f"{filename}: {package}")

    assert not offenders, (
        "these packages need a licence accepted interactively, so the build cannot install "
        "them and apt will roll back the whole package set:\n  " + "\n  ".join(offenders)
    )


def test_only_one_time_synchronisation_daemon() -> None:
    """Two time daemons cannot coexist, and apt proves it by refusing to install both.

    ntpsec, chrony and openntpd all declare `Conflicts: time-daemon`, which
    systemd-timesyncd provides. Listing one alongside systemd-timesyncd does not produce a
    subtle misconfiguration: the build stops with "Unable to correct problems, you have held
    broken packages" after several gigabytes have already been downloaded. This test costs
    nothing and fails in the first second instead.
    """
    chosen = "systemd-timesyncd"
    conflicting = {"ntpsec", "ntp", "chrony", "openntpd", "ntpdate"}

    selected: dict[str, str] = {}
    for filename, packages in astraos_env.package_lists().items():
        for package in packages:
            selected[package] = filename

    assert chosen in selected, (
        f"{chosen} is not in any package list. AstraOS synchronises time with the init "
        "system's own daemon; if that decision changes, change this test with it."
    )

    offenders = sorted(
        f"{name} (in {selected[name]})" for name in conflicting if name in selected
    )
    assert not offenders, (
        f"these time daemons are listed together with {chosen}, which they conflict with, "
        "so the build cannot resolve the package set:\n  " + "\n  ".join(offenders)
    )


def test_no_duplicate_entries_within_a_list() -> None:
    problems: list[str] = []
    for filename, packages in astraos_env.package_lists().items():
        seen: set[str] = set()
        for package in packages:
            if package in seen:
                problems.append(f"{filename}: {package} listed twice")
            seen.add(package)
    assert not problems, "duplicate entries add noise and hide intent:\n  " + "\n  ".join(problems)


def test_no_task_metapackages() -> None:
    """AstraOS selects packages explicitly; task-* metapackages pull in duplicates.

    auto/config disables Debian tasks for the same reason. This test keeps a future
    package list from quietly reintroducing one.
    """
    offenders: list[str] = []
    for filename, packages in astraos_env.package_lists().items():
        for package in packages:
            if package.startswith("task-"):
                offenders.append(f"{filename}: {package}")
    assert not offenders, (
        "task metapackages are disabled in auto/config and must not appear in a package "
        "list:\n  " + "\n  ".join(offenders)
    )


def test_critical_components_are_selected() -> None:
    """The components the release depends on must be in some list.

    These are asserted by name because each one corresponds to a documented promise:
    a bootable kernel, a live session, an Xfce desktop, a network manager, a display
    manager, the installer and the AstraOS packages themselves.
    """
    packages = astraos_env.all_packages()
    required = {
        "linux-image-amd64": "a bootable kernel",
        "initramfs-tools": "an initramfs for that kernel",
        "systemd": "the init system named in config/distribution.env",
        "xfce4": "the desktop named in config/distribution.env",
        "xfce4-terminal": "the terminal the release promises",
        "thunar": "the file manager the release promises",
        "network-manager": "NetworkManager, the desktop networking authority",
        "lightdm": "the display manager named in config/distribution.env",
        "lightdm-gtk-greeter": "the branded login screen",
        "calamares": "the installer named in config/distribution.env",
        "plymouth": "the branded boot splash",
        "grub2-common": "the bootloader named in config/distribution.env",
        "ufw": "the documented firewall",
        "sudo": "privilege escalation for a normal user account",
        "firefox-esr": "the browser the release promises",
        "plymouth-themes": "theme support for the boot splash",
    }
    missing = [
        f"{name} ({why})" for name, why in required.items() if name not in packages
    ]
    assert not missing, (
        "these critical packages are not selected in any package list:\n  "
        + "\n  ".join(missing)
    )


def test_no_competing_display_managers() -> None:
    """Two display managers on one system fight over the display-manager unit."""
    packages = astraos_env.all_packages()
    managers = {"lightdm", "gdm3", "sddm", "lxdm", "slim", "xdm"} & set(packages)
    assert len(managers) <= 1, (
        f"more than one display manager is selected: {sorted(managers)}. "
        "Only one may own /etc/systemd/system/display-manager.service"
    )


def test_non_systemd_session_manager_not_installed() -> None:
    """elogind and systemd both manage sessions and must not be installed together."""
    packages = astraos_env.all_packages()
    assert "elogind" not in packages, (
        "elogind is selected but config/distribution.env sets ASTRAOS_INIT=systemd; "
        "installing both is a conflict"
    )


def test_no_passwordless_or_diagnostic_leaks_in_package_selection() -> None:
    """The release must not ship a remote administration daemon by default."""
    packages = astraos_env.all_packages()
    for forbidden in ("openssh-server", "ssh", "dropbear", "x11vnc", "vino", "tigervnc-standalone-server"):
        assert forbidden not in packages, (
            f"{forbidden} is selected. AstraOS 0.1.0 ships no remote administration "
            "daemon and docs/SECURITY.md documents that as a security property"
        )


def test_kpmcore_is_versioned() -> None:
    """kpmcore is shipped as a versioned library, not a bare name.

    The bare name 'kpmcore' does not exist in the pinned release, so this test pins the
    expectation and points at the place to update it when the base release changes.
    """
    packages = astraos_env.all_packages()
    assert "kpmcore" not in packages, (
        "'kpmcore' is not a real package in Debian trixie; the versioned library name "
        "must be used (see config/package-lists/60-installer.list.chroot)"
    )
