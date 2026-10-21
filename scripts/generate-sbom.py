#!/usr/bin/env python3
"""Write an SPDX 2.3 software bill of materials for the packages this build produced.

Why this exists: a distribution is a set of packages, and a user (or an auditor, or
a future AstraOS installation) has no way to ask "what is in this image, and under
what licence?". The answer should be a file, not a question. The format is SPDX 2.3
JSON, because it is the one that tooling already reads.

What it says, and what it does not:

  * Every AstraOS package that went into the image is listed with its version, its
    SHA-256, its supplier and its licence (MIT, the licence of the AstraOS-specific
    work). The base distribution is Debian 13, and a Debian package keeps its own
    licence; the document says so rather than pretending one covers the other.
  * Files are not listed individually: the package list is the bill of materials for
    the distribution's own packages, and each package's own metadata points at the
    files it ships. The image itself can be added with --iso, which records its
    SHA-256.

The .deb files are read with a small `ar` reader and Python's own tarfile, so the
script needs no dpkg-deb and runs anywhere Python does.

Usage:
    scripts/generate-sbom.py --debs DIR --out FILE [--name NAME] [--iso FILE]

Exit codes:
    0  the bill of materials was written
    2  the package directory does not exist, or holds no packages
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

TOOL = "astraos-generate-sbom-0.1"
LICENCE = "MIT"
SUPPLIER = "Organization: AstraOS Project"
BASE_DISTRIBUTION = "Debian 13 (trixie)"


def _ar_members(path: Path):
    """Yield (name, bytes) for each member of an ar archive (a .deb is one)."""
    with path.open("rb") as handle:
        if handle.read(8) != b"!<arch>\n":
            raise ValueError(f"not an ar archive: {path}")
        while True:
            header = handle.read(60)
            if len(header) < 60:
                return
            name = header[0:16].decode("ascii", "replace").strip().rstrip("/")
            try:
                size = int(header[48:58].decode("ascii", "replace").strip() or "0")
            except ValueError:
                return
            data = handle.read(size)
            if size % 2:
                handle.read(1)  # members are padded to an even length
            yield name, data


def _control_text(path: Path) -> str:
    """The control file of a .deb, read without dpkg-deb."""
    for name, data in _ar_members(path):
        if not name.startswith("control.tar"):
            continue
        mode = {
            "control.tar.gz": "r:gz",
            "control.tar.xz": "r:xz",
            "control.tar.bz2": "r:bz2",
            "control.tar": "r:",
        }.get(name)
        if mode is None:
            continue
        with tarfile.open(fileobj=io.BytesIO(data), mode=mode) as tar:
            for member in tar.getmembers():
                if member.name.lstrip("./") == "control":
                    handle = tar.extractfile(member)
                    if handle is None:
                        continue
                    return handle.read().decode("utf-8", "replace")
    raise ValueError(f"no control file in {path}")


def _parse_control(text: str) -> dict[str, str]:
    """Parse a Debian control stanza into a dictionary."""
    fields: dict[str, str] = {}
    key = ""
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[0] in " \t" and key:
            fields[key] += "\n" + line.strip()
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        fields[key] = value.strip()
    return fields


def _spdx_id(name: str) -> str:
    return "SPDXRef-Package-" + re.sub(r"[^A-Za-z0-9.\-]", "-", name)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_entry(name: str, version: str, licence: str, digest: str,
                   architecture: str = "amd64", supplier: str = SUPPLIER) -> dict:
    return {
        "name": name,
        "SPDXID": _spdx_id(name),
        "versionInfo": version,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": licence,
        "licenseDeclared": licence,
        "copyrightText": "NOASSERTION",
        "supplier": supplier,
        "checksums": [{"algorithm": "SHA256", "checksumValue": digest}],
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": f"pkg:deb/debian/{name}@{version}?arch={architecture}",
            }
        ],
    }


def build_sbom(debs: list[Path], name: str, namespace: str, created: str,
               iso: Path | None) -> dict:
    packages = []
    for deb in sorted(debs):
        fields = _parse_control(_control_text(deb))
        package = fields.get("Package", deb.stem)
        version = fields.get("Version", "unknown")
        packages.append(
            _package_entry(package, version, LICENCE, _sha256(deb),
                           architecture=fields.get("Architecture", "amd64"))
        )

    if iso is not None:
        packages.append(
            _package_entry(iso.name, "0.2.0-alpha", LICENCE, _sha256(iso))
        )

    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": name,
        "documentNamespace": namespace,
        "creationInfo": {
            "created": created,
            "creators": [f"Tool: {TOOL}", SUPPLIER],
            "comment": (
                f"The AstraOS-specific packages are under the {LICENCE} licence. The base "
                f"distribution is {BASE_DISTRIBUTION}; every package inherited from Debian "
                "keeps its own licence, which its own source and copyright files state. "
                "This document lists the packages AstraOS builds; it does not restate "
                "Debian's own licences."
            ),
        },
        "packages": packages,
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relatedSpdxElement": package["SPDXID"],
                "relationshipType": "DESCRIBES",
            }
            for package in packages
        ],
    }
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--debs", required=True, help="directory holding the built .deb files")
    parser.add_argument("--out", required=True, help="where to write the bill of materials")
    parser.add_argument("--name", default="astraos", help="the document name")
    parser.add_argument("--namespace", default=None, help="the document namespace (a unique URL)")
    parser.add_argument("--iso", default=None, help="the built image, to record its hash")
    args = parser.parse_args(argv)

    debs_dir = Path(args.debs)
    if not debs_dir.is_dir():
        print(f"ERROR: no package directory: {debs_dir}", file=sys.stderr)
        return 2
    debs = sorted(debs_dir.rglob("*.deb"))
    if not debs:
        print(f"ERROR: no .deb files under {debs_dir}", file=sys.stderr)
        return 2

    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    namespace = args.namespace or (
        f"https://github.com/rafikulislammollaq-dev/astraos/sbom/{args.name}-{created}"
    )
    iso = Path(args.iso) if args.iso else None
    document = build_sbom(debs, args.name, namespace, created, iso)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(document['packages'])} package(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
