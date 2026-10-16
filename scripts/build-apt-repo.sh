#!/usr/bin/env bash
# Assemble an APT repository from the AstraOS .deb packages.
#
# WHY THIS EXISTS
#
#   An installed AstraOS currently gets Debian packages and nothing else: there is no
#   archive carrying astraos-* updates, so "installed AstraOS" today means "frozen at
#   the version on the medium". This script is the archive half of the fix - the
#   layout an HTTP server (or a GitHub Pages branch, or a USB stick with a file://
#   source) serves as-is:
#
#       pool/main/<package>/<file>.deb           the package files
#       dists/stable/main/binary-amd64/Packages  the index apt reads
#       dists/stable/Release                     hashes + size of that index
#       dists/stable/InRelease                   Release, signed (only with --key)
#       astraos-archive-keyring.gpg              the public half (only with --key)
#
# WHY NOT dpkg-scanpackages
#
#   It lives in dpkg-dev, which the build host is not required to have (bootstrap
#   installs dpkg-deb only, because building these packages needs no more than that).
#   The two formats are small and documented, and generating them here means the
#   hashes are computed from the actual bytes at the moment they are written - and
#   then read back and checked again before this script reports success. A repository
#   whose index does not match its pool is worse than no repository: apt would fetch
#   a file it refuses to trust, or worse, trust an index that describes nothing.
#
# SIGNING
#
#   Pass --key FINGERPRINT to sign with an existing GPG key. This never generates a
#   key and never stores one (plan: private signing keys do not live in this
#   repository), and it refuses to continue if signing was requested and failed.
#   Without --key the repository is assembled unsigned and the script says so
#   loudly: an unsigned Release carries integrity hashes but no authenticity, so it
#   is only fit for controlled use (CI artifacts, a local file:// medium with
#   "[trusted=yes]") - never for a fleet that accepts updates over a network.
#
# Usage:
#   ./scripts/build-apt-repo.sh [--debs DIR] [--out DIR] [--key FINGERPRINT]
#
# Defaults: --debs build/live-build/packages --out dist/apt-repo

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=/dev/null
. "${REPO_ROOT}/config/distribution.env"
. "${REPO_ROOT}/VERSION"

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
    sed -n '/^# Usage:/,/^# Defaults:/p' "$0" | sed 's/^# \{0,2\}//'
}

DEBS="${REPO_ROOT}/${ASTRAOS_BUILD_DIR}/packages"
OUT="${REPO_ROOT}/dist/apt-repo"
KEY=""

while [ $# -gt 0 ]; do
    case "$1" in
        --debs) DEBS="$2"; shift 2 ;;
        --out)  OUT="$2";  shift 2 ;;
        --key)  KEY="$2";  shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "unknown argument: $1" ;;
    esac
done

command -v dpkg-deb >/dev/null 2>&1 \
    || die "dpkg-deb is not installed. Run scripts/bootstrap-build-environment.sh"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is not installed"
command -v gzip >/dev/null 2>&1 || die "gzip is not installed"

