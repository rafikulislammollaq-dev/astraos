#!/usr/bin/env bash
# create-archive-signing-key.sh - make the key that signs the AstraOS archive.
#
# WHY A KEY AT ALL
#
#   apt refuses to install from an archive it cannot verify. An unsigned archive
#   can only be used with [trusted=yes], which means "trust whatever arrives" -
#   and for an *update channel* that is exactly the wrong thing: anyone who can
#   intercept the connection could then serve a modified package. A key fixes
#   that: the public half goes in the image, the private half signs the archive,
#   and apt checks every package against the public half it already trusts.
#
#   Nothing breaks without a key. The archive is published unsigned and the
#   publisher says so; the client line in the image ships disabled. The key is
#   what lets you turn that line on and update safely.
#
# WHAT IT DOES
#
#   1. creates a key in a TEMPORARY keyring (your own keyring is never touched);
#   2. writes the PUBLIC half into the image's keyring directory, ready to be
#      committed - the public half is not a secret;
#   3. prints the PRIVATE half, base64 encoded, for you to paste into the
#      repository's secrets. The private half never goes in the repository and
#      never leaves your machine except through that secret.
#
# USAGE
#
#   ./scripts/create-archive-signing-key.sh
#   ./scripts/create-archive-signing-key.sh "AstraOS archive" "you@example.com"
#
# Then: Settings -> Secrets and variables -> Actions -> New repository secret
#   name:  APT_ARCHIVE_SIGNING_KEY
#   value: the base64 blob it printed
# and (optional, for a passphrase-protected key) a second secret:
#   name:  APT_ARCHIVE_SIGNING_PASSPHRASE

set -euo pipefail

NAME="${1:-AstraOS archive signing key}"
EMAIL="${2:-maintainers@astraos.invalid}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEYRING_DIR="${REPO_ROOT}/packages/astraos-base/root/usr/share/keyrings"

command -v gpg >/dev/null 2>&1 || {
    printf 'ERROR: gpg is not installed.\n' >&2
    printf '       Debian/Ubuntu: sudo apt install gnupg\n' >&2
    exit 1
}

WORK="$(mktemp -d)"
chmod 700 "$WORK"
export GNUPGHOME="$WORK"
trap 'rm -rf "$WORK"' EXIT

printf 'Creating a signing key in a temporary keyring (yours is untouched)...\n\n'
gpg --batch --pinentry-mode loopback --passphrase '' \
    --quick-generate-key "$NAME <$EMAIL>" rsa4096 sign never >/dev/null 2>&1

fingerprint="$(gpg --batch --list-keys --with-colons | awk -F: '/^fpr/{print $10; exit}')"
[ -n "$fingerprint" ] || { printf 'ERROR: the key was not created.\n' >&2; exit 1; }

gpg --batch --armor --export-secret-keys "$fingerprint" > "${WORK}/secret.asc"
gpg --batch --armor --export "$fingerprint" > "${WORK}/public.asc"

mkdir -p "$KEYRING_DIR"
cp -f "${WORK}/public.asc" "${KEYRING_DIR}/astraos-archive-keyring.asc"
printf 'The public key is in the image source at:\n  %s\n' \
    "packages/astraos-base/root/usr/share/keyrings/astraos-archive-keyring.asc"
printf 'Commit that file, and the image can enable the archive line.\n\n'

printf '=== Fingerprint ===\n%s\n\n' "$fingerprint"
printf '=== 1. Repository secret: APT_ARCHIVE_SIGNING_KEY ===\n'
printf 'Settings -> Secrets and variables -> Actions -> New repository secret\n\n'
printf 'value (one line, base64):\n'
base64 -w0 "${WORK}/secret.asc" 2>/dev/null || base64 "${WORK}/secret.asc" | tr -d '\n'
printf '\n\n'
printf '=== 2. Then let CI publish a signed archive ===\n'
printf 'Run the "Publish the APT archive" workflow. It signs the archive, exports the\n'
printf 'public keyring next to it, and says so in the run summary.\n'
