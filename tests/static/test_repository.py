"""Repository structure, desktop entries, installer config, docs and secret scanning."""

from __future__ import annotations

import configparser
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import astraos_env  # noqa: E402

DESCRIPTION = "repository structure, desktop entries, installer YAML, docs and secrets"

# Directories the plan's §4 structure requires.
REQUIRED_DIRS = [
    "config", "config/package-lists", "config/live-build", "config/live-build/auto",
    "config/live-build/config/hooks/live", "config/live-build/config/archives",
    "branding", "branding/logos", "branding/icons", "branding/plymouth", "branding/grub",
    "branding/lightdm", "branding/tools", "desktop", "desktop/skel", "desktop/themes",
    "desktop/launchers", "desktop/autostart", "packages", "packages/astraos-base",
    "packages/astraos-branding", "packages/astraos-desktop", "packages/astraos-system-tools",
    "system", "system/sysctl", "system/security", "installer", "installer/calamares",
    "installer/calamares/modules", "installer/branding/astraos", "scripts", "tests",
    "tests/static", "docs", "build", "dist",
]

REQUIRED_FILES = [
    "README.md", "LICENSE", "SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md", "VERSION",
    "Makefile", ".gitignore",
    "config/distribution.env", "config/branding.env",
    "scripts/build-iso.sh", "scripts/validate-environment.sh",
    "scripts/configure-live-build.sh", "scripts/build-packages.sh",
    "scripts/validate-iso.sh", "scripts/generate-checksums.sh",
    "scripts/generate-manifest.sh", "scripts/verify-package-availability.py",
]


def test_required_directories_exist() -> None:
    missing = [d for d in REQUIRED_DIRS if not (REPO_ROOT / d).is_dir()]
    assert not missing, "missing required directories:\n  " + "\n  ".join(missing)


def test_required_files_exist() -> None:
    missing = [f for f in REQUIRED_FILES if not (REPO_ROOT / f).is_file()]
    assert not missing, "missing required files:\n  " + "\n  ".join(missing)


def test_no_empty_placeholder_documents() -> None:
    """The plan forbids empty placeholder documentation (plan §25)."""
    offenders: list[str] = []
    docs_dir = REPO_ROOT / "docs"
    for path in sorted(docs_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text.strip()) < 400:
            offenders.append(f"{path.name} ({len(text.strip())} characters)")
    assert not offenders, (
        "these documents are effectively empty; the plan requires real content:\n  "
        + "\n  ".join(offenders)
    )


def test_desktop_entries_are_valid() -> None:
    """Every launcher must parse and declare the keys a desktop needs."""
    launchers = sorted((REPO_ROOT / "desktop" / "launchers").glob("*.desktop"))
    autostart = sorted((REPO_ROOT / "desktop" / "autostart").glob("*.desktop"))
    files = launchers + autostart
    assert files, "no desktop entries were found"

    failures: list[str] = []
    for path in files:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read_string(path.read_text(encoding="utf-8"))
        except configparser.Error as exc:
            failures.append(f"{path.name}: cannot parse: {exc}")
            continue

        if not parser.has_section("Desktop Entry"):
            failures.append(f"{path.name}: no [Desktop Entry] section")
            continue

        entry = parser["Desktop Entry"]
        for key in ("Type", "Name"):
            if not entry.get(key):
                failures.append(f"{path.name}: missing required key {key}")
        if entry.get("Type") == "Application" and not entry.get("Exec"):
            failures.append(f"{path.name}: Type=Application requires Exec")
        if not entry.get("Comment"):
            failures.append(f"{path.name}: no Comment; the menu entry would look bare")
    assert not failures, "desktop entry problems:\n  " + "\n  ".join(failures)


def test_astraos_launchers_only_use_commands_that_are_shipped() -> None:
    """A launcher that calls a command the image does not contain is a dead menu item."""
    commands = set()
    for path in sorted((REPO_ROOT / "desktop" / "launchers").glob("astraos-*.desktop")):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("Exec="):
                exec_line = line.split("=", 1)[1]
                # Take the command being run: after --command= for a terminal wrapper,
                # otherwise the first token.
                match = re.search(r"--command=\"?([^\"']+)", exec_line)
                if match:
                    commands.add(match.group(1).strip().split()[0].strip('"'))
                else:
                    commands.add(exec_line.split()[0])

    astraos_commands = {c for c in commands if c.startswith("astraos-")}
    assert astraos_commands, "no AstraOS commands found in the launchers"

    # Each must be provided by a package source tree.
    provided = {
        path.name
        for path in (REPO_ROOT / "packages").rglob("usr/bin/astraos-*")
        if path.is_file()
    }
    missing = sorted(astraos_commands - provided)
    assert not missing, (
        "these launchers call commands that no package installs:\n  " + "\n  ".join(missing)
    )