[ -d "$DEBS" ] || die "no package directory: $DEBS (build the packages first: scripts/build-packages.sh)"
debs=()
for deb in "$DEBS"/*.deb; do
    [ -e "$deb" ] || continue
    debs+=("$deb")
done
[ "${#debs[@]}" -gt 0 ] || die "no .deb files in $DEBS"

case "$OUT" in
    ""|/|"$HOME"|"$REPO_ROOT") die "refusing to wipe suspicious --out: '$OUT'" ;;
esac

# The repository is rebuilt from scratch every time: a stale index is how an archive
# serves a version that no longer exists. The wipe is bounded to $OUT, which was
# checked above, and it is announced before it happens.
say "assembling an APT repository from ${#debs[@]} package(s) in $DEBS"
say "output: $OUT (rebuilt from scratch)"
rm -rf "$OUT"
mkdir -p "$OUT/dists/stable/main/binary-amd64"

PACKAGES="$OUT/dists/stable/main/binary-amd64/Packages"
: > "$PACKAGES"

for deb in "${debs[@]}"; do
    name="$(dpkg-deb -f "$deb" Package)"
    version="$(dpkg-deb -f "$deb" Version)"
    [ -n "$name" ] || die "cannot read Package from $deb"
    [ -n "$version" ] || die "cannot read Version from $deb"

    pool="pool/main/${name}/$(basename "$deb")"
    mkdir -p "$OUT/$(dirname "$pool")"
    cp -f "$deb" "$OUT/$pool"

    # The stanza is the package's own control data, verbatim, plus the three fields
    # an index adds: where the file lives, how big it is, and what it hashes to.
    {
        dpkg-deb -f "$deb"
        printf 'Filename: %s\n' "$pool"
        printf 'Size: %s\n' "$(stat -c %s "$deb")"
        printf 'SHA256: %s\n' "$(sha256sum "$deb" | cut -d' ' -f1)"
        printf '\n'
    } >> "$PACKAGES"
done
# -c writes the gzipped copy to stdout and leaves the plain index in place: apt
# publishes both forms and a client may fetch either, so both must exist and match.
gzip -9nc "$PACKAGES" > "$PACKAGES.gz"

# Release carries the hashes of the indices in the path form apt looks them up
# (relative to dists/stable/), and the date lets a client refuse a future-dated one.
release_tmp="$(mktemp)"
{
    printf 'Origin: AstraOS\n'
    printf 'Label: AstraOS\n'
    printf 'Suite: stable\n'
    printf 'Codename: stable\n'
    printf 'Architectures: amd64\n'
    printf 'Components: main\n'
    printf 'Description: AstraOS archive\n'
    printf 'Date: %s\n' "$(date -Ru)"
    printf 'SHA256:\n'
    printf ' %s %s %s\n' \
        "$(sha256sum "$PACKAGES" | cut -d' ' -f1)" "$(stat -c %s "$PACKAGES")" \
        "main/binary-amd64/Packages"
    printf ' %s %s %s\n' \
        "$(sha256sum "$PACKAGES.gz" | cut -d' ' -f1)" "$(stat -c %s "$PACKAGES.gz")" \
        "main/binary-amd64/Packages.gz"
} > "$release_tmp"
mv "$release_tmp" "$OUT/dists/stable/Release"

if [ -n "$KEY" ]; then
    command -v gpg >/dev/null 2>&1 || die "--key was given but gpg is not installed"
    gpg --batch --yes --local-user "$KEY" --armor --detach-sign \
        -o "$OUT/dists/stable/Release.gpg" "$OUT/dists/stable/Release" \
        || die "signing Release failed (key: $KEY)"
    gpg --batch --yes --local-user "$KEY" --clearsign \
        -o "$OUT/dists/stable/InRelease" "$OUT/dists/stable/Release" \
        || die "clearsigning Release failed (key: $KEY)"
    gpg --batch --yes --export "$KEY" > "$OUT/astraos-archive-keyring.gpg" \
        || die "exporting the public key failed (key: $KEY)"
    gpg --batch --verify "$OUT/dists/stable/InRelease" >/dev/null 2>&1 \
        || die "the signature that was just written does not verify; refusing to report success"
    say "signed with $KEY; public key exported to astraos-archive-keyring.gpg"
else
    say ""
    say "WARNING: this repository is UNSIGNED (no --key was given)."
    say "It carries integrity hashes but no authenticity: use it only where the"
    say "transport is controlled (CI artifacts, a local file:// medium). To sign:"
    say "  $0 --debs '$DEBS' --out '$OUT' --key <fingerprint>"
    say ""
fi

# File modes: mktemp and gpg create private files, and whatever serves this tree has
# to be able to read it. Everything served is world-readable, nothing writable.
for serving in "$OUT/dists/stable/Release" "$OUT/dists/stable/InRelease" \
                "$OUT/dists/stable/Release.gpg" "$OUT/astraos-archive-keyring.gpg"; do
    if [ -f "$serving" ]; then
        chmod 0644 "$serving"
    fi
done

# --- read back what was written -------------------------------------------------------
# The point of a repository is that apt can trust the index to describe the pool, so
# every file the index names is opened again and checked: exists, right size, right
# hash - and the Release, in turn, is checked against the indices actually on disk.
checked=0
filename=""
size=""
while IFS= read -r line; do
    case "$line" in
        Filename:*) filename="${line#Filename: }" ;;
        Size:*) size="${line#Size: }" ;;
        SHA256:*)
            hash="${line#SHA256: }"
            [ -f "$OUT/$filename" ] || die "the index names a missing file: $filename"
            actual_size="$(stat -c %s "$OUT/$filename")"
            [ "$actual_size" = "$size" ] \
                || die "size mismatch for $filename: index says $size, disk says $actual_size"
            actual_hash="$(sha256sum "$OUT/$filename" | cut -d' ' -f1)"
            [ "$actual_hash" = "$hash" ] || die "hash mismatch for $filename"
            checked=$((checked + 1))
            ;;
    esac
done < "$PACKAGES"
[ "$checked" -eq "${#debs[@]}" ] \
    || die "the index describes $checked package(s), not ${#debs[@]}"

for index in "$PACKAGES" "$PACKAGES.gz"; do
    rel="main/binary-amd64/$(basename "$index")"
    if ! grep -q -- "$(sha256sum "$index" | cut -d' ' -f1) $(stat -c %s "$index") $rel" \
        "$OUT/dists/stable/Release"; then
        die "Release does not carry the current hash of $rel"
    fi
done

say ""
say "repository ready: $OUT"
say "  ${#debs[@]} package(s); index $(stat -c %s "$PACKAGES") bytes, $(stat -c %s "$PACKAGES.gz") bytes gzipped"
if [ -n "$KEY" ]; then
    say "  client sources line:"
    say "    deb [signed-by=/usr/share/keyrings/astraos-archive-keyring.gpg] <URL>/ stable main"
else
    say "  client sources line (controlled use only, the repository is unsigned):"
    say "    deb [trusted=yes] file://$OUT stable main"
fi
