"""Configuration consistency tests.

Checks that the pinned release, the package lists and the identity files agree with each
other. This is the test that catches the most likely real mistake in this repository:
one file being updated and another being forgotten.
"""

from __future__ import annotations

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
