#!/usr/bin/env bash
# Generate and verify SHA-256 checksums for a release image (plan §16.1 step 18, §24).
#
# The checksum file is written next to the image and then verified against it, so the
# project never publishes a checksum that has not been checked against its own artifact.
#
# Usage: ./scripts/generate-checksums.sh dist/astraos-0.1.0-alpha-amd64.iso

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

ARTIFACT="${1:-}"
if [ -z "$ARTIFACT" ]; then
    printf 'usage: %s path/to/image.iso\n' "$0" >&2
    exit 2
fi
[ -f "$ARTIFACT" ] || { printf 'ERROR: no such file: %s\n' "$ARTIFACT" >&2; exit 1; }

command -v sha256sum >/dev/null 2>&1 || { printf 'ERROR: sha256sum is required\n' >&2; exit 1; }

DIR="$(cd "$(dirname "$ARTIFACT")" && pwd)"
NAME="$(basename "$ARTIFACT")"

printf '[astraos:checksums] computing sha256 for %s\n' "$NAME"

# The conventional format: SHA256 (filename) = hash, which 'sha256sum -c' accepts and
# which is what a user will find in any download verification guide.
TMP="$(mktemp)"
( cd "$DIR" && sha256sum "$NAME" > "$TMP" )
mv "$TMP" "${DIR}/${NAME}.sha256"
chmod 0644 "${DIR}/${NAME}.sha256"

HASH="$(cut -d' ' -f1 < "${DIR}/${NAME}.sha256")"
printf '[astraos:checksums] sha256 = %s\n' "$HASH"

# Verify immediately. Publishing an unverified checksum is worse than publishing none.
if ( cd "$DIR" && sha256sum -c "${NAME}.sha256" >/dev/null 2>&1 ); then
    printf '[astraos:checksums] verified: the checksum matches the image\n'
else
    printf '[astraos:checksums] ERROR: the checksum does NOT match the image\n' >&2
    exit 1
fi

printf '[astraos:checksums] wrote %s.sha256\n' "$NAME"
printf '\nTo verify a download:\n  sha256sum -c %s.sha256\n' "$NAME"
