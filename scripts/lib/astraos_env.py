"""Shared helpers for reading the AstraOS configuration.

Standard library only: the build host is not guaranteed to have PyYAML, and the
build scripts must never need network access just to read their own config.

Used by scripts/ and tests/.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DISTRIBUTION_ENV = REPO_ROOT / "config" / "distribution.env"
BRANDING_ENV = REPO_ROOT / "config" / "branding.env"
VERSION_FILE = REPO_ROOT / "VERSION"

# KEY="value"  /  KEY=value  /  KEY='value'
_ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a POSIX-style KEY=value configuration file.

    Refuses lines that try to execute commands: this file is read by tooling that
    must not run arbitrary code from the repository config.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        raise FileNotFoundError(f"configuration file not found: {path}")

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT.match(line)
        if not match:
            raise ValueError(f"{path.name}:{lineno}: not a KEY=value assignment: {raw!r}")
        key, value = match.group(1), match.group(2).strip()
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'") and len(value) >= 2:
            value = value[1:-1]
        if "$(" in value or "`" in value:
            raise ValueError(
                f"{path.name}:{lineno}: command substitution is not allowed in config: {raw!r}"
            )
        values[key] = value
    return values


def distribution() -> dict[str, str]:
    return parse_env_file(DISTRIBUTION_ENV)


def branding() -> dict[str, str]:
    return parse_env_file(BRANDING_ENV)


def version() -> dict[str, str]:
    return parse_env_file(VERSION_FILE)


def package_lists() -> dict[str, list[str]]:
    """Return {list filename: [package, ...]} for config/package-lists/*.list.chroot."""
    lists_dir = REPO_ROOT / "config" / "package-lists"
    result: dict[str, list[str]] = {}
    for path in sorted(lists_dir.glob("*.list.chroot")):
        packages: list[str] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                packages.append(line)
        result[path.name] = packages
    return result


def all_packages() -> dict[str, list[str]]:
    """Return {package_name: [list files that request it]} across every list."""
    owners: dict[str, list[str]] = {}
    for filename, packages in package_lists().items():
        for package in packages:
            owners.setdefault(package, []).append(filename)
    return owners


# Dependency fields the .deb packages declare. Resolved by apt when the image is built, so a
# name that does not exist stops the build just as surely as a wrong package list entry.
CONTROL_DEPENDENCY_FIELDS = ("Depends", "Recommends", "Pre-Depends")


def own_packages() -> set[str]:
    """Names of the packages this repository builds, one per packages/*/control.in."""
    return {path.parent.name for path in (REPO_ROOT / "packages").glob("*/control.in")}


def control_dependencies() -> list[tuple[tuple[str, ...], str]]:
    """Return (alternatives, source) for every dependency the AstraOS packages declare.

    `alternatives` is a tuple because Debian allows `a | b`, where any one of them satisfies
    the requirement; checking that all of them exist would be wrong.

    `source` reads like `packages/astraos-installer/control.in Depends`, so a failure can
    name the file and field instead of just the package.
    """
    groups: list[tuple[tuple[str, ...], str]] = []

    for control in sorted((REPO_ROOT / "packages").glob("*/control.in")):
        source_file = control.relative_to(REPO_ROOT).as_posix()
        # Unfold continuation lines: a dependency list may be wrapped.
        text = control.read_text(encoding="utf-8").replace("\n ", " ").replace("\n\t", " ")

        for line in text.splitlines():
            field, separator, value = line.partition(":")
            if not separator or field.strip() not in CONTROL_DEPENDENCY_FIELDS:
                continue
            for entry in value.split(","):
                alternatives: list[str] = []
                for alternative in entry.split("|"):
                    name = alternative.split("(", 1)[0].strip()
                    # Drop an architecture qualifier such as `foo:any`.
                    name = name.split(":", 1)[0].strip()
                    # A substvar or a build profile is not a package name to look up.
                    if not name or "$" in name or "<" in name:
                        continue
                    alternatives.append(name)
                if alternatives:
                    groups.append((tuple(alternatives), f"{source_file} {field.strip()}"))

    return groups
