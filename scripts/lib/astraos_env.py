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