def test_calamares_configuration_has_the_safety_properties() -> None:
    """The safety settings the build hook asserts must be present in the source too."""
    partition = (REPO_ROOT / "installer" / "calamares" / "modules" / "partition.conf").read_text(encoding="utf-8")
    settings = (REPO_ROOT / "installer" / "calamares" / "settings.conf").read_text(encoding="utf-8")

    assert re.search(r"^alwaysShowPartitionLabels:\s*true", partition, re.M), (
        "partition.conf must always show which partitions are affected"
    )
    assert not re.search(r"^initialPartitioningChoice:\s*eraseDisk", partition, re.M), (
        "partition.conf must not default to erasing a disk"
    )
    assert re.search(r"^defaultFileSystemType:\s*\"?ext4\"?", partition, re.M), (
        "the default root filesystem must be ext4 (plan §11)"
    )

    # The destructive steps must come after the confirmation steps.
    order = settings.find("- summary")
    unpack = settings.find("- unpackfs")
    assert order != -1 and unpack != -1, "settings.conf is missing summary or unpackfs"
    assert order < unpack, (
        "the summary step must appear before unpackfs, so the user confirms the target "
        "disk before anything is written (plan §10.3)"
    )


def test_no_fixed_credentials_in_the_installer() -> None:
    users_conf = (REPO_ROOT / "installer" / "calamares" / "modules" / "users.conf").read_text(encoding="utf-8")
    for line in users_conf.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        if key.strip() in ("password", "username", "fullName", "email") and value.strip():
            raise AssertionError(
                f"users.conf sets {key.strip()} to a value; AstraOS must not ship "
                "fixed or pre-filled credentials (plan §10.4)"
            )
    assert "doAutologin: false" in users_conf, (
        "users.conf must disable autologin explicitly"
    )


# A private key is recognised by the shape of an armored block, not by the armor header
# text, for the same reason the shipped scanner (astraos-scan-secrets) is: the header text
# also appears in documentation, in a magic(5) database and as a compiled-in parser
# constant, and a check that fires on those is a check people learn to ignore.
#
# What this matches is a bare header line followed, within a few lines, by base64 payload or
# by the matching footer — which is what a key written into a file looks like, including one
# that lost its last line to a bad copy. Documentation that names the header is not a key,
# and a sample key inside a test fixture is only reported when it is written the way a real
# one would be written.
PRIVATE_KEY_BLOCK = re.compile(
    r"^-----BEGIN [A-Z0-9 ]*(?:PRIVATE|SECRET) KEY(?: BLOCK)?-----"
    r"(?:\r?\n[^\n]{0,80}){0,4}?\r?\n"
    r"(?:[A-Za-z0-9+/]{16,}={0,2}$"
    r"|-----END [A-Z0-9 ]*(?:PRIVATE|SECRET) KEY(?: BLOCK)?-----)",
    re.MULTILINE,
)


def test_no_secrets_committed() -> None:
    """Scan the repository for private keys and obvious tokens."""
    patterns = {
        "private key": PRIVATE_KEY_BLOCK,
        "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        "generic api key": re.compile(r"(?i)\bapi[_-]?key\s*[:=]\s*[\"'][A-Za-z0-9_\-]{16,}[\"']"),
        # The value class deliberately excludes whitespace, slashes, quotes and
        # brackets. Without that, ordinary code such as `grep -E '^password:' file`
        # or a Plymouth callback reading `"password:"` looks like a credential and the
        # check becomes noise that people learn to ignore.
        "password assignment": re.compile(
            r"(?i)\bpassword[\"']?\s*[:=]\s*[\"'][A-Za-z0-9_@#$%^&*.,!+=()\-]{6,}[\"']"
        ),
    }

    offenders: list[str] = []
    skip_dirs = {".git", "build", "dist", "node_modules", "__pycache__"}
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix.lower() in {".png", ".iso", ".gz", ".xz", ".deb"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pattern in patterns.items():
            if pattern.search(text):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: possible {label}")

    assert not offenders, (
        "possible secrets in the repository:\n  " + "\n  ".join(offenders)
    )


def test_gitignore_excludes_build_output() -> None:
    raw = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    # Check the RULES, not the prose: a comment explaining why a pattern is anchored
    # legitimately mentions the source path it protects.
    rules = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    rule_text = "\n".join(rules)

    for pattern in ("/build", "/dist", "*.iso", "*.log", "*.key"):
        assert pattern in rule_text, (
            f".gitignore has no rule for {pattern!r}; generated images and logs must not "
            "be committed (plan §4)"
        )

    # Anchoring matters. An unanchored "live-build/" rule also hides the real
    # config/live-build/ source directory from any tool that respects gitignore.
    assert "config/live-build" not in rule_text, (
        ".gitignore ignores config/live-build/, which is tracked source, not build output. "
        "Anchor the rule under /build/ instead."
    )
    for unanchored in ("^live-build/", "^config/"):
        import re as _re
        assert not _re.search(unanchored, rule_text, _re.M), (
            f".gitignore contains the unanchored rule {unanchored!r}, which would hide "
            "source directories"
        )


def test_critical_files_were_not_scaffolded_empty() -> None:
    """The build scripts must contain real logic, not placeholders."""
    for relative in ("scripts/build-iso.sh", "scripts/configure-live-build.sh",
                     "config/live-build/auto/config"):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert len(text) > 1500, f"{relative} is too short to be a real implementation"
        for placeholder in ("TODO", "FIXME", "not implemented", "Your code here"):
            assert placeholder not in text, (
                f"{relative} still contains the placeholder {placeholder!r}"
            )
