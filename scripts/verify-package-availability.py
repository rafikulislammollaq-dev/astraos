#!/usr/bin/env python3
"""Verify that every package AstraOS asks for actually exists in Debian.

Plan references: §16.1 step 5-6 ("validate the package list", "verify access to the
required package repositories"), §18.1 (static tests), §28 Rule 4 (never fabricate).

This reads the real archive indexes for the pinned release and fails loudly on any
name that does not exist, so a typo in a package list cannot survive until a
half-hour into a build.

Indexes are cached under build/cache/archive/ and are re-downloaded only when the
cached copy is older than --max-age-days.

Exit codes:
  0  every package resolved
  1  one or more packages missing (or only available as a virtual package)
  2  the archive could not be reached or parsed
"""

from __future__ import annotations

import argparse
import lzma
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import astraos_env  # noqa: E402

AREAS = ("main", "contrib", "non-free", "non-free-firmware")
USER_AGENT = "AstraOS-build/0.1 (package availability verifier)"
INDEX_TIMEOUT = 120


def fetch(url: str, cache_file: Path, max_age_days: float) -> bytes:
    """Return the bytes of url, using cache_file when it is fresh enough."""
    fresh = (
        cache_file.is_file()
        and (time.time() - cache_file.stat().st_mtime) < max_age_days * 86400
    )
    if fresh:
        print(f"  [cache] {cache_file.name}")
        return cache_file.read_bytes()

    print(f"  [fetch] {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=INDEX_TIMEOUT) as response:
            if response.status != 200:
                raise urllib.error.HTTPError(url, response.status, "unexpected status", {}, None)
            payload = response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise SystemExit(f"ERROR: cannot reach the package archive: {url}: {exc}")

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(payload)
    return payload


def parse_packages(text: str) -> tuple[set[str], set[str], dict[str, str]]:
    """Parse a Debian Packages index.

    Returns (real_names, provided_names, name -> version).
    """
    real: set[str] = set()
    provided: set[str] = set()
    versions: dict[str, str] = {}

    name = version = provides = None
    for line in text.splitlines():
        if not line.strip():
            if name:
                real.add(name)
                if version:
                    versions[name] = version
                if provides:
                    for entry in provides.split(","):
                        candidate = entry.strip().split("(", 1)[0].strip()
                        if candidate:
                            provided.add(candidate)
            name = version = provides = None
            continue
        if line[0] in " \t":  # continuation of the previous field
            continue
        field, _, value = line.partition(":")
        field, value = field.strip(), value.strip()
        if field == "Package":
            name = value
        elif field == "Version":
            version = value
        elif field == "Provides":
            provides = value

    if name:  # last stanza when the file does not end with a blank line
        real.add(name)
        if version:
            versions[name] = version
        if provides:
            for entry in provides.split(","):
                candidate = entry.strip().split("(", 1)[0].strip()
                if candidate:
                    provided.add(candidate)
    return real, provided, versions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-age-days", type=float, default=7.0,
                        help="re-use a cached index younger than this (default: 7)")
    parser.add_argument("--show-kernel", action="store_true",
                        help="print the resolved linux-image version and exit")
    args = parser.parse_args()

    config = astraos_env.distribution()
    mirror = config["ASTRAOS_DEBIAN_MIRROR"]
    suite = config["ASTRAOS_BASE_SUITE"]
    packages = astraos_env.all_packages()

    print(f"AstraOS package availability check")
    print(f"  release : {config['ASTRAOS_BASE_DISTRIBUTION']} "
          f"{config['ASTRAOS_BASE_RELEASE_VERSION']} ({suite})")
    print(f"  arch    : {config['ASTRAOS_ARCH_DEB']}")
    print(f"  mirror  : {mirror}")
    print(f"  asked   : {len(packages)} distinct packages across "
          f"{len(astraos_env.package_lists())} lists")
    print(f"  declared: {len(astraos_env.control_dependencies())} dependency groups in the "
          f"AstraOS packages")
    print()

    cache_dir = astraos_env.REPO_ROOT / "build" / "cache" / "archive"
    real: set[str] = set()
    provided: set[str] = set()
    versions: dict[str, str] = {}

    for area in AREAS:
        url = f"{mirror}/dists/{suite}/{area}/binary-{config['ASTRAOS_ARCH_DEB']}/Packages.xz"
        cache_file = cache_dir / f"{suite}-{area}-{config['ASTRAOS_ARCH_DEB']}-Packages.xz"
        try:
            payload = fetch(url, cache_file, args.max_age_days)
            text = lzma.decompress(payload).decode("utf-8", errors="replace")
        except (lzma.LZMAError, OSError) as exc:
            print(f"ERROR: cannot decompress the {area} index: {exc}")
            return 2
        area_real, area_provided, area_versions = parse_packages(text)
        print(f"  {area:20s} {len(area_real):6d} packages")
        real |= area_real
        provided |= area_provided
        versions.update(area_versions)

    print()

    if args.show_kernel:
        for candidate in ("linux-image-amd64", "linux-image-6.12-amd64"):
            if candidate in versions:
                print(f"{candidate} {versions[candidate]}")
        return 0

    missing = sorted(name for name in packages if name not in real and name not in provided)
    virtual = sorted(name for name in packages if name not in real and name in provided)
    unresolved = missing + virtual

    # The AstraOS .deb packages declare their own dependencies, and apt resolves those when
    # the image is assembled. A name that does not exist there stops the build after every
    # package has been downloaded — which is exactly how `Depends: kpmcore` was found.
    dependency_groups = astraos_env.control_dependencies()
    # The AstraOS packages depend on each other; those names are built here, so they will not
    # be in the Debian archive and are not a failure.
    own = astraos_env.own_packages()
    unsatisfiable: list[tuple[tuple[str, ...], str]] = []
    for alternatives, source in dependency_groups:
        if any(name in real or name in provided or name in own for name in alternatives):
            continue
        unsatisfiable.append((alternatives, source))

    if unsatisfiable:
        print(f"The AstraOS packages declare {len(dependency_groups)} dependency group(s); "
              f"{len(unsatisfiable)} cannot be satisfied:")
        for alternatives, source in unsatisfiable:
            joined = " | ".join(alternatives)
            print(f"  x {joined}\n      declared by: {source}")
        print()
    else:
        internal = [
            group for group, _ in dependency_groups if any(name in own for name in group)
        ]
        print(f"OK: all {len(dependency_groups)} dependencies declared by the AstraOS "
              f"packages resolve ({len(internal)} of them are AstraOS packages built here).")
        print()

    if virtual:
        # A virtual package is installable, but it is usually a sign that the list
        # should name a real provider. Reported as a failure so the lists stay exact.
        print(f"Available only as virtual packages ({len(virtual)}):")
        for name in virtual:
            requested_by = ", ".join(packages[name])
            print(f"  ~ {name}\n      requested by: {requested_by}")
        print()

    if missing:
        print(f"MISSING from Debian {suite} ({len(missing)}):")
        for name in missing:
            requested_by = ", ".join(packages[name])
            print(f"  x {name}\n      requested by: {requested_by}")
        print()

    if unresolved or unsatisfiable:
        print(f"FAIL: {len(unresolved)} configured package name(s) and "
              f"{len(unsatisfiable)} declared dependency group(s) do not resolve to a real")
        print(f"      package in Debian {suite}.")
        print("      Fix the lists or the control files, or change the pinned release")
        print("      deliberately.")
        return 1

    print(f"OK: all {len(packages)} packages exist in Debian {suite}.")
    kernel = versions.get("linux-image-amd64", "unknown")
    print(f"    kernel package linux-image-amd64 = {kernel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
