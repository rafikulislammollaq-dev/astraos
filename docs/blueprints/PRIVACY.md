# Privacy and security by default

Blueprint, October 2026. Status: **proposed.** Nothing here is implemented, and
no built image offers anything like it (the firewall policy that does exist is
documented in [`../SECURITY.md`](../SECURITY.md)). The roadmap stage is
Stage 7.

## The promise

Programs ask permission like they do on a phone. Nothing is collected and
nothing is sent unless the person opts in. The builds can be checked by
anyone.

## How it works

- **Per-application permissions.** Flatpak applications already run under
  portals; the Permissions panel shows what each application asked for —
  files, camera, microphone, network — in plain words, and lets it be changed
  or revoked after install. Native programs come under Guard profiles
  (Stage 3): observe / prepare / modify / privileged, with approvals that
  name the target.
- **No telemetry by default.** The system's own network use is a short,
  written list: time synchronization and security updates. The assistant is
  opt-in; the first-boot answer never leaves the machine; anything that might
  ever be shared (like Doctor reports, Stage 7) is consent-based with the
  exact payload previewed. The list is checked: a CI scan of the built image
  for known telemetry endpoints fails on a new one.
- **Verifiable builds, in stages.** An SBOM is generated at build time
  (packages, versions, licenses); release checksums are signed; the APT
  repository (Stage 1) ships signed metadata; the Secure Boot attempt
  (Stage 1) is labeled an attempt until a machine proves otherwise. Full ISO
  reproducibility is a direction, not a claim: Debian's own packages carry
  reproducibility work, and this project will publish exactly how far its
  image gets — including what resists.

## Honest boundaries

- Sandboxing reduces reach; it does not make a hostile program harmless. The
  kernel remains the kernel, and the limitations document says so.
- "No telemetry" means no collection and no sending by default — not that
  programs a person installs are invisible; per-application permissions and
  the firewall decision (Stage 1) are how that stays visible and
  controllable.
- Reproducible builds are a hard, unfinished problem across the industry; the
  commitment is to publishing measurements, not to a claim.

## How this gets proven

- A CI scan of the built image against an egress allowlist; a new endpoint
  fails the build unless the list is deliberately changed with a reason.
- A permission test: an application without camera permission cannot open the
  camera in a VM (portal refusal), and the Permissions panel shows and
  revokes the grant.
- An SBOM presence test, and a signature verification test once signing
  exists.
