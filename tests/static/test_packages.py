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

# A control field: a name, then a colon. dpkg-deb accepts nothing else at the start of a line.
FIELD_LINE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*:")

# Tools that rewrite a configuration file belonging to another package, mapped to the file
# they rewrite. A package maintainer script that calls one of these edits the file *inside*
# the dpkg run that is configuring the package owning it, so dpkg finds a file that no longer
# matches the copy it unpacked and stops to ask which version to keep:
#
#   Configuration file '/etc/plymouth/plymouthd.conf'
#   *** plymouthd.conf (Y/I/N/O/D/Z) [default=N] ? dpkg: error processing package
#     plymouth (--configure): end of file on stdin at conffile prompt
#
# Nothing answers that question during an unattended build, so the whole image build fails
# after every package has been installed. `plymouth-set-default-theme` edits its file with
# sed(1); the tool and the file were read out of the plymouth package itself.
#
# A chroot hook may call these: hooks run after installation and configuration are finished,
# so the same edit is a local change to a configuration file rather than a conflict. See
# docs/KNOWN_LIMITATIONS.md §3.13.
CONFFILE_EDITING_TOOLS = {
    "plymouth-set-default-theme": "/etc/plymouth/plymouthd.conf",
}

MAINTAINER_SCRIPTS = ("preinst", "postinst", "prerm", "postrm")

PLYMOUTH_HOOK = "config/live-build/config/hooks/live/0120-plymouth.hook.chroot"


def _without_comments(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )

# A Debian package name: lowercase letters, digits, plus, minus and dots; must start
# with an alphanumeric.
VALID_NAME = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")


def test_no_two_astraos_packages_ship_the_same_path() -> None:
    """Two packages may not own the same file: dpkg refuses to install the second.

    This is not a style rule. The image build installs the AstraOS packages into
    the chroot, and when two of them own the same path the build dies there with
    "trying to overwrite '/usr/share/applications/astraos-help.desktop', which is
    also in package astraos-ai" - after the image has been assembled, which is
    the most expensive place to find out. A desktop entry added to the assistant
    package while the desktop package already shipped one with that name cost
    exactly that.
    """
    owners: dict[str, str] = {}
    conflicts: list[str] = []
    for package in sorted((REPO_ROOT / "packages").iterdir()):
        if not package.is_dir():
            continue
        root = package / "root"
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            key = path.relative_to(root).as_posix()
            if key in owners:
                conflicts.append(f"{key} is shipped by both {owners[key]} and {package.name}")
            else:
                owners[key] = package.name
    assert not conflicts, (
        "two AstraOS packages own the same path, and the image build will refuse to "
        "install the second one:\n  " + "\n  ".join(conflicts)
    )
    assert len(owners) > 10, (
        "only a handful of package files were found, so this check is not looking at "
        "the packages"
    )


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


def test_control_files_are_valid_control_paragraphs() -> None:
    """A Debian control paragraph has no comment syntax, and dpkg-deb stops the build over it.

    A `#` at the start of a line is not a comment: dpkg-deb reads it as a field name and
    fails with "field name '#' must be followed by colon", after every AstraOS package has
    already been assembled. That is exactly what a block of comments explaining the
    Conflicts/Replaces fields did. Explanation belongs in the changelog, in
    docs/KNOWN_LIMITATIONS.md or in the package list; the control paragraph holds fields.

    A line is therefore only valid as a field (`Name: value`), as an indented continuation of
    the previous field (which is how the Description body is written) or as blank.
    """
    controls = astraos_env.control_files()
    assert len(controls) >= 5, (
        f"only {len(controls)} control template(s) were found; the check is not looking at "
        "the packages this repository builds"
    )

    offenders: list[str] = []
    for control in controls:
        label = control.relative_to(astraos_env.REPO_ROOT).as_posix()
        for number, line in enumerate(control.read_text(encoding="utf-8").splitlines(), 1):
            if not line or line.startswith((" ", "\t")) or FIELD_LINE.match(line):
                continue
            looks_like_comment = " (comment: control files have no comment syntax)" if line.startswith("#") else ""
            offenders.append(f"{label}:{number}: {line.rstrip()}{looks_like_comment}")

    assert not offenders, (
        "dpkg-deb cannot parse these control-file lines, so the package build would fail:\n  "
        + "\n  ".join(offenders)
    )


