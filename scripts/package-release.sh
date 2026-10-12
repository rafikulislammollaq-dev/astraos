#!/usr/bin/env bash
# Assemble a release directory from the built artifacts (plan §16.1, §24).
#
# Assembles dist/release-<version>/ containing everything a tester needs and nothing
# that would mislead them. The checksum is verified against the image before anything is
# copied, so a release directory cannot contain an artifact whose checksum does not match
# (plan §28 Rule 4).
#
# This script does NOT sign anything and does NOT upload anything. Release signing is not
# implemented in 0.1.0 (see docs/RELEASE_PROCESS.md §6).

# `set -e` is correct here: assembling a release directory either completes or it does
# not, and a half-populated release directory is worse than no release directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=/dev/null
. "${REPO_ROOT}/config/distribution.env"
. "${REPO_ROOT}/VERSION"

DIST_DIR="${REPO_ROOT}/${ASTRAOS_DIST_DIR}"
RELEASE_NAME="release-${ASTRAOS_VERSION}-${ASTRAOS_RELEASE_STAGE,,}"
RELEASE_DIR="${DIST_DIR}/${RELEASE_NAME}"

say() { printf '[astraos:release] %s\n' "$*"; }
fail() { printf '[astraos:release] ERROR: %s\n' "$*" >&2; exit 1; }

# --- Find the image ----------------------------------------------------------
ISO=""
if [ -n "${1:-}" ]; then
    ISO="$1"
else
    ISO="$(ls -1t "${DIST_DIR}"/*.iso 2>/dev/null | head -n1 || true)"
fi

[ -n "$ISO" ] || fail "no ISO found in ${DIST_DIR}. Build one first: ./scripts/build-iso.sh"
[ -f "$ISO" ] || fail "no such file: $ISO"

say "packaging $(basename "$ISO")"

# --- Verify before copying ---------------------------------------------------
CHECKSUM_FILE="${ISO}.sha256"
if [ ! -f "$CHECKSUM_FILE" ]; then
    say "no checksum file found; generating one"
    "${SCRIPT_DIR}/generate-checksums.sh" "$ISO" || fail "could not generate a checksum"
fi

if ! ( cd "$(dirname "$ISO")" && sha256sum -c "$(basename "$CHECKSUM_FILE")" >/dev/null 2>&1 ); then
    fail "the checksum does NOT match the image. Refusing to package an artifact that fails its own verification."
fi
say "checksum verified against the image"

# --- Assemble ----------------------------------------------------------------
rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"

cp -f "$ISO" "$RELEASE_DIR/"
cp -f "$CHECKSUM_FILE" "$RELEASE_DIR/"

MANIFEST="${ISO}.manifest"
if [ -f "$MANIFEST" ]; then
    cp -f "$MANIFEST" "$RELEASE_DIR/"
else
    say "no manifest exists; generating one"
    "${SCRIPT_DIR}/generate-manifest.sh" "$ISO"
    if [ -f "$MANIFEST" ]; then
        cp -f "$MANIFEST" "$RELEASE_DIR/"
    fi
fi

# The AstraOS package manifest, so a tester can see exactly which AstraOS packages are in
# the image and their checksums.
PKG_MANIFEST="${REPO_ROOT}/${ASTRAOS_BUILD_DIR}/packages/astraos-packages.txt"
if [ -f "$PKG_MANIFEST" ]; then
    cp -f "$PKG_MANIFEST" "$RELEASE_DIR/"
else
    say "no AstraOS package manifest found; the release will not list the AstraOS packages"
fi

# Documentation: ship the same set that is installed into the image.
# NOTE: `[ -f x ] && cp` would return non-zero when the test fails, which under `set -e`
# would abort the script. Explicit if-blocks are used for that reason.
mkdir -p "${RELEASE_DIR}/docs"
for doc in "${REPO_ROOT}/docs"/*.md; do
    if [ -f "$doc" ]; then
        cp -f "$doc" "${RELEASE_DIR}/docs/"
    fi
done
for doc in README.md CHANGELOG.md SECURITY.md CONTRIBUTING.md LICENSE; do
    if [ -f "${REPO_ROOT}/${doc}" ]; then
        cp -f "${REPO_ROOT}/${doc}" "${RELEASE_DIR}/"
    fi
done

# --- Release notes -----------------------------------------------------------
# Generated from the actual values, never hand-written, so the notes cannot claim a test
# result that did not happen.
SHA256="$(cut -d' ' -f1 < "$CHECKSUM_FILE")"
SIZE="$(wc -c < "$ISO")"

cat > "${RELEASE_DIR}/RELEASE-NOTES.md" <<EOF
# AstraOS ${ASTRAOS_VERSION} ${ASTRAOS_RELEASE_STAGE} — codename ${ASTRAOS_CODENAME}

An independent Linux desktop operating system based on
${ASTRAOS_BASE_DISTRIBUTION} ${ASTRAOS_BASE_RELEASE_VERSION} (${ASTRAOS_BASE_RELEASE_CODENAME}).

## Artifact

| | |
|---|---|
| File | \`$(basename "$ISO")\` |
| Size | ${SIZE} bytes |
| SHA-256 | \`${SHA256}\` |
| Architecture | ${ASTRAOS_ARCH} |
| Built | $(date -u +%Y-%m-%dT%H:%M:%SZ) |

Verify before you boot it:

\`\`\`bash
sha256sum -c $(basename "$CHECKSUM_FILE")
\`\`\`

## What has been verified

$(if [ -f "$MANIFEST" ]; then sed -n '/^\[validation\]/,/^$/p' "$MANIFEST"; else echo "See the manifest for the validation record."; fi)

## What has NOT been verified

This is an alpha release. Unless the manifest above says otherwise, the following have
**not** been tested: booting the image, the installer, an installed system, networking,
physical hardware, and disk encryption. See \`docs/KNOWN_LIMITATIONS.md\`.

## Before installing on real hardware

Do not. Run the virtual machine procedure in
\`docs/INSTALLATION_VIRTUALBOX.md\` first. It costs an hour and it finds most defects
without risking any data.

## Support

AstraOS has no support commitment and no security team. See \`SECURITY.md\` for the
reporting process and for what is explicitly not claimed.

## Licensing

GPL-3.0-or-later. AstraOS is an independent distribution based on Debian GNU/Linux and is
not an official Debian release. See \`LICENSE\` and \`docs/ARCHITECTURE.md\`.
EOF

# --- Summarise ---------------------------------------------------------------
COUNT="$(find "$RELEASE_DIR" -type f | wc -l)"
TOTAL="$(du -sh "$RELEASE_DIR" 2>/dev/null | cut -f1)"

printf '\n'
say "release directory ready: ${RELEASE_DIR}"
say "  files : ${COUNT}"
say "  size  : ${TOTAL}"
say "  sha256: ${SHA256}"
printf '\n'
say "Reminder: creating this directory is not a release. See docs/RELEASE_PROCESS.md for"
say "the checklist that must be answered first, including the tests that have NOT run."
