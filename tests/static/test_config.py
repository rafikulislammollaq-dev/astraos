"""Configuration consistency tests.

Checks that the pinned release, the package lists and the identity files agree with each
other. This is the test that catches the most likely real mistake in this repository:
one file being updated and another being forgotten.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import astraos_env  # noqa: E402

DESCRIPTION = "configuration files parse and agree with each other"


def test_distribution_env_parses() -> None:
    config = astraos_env.distribution()
    required = [
        "ASTRAOS_NAME",
        "ASTRAOS_VERSION",
        "ASTRAOS_BASE_RELEASE_CODENAME",
        "ASTRAOS_BASE_SUITE",
        "ASTRAOS_ARCH",
        "ASTRAOS_ARCH_DEB",
        "ASTRAOS_DESKTOP",
        "ASTRAOS_LIVE_USER",
        "ASTRAOS_DEBIAN_MIRROR",
    ]
    missing = [key for key in required if key not in config]
    assert not missing, f"config/distribution.env is missing: {', '.join(missing)}"


def test_branding_env_parses() -> None:
    branding = astraos_env.branding()
    for key in ("BRAND_NAME", "BRAND_VOID", "BRAND_NEON_MAGENTA",
                "COLOR_BG_DARK", "COLOR_ACCENT_PRIMARY", "BRAND_FONT_UI"):
        assert key in branding, f"config/branding.env is missing {key}"

    # Colours must be valid 6-digit hex, because the asset renderer parses them.
    for key, value in branding.items():
        if value.startswith("#"):
            assert len(value) == 7, f"{key}={value!r} is not a #RRGGBB colour"
            int(value[1:], 16)  # raises ValueError on a bad digit


def test_no_token_is_declared_twice_in_an_env_file() -> None:
    """A repeated key silently shadows the earlier value, and nothing reports it.

    scripts/lib/astraos_env.py returns these files verbatim and the last definition
    of a key wins, so a duplicate is a silent behaviour change rather than an error.
    That is not hypothetical: config/branding.env carried COLOR_TEXT_DIM twice, as
    #98A2B3 in the desktop-layer block and #9A93B8 in the HUD block. Every consumer
    reading the token got #9A93B8, while the Light GTK themes were still written
    against the dead #98A2B3 - a palette drift that only surfaced because a separate
    test happened to notice a colour the other theme used.

    Declaring a token once is the rule. This test makes a second declaration a build
    failure at the point of the mistake rather than a mystery three files away.
    """
    for name in ("config/branding.env", "config/distribution.env"):
        path = astraos_env.REPO_ROOT / name
        assert path.is_file(), f"{name} is missing"
        first_seen: dict[str, int] = {}
        duplicates: list[str] = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key = stripped.partition("=")[0].strip()
            if key in first_seen:
                duplicates.append(f"{key} (lines {first_seen[key]} and {number})")
            else:
                first_seen[key] = number
        assert not duplicates, (
            f"{name} declares the same key twice, so the later value silently wins: "
            + "; ".join(duplicates)
            + ". Declare a token once and delete the stale line."
        )


def test_version_files_agree() -> None:
    """VERSION and config/distribution.env must not disagree about the release."""
    version = astraos_env.version()
    config = astraos_env.distribution()
    assert version["ASTRAOS_VERSION"] == config["ASTRAOS_VERSION"], (
        "VERSION and config/distribution.env disagree: "
        f"{version['ASTRAOS_VERSION']!r} vs {config['ASTRAOS_VERSION']!r}"
    )
    assert version["ASTRAOS_ARCH"] == config["ASTRAOS_ARCH"], (
        "VERSION and config/distribution.env disagree about the architecture"
    )


def test_pretty_name_contains_version() -> None:
    config = astraos_env.distribution()
    assert config["ASTRAOS_VERSION"] in config["ASTRAOS_PRETTY_NAME"], (
        "ASTRAOS_PRETTY_NAME does not contain the version, so the version shown to users "
        "would drift from the actual release"
    )
    assert config["ASTRAOS_RELEASE_STAGE"] in config["ASTRAOS_PRETTY_NAME"], (
        "ASTRAOS_PRETTY_NAME does not mention the release stage; an alpha release must "
        "identify itself as alpha where users see it"
    )


def test_iso_identity_carries_the_release_version() -> None:
    """The ISO's own name for itself drifts silently, and it did.

    Bumping the release to 0.2.0 updated ASTRAOS_VERSION and ASTRAOS_PRETTY_NAME but left
    the ISO volume id and label reading 0.1.0, so the medium would have announced a release
    that was not the one being built. ASTRAOS_ISO_VOLUME_ID is not decoration for a human
    to read: scripts/configure-live-build.sh passes it to `lb config --iso-volume`, so it
    becomes the ISO9660 volume id, and `isoinfo` is how anyone checks which image they have.
    """
    config = astraos_env.distribution()
    version = config["ASTRAOS_VERSION"]
    label = config["ASTRAOS_ISO_LABEL"]
    volume = config["ASTRAOS_ISO_VOLUME_ID"]

    assert version in label, (
        f"ASTRAOS_ISO_LABEL is {label!r}, which does not name the version {version!r} "
        "being built, so the medium would announce the wrong release"
    )
    assert config["ASTRAOS_RELEASE_STAGE"] in label, (
        f"ASTRAOS_ISO_LABEL is {label!r} and does not name the release stage; an alpha "
        "image has to say so on its own label"
    )

    # ISO9660 volume ids are upper case, and the dots of a version become underscores.
    expected = f"ASTRAOS_{version.replace('.', '_')}_{config['ASTRAOS_ARCH'].upper()}"
    assert volume == expected, (
        f"ASTRAOS_ISO_VOLUME_ID is {volume!r}, but version {version!r} and architecture "
        f"{config['ASTRAOS_ARCH']!r} imply {expected!r}. The volume id is what isoinfo "
        "reports, so it has to be derivable from the release, not maintained by hand."
    )


# Files that ship in the image and state the release to a person: the login banner, the
# message of the day, the desktop greeter, the boot menu, the installer, the first-run
# screen and the tool that reports what this system is. Each one either carries the release
# number or reads it at run time; none may carry a different one.
#
# Not in this list: files that quote a version as history. docs/KNOWN_LIMITATIONS.md records
# what the 0.1.0 ISO measured, and the CHANGELOG is a record of past releases. Those are
# supposed to keep the old numbers.
SHIPPED_IDENTITY_FILES = [
    "apps/astraos-hud/astraos_hud/__init__.py",
    "branding/grub/astraos/theme.txt",
    "branding/lightdm/astraos-greeter/MainWindow.html",
    "installer/branding/astraos/branding.desc",
    "packages/astraos-base/root/etc/ufw/astraos-policy.conf",
    "packages/astraos-base/root/usr/bin/astraos-info",
    "packages/astraos-system-tools/root/usr/bin/astraos-welcome",
    "system/issue.in",
    "system/issue.net.in",
    "system/lsb-release.in",
    "system/motd",
]


def _without_comments(text: str) -> str:
    """Drop full-line comments.

    Every file in the list above is shell, Python, HTML or a Calamares description file, and
    in all of them a line whose first non-space characters open a comment. A comment is
    allowed to name a version it is not claiming: the explanation above a line that reads the
    release from a file will say which release the literal it replaced was. Flagging those
    would push the next person to stop writing down why the code looks the way it does.
    """
    kept = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("#", "<!--", "//")):
            continue
        kept.append(line)
    return "\n".join(kept)


def test_no_shipped_file_names_a_different_release() -> None:
    """Every place the image names its own release has to name the release being built.

    Raising the version to 0.2.0 in VERSION and config/distribution.env left eleven shipped
    files still saying 0.1.0: the boot menu, the desktop login screen, the installer's title
    and welcome page, `/etc/issue`, `/etc/issue.net`, the message of the day, `astraos-info
    --help`, the first-run screen and the HUD's own version. The image would have introduced
    itself as 0.1.0 from the first screen after the firmware and reported 0.2.0 in
    /etc/os-release, which is the version bug reports are filed against.

    A file may name the current release, and it may read the release at run time (the two
    tools do), but it may not name any other version. That rule is what makes this test
    catch the next bump as well as this one.
    """
    version = astraos_env.distribution()["ASTRAOS_VERSION"]
    pattern = re.compile(r"\b\d+\.\d+\.\d+\b")

    offenders: list[str] = []
    for relative in SHIPPED_IDENTITY_FILES:
        path = REPO_ROOT / relative
        assert path.is_file(), (
            f"{relative} is listed as a file that names the release but does not exist, so "
            "this test is not checking what it says it checks"
        )
        for number, line in enumerate(_without_comments(path.read_text(encoding="utf-8")).splitlines(), 1):
            for found in pattern.findall(line):
                if found != version:
                    offenders.append(f"{relative}:{number}: {found} (release is {version})")

    assert not offenders, (
        "the image would name a release other than the one being built:\n  "
        + "\n  ".join(offenders)
    )


def test_architecture_is_consistent() -> None:
    config = astraos_env.distribution()
    assert config["ASTRAOS_ARCH"] in ("amd64", "arm64"), (
        f"unexpected architecture {config['ASTRAOS_ARCH']!r}"
    )
    assert config["ASTRAOS_ARCH_DEB"] in ("amd64", "arm64"), (
        f"unexpected dpkg architecture {config['ASTRAOS_ARCH_DEB']!r}"
    )


def test_no_unsubstituted_placeholders_in_templates() -> None:
    """Every @@TOKEN@@ used in a template must be one the build scripts substitute.

    Without this, the first sign of a typo is an image that ships the literal text
    "@@VERSION@@" in /etc/os-release.
    """
    # The tokens that scripts/configure-live-build.sh and build-packages.sh know how to
    # replace. Kept in sync with the substitution tables in those scripts.
    known = {
        "NAME", "VERSION", "CODENAME", "CODENAME_LOWER", "STAGE", "ARCH",
        "PRETTY_NAME", "HOMEPAGE", "SUPPORT_URL", "BUG_URL", "DOCUMENTATION_URL",
        "BASE_DISTRIBUTION", "BASE_RELEASE_VERSION", "BASE_RELEASE_CODENAME",
        "BASE_SUITE", "DESKTOP", "DISPLAY_SERVER", "INIT", "INSTALLER",
        "PACKAGE", "VENDOR", "RELEASE_TYPE",
    }

    import re
    token = re.compile(r"@@([A-Z_]+)@@")
    templates = list((REPO_ROOT / "system").glob("*.in"))
    templates += list((REPO_ROOT / "packages").rglob("*.in"))
    assert templates, "no templates were found; the test paths are wrong"

    unknown: list[str] = []
    for path in templates:
        text = path.read_text(encoding="utf-8")
        for match in token.finditer(text):
            name = match.group(1)
            if name not in known:
                unknown.append(f"{path.relative_to(REPO_ROOT)}: @@{name}@@")
    assert not unknown, (
        "these templates use placeholders the build scripts cannot substitute, so they "
        "would ship literally:\n  " + "\n  ".join(unknown)
    )


def test_scripts_substitute_every_known_token() -> None:
    """The substitution tables must cover every token declared above.

    This is the other half of the previous test: it stops the two lists drifting apart
    when a new placeholder is added.
    """
    configure = (REPO_ROOT / "scripts" / "configure-live-build.sh").read_text(encoding="utf-8")
    packages = (REPO_ROOT / "scripts" / "build-packages.sh").read_text(encoding="utf-8")
    combined = configure + packages

    for token in ("@@NAME@@", "@@VERSION@@", "@@CODENAME@@", "@@STAGE@@", "@@ARCH@@",
                  "@@PRETTY_NAME@@", "@@BASE_DISTRIBUTION@@", "@@BASE_SUITE@@",
                  "@@DESKTOP@@", "@@INSTALLER@@", "@@PACKAGE@@"):
        assert token in combined, (
            f"{token} is documented as substituted but does not appear in any build "
            "script; either add the substitution or remove the placeholder"
        )