def test_package_scripts_do_not_edit_configuration_owned_by_another_package() -> None:
    """Packages may not edit a conffile that another package owns, and dpkg enforces it.

    This is the third variant of one mistake: AstraOS touching a path Debian already owns.
    The first two were file conflicts, where the second owner is refused outright. This one
    is subtler — the edit succeeds, and the failure comes later, when dpkg configures the
    package that owns the file and finds its contents changed. It stops at a prompt that
    nothing answers during a build, so the image build dies at the very end of the chroot
    stage with "end of file on stdin at conffile prompt".
    """
    offenders: list[str] = []
    for suffix in MAINTAINER_SCRIPTS:
        for script in sorted((astraos_env.REPO_ROOT / "packages").glob(f"*/{suffix}")):
            label = script.relative_to(astraos_env.REPO_ROOT).as_posix()
            code = _without_comments(script.read_text(encoding="utf-8"))
            # Split on anything that cannot appear in a command name, so `$(` and quoting
            # around a call do not hide it.
            words = set(re.split(r"[^A-Za-z0-9_.+-]+", code))
            for tool, conffile in CONFFILE_EDITING_TOOLS.items():
                if tool in words:
                    offenders.append(
                        f"{label} calls {tool}, which rewrites {conffile} while the package "
                        "that owns it may not be configured yet"
                    )

    assert not offenders, (
        "these maintainer scripts would stop the image build at a dpkg conffile prompt:\n  "
        + "\n  ".join(offenders)
        + "\n  Move the call into a chroot hook, which runs after every package is "
        "installed and configured."
    )


def test_the_plymouth_theme_is_selected_after_packages_are_configured() -> None:
    """The theme is still selected somewhere, and the somewhere is a hook.

    Without the first assertion this rule could be satisfied by deleting the theme
    selection altogether, and the image would boot an unbranded upstream splash.
    """
    hook = astraos_env.REPO_ROOT / PLYMOUTH_HOOK
    assert hook.is_file(), (
        f"{PLYMOUTH_HOOK} does not exist. No package can select the Plymouth theme "
        "without editing a conffile owned by the plymouth package, so this hook is the "
        "only place the selection can happen."
    )

    body = _without_comments(hook.read_text(encoding="utf-8"))
    assert "plymouth-set-default-theme" in body, (
        f"{PLYMOUTH_HOOK} is expected to select the AstraOS Plymouth theme; it no longer "
        "calls plymouth-set-default-theme"
    )
    assert "update-initramfs" in body, (
        f"{PLYMOUTH_HOOK} selects a theme without rebuilding the initramfs. The initramfs "
        "carries its own copy of the theme, so the splash would fall back to the plain "
        "text animation."
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


def test_resolvconf_is_not_installed_alongside_networkmanager() -> None:
    """resolvconf and NetworkManager each defer DNS to the other, so DNS ends up dead.

    This is a measured defect, not a theoretical one. On the 0.1.0 ISO, both units are
    enabled (NetworkManager.service and resolvconf.service are both in
    multi-user.target.wants) and /etc/resolv.conf is a 0-byte regular file, because
    live-build replaces the path rather than leaving the /run/resolvconf/resolv.conf
    symlink resolvconf(8) manages. NetworkManager sees resolvconf installed and hands
    DNS over to it; resolvconf finds its symlink replaced and writes nothing. Nothing
    owns the file, so no name ever resolves and the live session has a browser that
    cannot load a page until someone types a nameserver by hand.

    Unlike most package mistakes this one does not fail the build: apt resolves the set
    happily and the image ships. It is only visible by booting, which is why the
    exclusion needs a test. NetworkManager writes /etc/resolv.conf itself, and Debian 13
    treats resolvconf as deprecated.
    """
    selected: dict[str, str] = {}
    for filename, packages in astraos_env.package_lists().items():
        for package in packages:
            selected[package] = filename

    assert "network-manager" in selected, (
        "network-manager is not in any package list, so this test is no longer guarding "
        "the DNS path it was written for. NetworkManager is the single networking "
        "authority for the desktop session (plan §12)."
    )

    offenders = sorted(
        f"{name} (in {selected[name]})"
        for name in ("resolvconf", "openresolv", "unbound-anchor")
        if name in selected
    )
    assert not offenders, (
        "these DNS resolvers are listed alongside network-manager, which disables name "
        "resolution in the live session:\n  " + "\n  ".join(offenders)
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
            f"{forbidden} is selected. AstraOS ships no remote administration "
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


HOOK_DIR = REPO_ROOT / "config" / "live-build" / "config" / "hooks" / "live"
TOOL_REFERENCE = re.compile(r"/usr/bin/(astraos-[a-z][a-z0-9-]*)")


def test_tools_run_by_the_build_hooks_are_shipped_by_a_package() -> None:
    """A hook may only run a tool that the image actually contains.

    Hooks execute *inside* the chroot, where a wrong tool name is neither a syntax error nor
    a missing file on the host: the build fails minutes in, after every package has been
    installed, with "not found". What puts a tool in the image is the root tree of one of
    the packages built here, so the two have to agree.
    """
    referenced: set[str] = set()
    for hook in sorted(HOOK_DIR.glob("*.chroot")):
        text = "".join(
            line
            for line in hook.read_text(encoding="utf-8", errors="replace").splitlines(True)
            if not line.lstrip().startswith("#")
        )
        referenced.update(TOOL_REFERENCE.findall(text))

    assert referenced, "no hook runs an astraos tool; this test is watching nothing"

    shipped = {
        path.name for path in (REPO_ROOT / "packages").glob("*/root/usr/bin/astraos-*")
    }
    missing = sorted(referenced - shipped)
    assert not missing, (
        "these tools are run by a build hook but are not shipped by any package, so the "
        "hook would fail inside the chroot: " + ", ".join(missing)
    )
