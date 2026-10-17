# AstraOS release process

## 1. Versioning

`MAJOR.MINOR.PATCH`, plus a codename and a release stage.

| Field | Meaning | Recorded in |
|---|---|---|
| Version | Semantic version of the distribution | `VERSION`, `config/distribution.env` |
| Codename | Release name | same |
| Stage | `Alpha`, `Beta`, or `Stable` | same |
| Base release | The pinned Debian release | `config/distribution.env` |
| ISO name | `astraos-<version>-<stage>-<arch>.iso` | produced by `build-iso.sh` |

**A MINOR or MAJOR release pins a new Debian base.** The base release is recorded in one
file and verified against the live archive before any build, so a release cannot silently
change which Debian version it was built from (plan §5).

Full history: [`../CHANGELOG.md`](../CHANGELOG.md).

## 2. Updating the pinned base deliberately

1. Edit `config/distribution.env`: `ASTRAOS_BASE_RELEASE_CODENAME`,
   `ASTRAOS_BASE_RELEASE_VERSION`, `ASTRAOS_BASE_SUITE`, `ASTRAOS_SECURITY_SUITE`,
   `ASTRAOS_UPDATES_SUITE`.
2. Update `config/archives/astraos.list.chroot` to match.
3. Run `python3 scripts/verify-package-availability.py`. Versioned package names change
   between releases — `libkpmcore12` may become `libkpmcore13`, `polkitd` may be renamed
   again. The verifier names every breakage.
4. Update `VERSION`.
5. Build and test in a virtual machine.

This procedure exists because the failure mode is silent: a base release that changes
underneath a release branch produces an image nobody tested (plan §5).

## 3. Release checklist

Every item must be answered. **UNTESTED is an acceptable answer; an unverified PASS is
not** (plan §27).

### Build

- [ ] `make check` passes
- [ ] `make lint` passes
- [ ] `python3 scripts/verify-package-availability.py` passes
- [ ] `python3 branding/tools/render_assets.py` produces no unexpected diff
- [ ] `./scripts/build-iso.sh` completes
- [ ] `./scripts/validate-iso.sh` reports PASS
- [ ] The `.sha256` file verifies against the image
- [ ] The `.manifest` contains no fabricated values

### Test

- [ ] Live ISO boots in VirtualBox, UEFI
- [ ] Live ISO boots in VirtualBox, legacy BIOS
- [ ] Live desktop starts, panel and theme correct
- [ ] Live applications launch (terminal, file manager, browser)
- [ ] Networking works in the live session
- [ ] Installer launches
- [ ] Installation completes on a disposable virtual disk
- [ ] Installed system boots **without** the ISO attached
- [ ] Login works with the account created during installation
- [ ] `astraos-info` reports `installed`
- [ ] `systemctl --failed` is empty
- [ ] `sudo apt update` succeeds
- [ ] Restart and shutdown work
- [ ] The live account does not exist on the installed system

### Documentation

- [ ] `docs/KNOWN_LIMITATIONS.md` reflects the tests actually performed
- [ ] `CHANGELOG.md` records the release
- [ ] The manifest's `[validation]` section is accurate
- [ ] Any newly discovered limitation is documented, not hidden

### Security

- [ ] No secrets in the repository or the image
- [ ] Root is locked; no `NOPASSWD` rule
- [ ] No SSH server installed
- [ ] APT signature verification intact

## 4. Producing the release artifacts

```bash
./scripts/package-release.sh
```

This assembles `dist/release-<version>/` containing the ISO, its `.sha256`, its
`.manifest`, the package manifest, the documentation set and a generated `RELEASE-NOTES`
file. It verifies the checksum against the image before copying anything.

The release directory is not committed. Publish it as a build artifact or attach it to a
release; ISO files are never committed to git (plan §4, §17).

## 5. Where the ISO comes from

Two supported routes, and only two:

1. **CI:** run the **Build ISO** workflow manually. The image is uploaded as an artifact
   with its checksum and manifest, retained for 14 days.
2. **A Linux host:** `./scripts/build-iso.sh`.

There is no third route. In particular, **do not** redistribute a renamed Debian ISO: it
would not be built from this configuration, and plan §6.2 forbids representing it as
AstraOS.

## 6. Signing

Not implemented. AstraOS does not sign ISOs or packages. Anyone downloading an image
should verify the published SHA-256 and understand that a checksum verified over an
untrusted channel proves only that the transfer was intact, not that the file is
authentic.

If signing is added later, the private key must live outside the repository and outside CI
secrets (plan §17), and the public key and verification instructions must be published
separately from the artifact.

## 7. After the release

1. Tag the release commit.
2. Update `CHANGELOG.md` for the next development cycle.
3. Record every limitation found during testing in `KNOWN_LIMITATIONS.md`.
4. Open issues for anything deferred, with the evidence attached.
