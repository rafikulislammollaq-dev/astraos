# What the computer connects to

Blueprint, October 2026. Status: **proposed.** Nothing here is implemented, and no built
image offers anything like it. What exists today is `astraos-winbridge` (the Windows
bridge), the Stage 1 phone page (a six-digit pairing code, one served page, revoke) and
eight `SKILL.md` capability files inside `astraos-ai`; none of those is a connector in the
sense below. The roadmap stage is 7, with slices in Stage 5.

## The promise

The computer talks to the things a person already uses — their phone, their other
computers, their printer, their mail, their calendar, their contacts, their files, their
camera, their television — without an account with us, without a vendor in the middle, and
without any of them reaching further than the person allowed. A connector is granted in
one place, revoked in one place, and every use of it is written down.

## How it works

- **A connector is a declared surface, not a plugin.** It states its name, the fields it
  reads, the fields it changes, where the data goes, its author, its version and its
  signature. The shape is the Stage 7 skill manifest plus a transport, so there is one
  vocabulary for "a thing this computer can do" whether the thing is on the machine or
  across a network.

- **Three kinds, in order of preference.** A connector to the printer on the LAN, to the
  phone over Wi-Fi, or to another AstraOS machine over the mesh is preferred, because no
  third party is involved at all. A connector speaking a standard protocol to a server the
  person chose — IMAP and SMTP for mail, CalDAV and CardDAV for calendar and contacts,
  WebDAV or SFTP for files — is second, and its credential lives in the keyring rather
  than passing through anything of ours. A connector to a vendor's own API is the last
  resort, used only where the provider requires an account.

- **Where a vendor is unavoidable, the grant is spelled out.** The scopes are shown in
  plain words before anything is granted — "read your mail", "send mail on your behalf" —
  and the broker enforces the declared surface rather than trusting the connector to
  police itself. A connection that needs an account says so, and a fresh install has
  none.

- **The Model Context Protocol is the call format, not the permission model.** The Stage 7
  gateway exposes this operating system's own surface — packages, services, logs, network,
  metrics, files through portals — as tools over MCP, so assistants and other programs can
  use them in a shape everyone already speaks. Permissions stay this project's own model,
  deliberately independent of any protocol's behaviour, so a change in a protocol cannot
  widen what is allowed.

- **One screen enumerates everything.** Each connector shows what it can read, what it can
  write, when it last ran and what it did, with one switch that removes it. Removing a
  connector revokes the credential, not merely the menu entry.

- **Short-lived by default.** A connector receives the fields its task needs, for that
  task, through a token the broker issued — not a general handle on the account that
  anything downstream can pick up and reuse.

## Honest boundaries

- **A connector to somebody else's service means somebody else has the data.** The grant
  screen says so in plain words instead of implying otherwise; where an account exists,
  the provider can read what it holds, and no amount of local software changes that.

- **A credential in the keyring is protected by the login key**, not by a hardware key on
  machines that have no TPM. A stolen unlocked session is a stolen session; that is part
  of why tokens are scoped and short-lived wherever the provider allows it.

- **There is no connector store at first.** Connectors arrive as reviewed manifests in the
  image or in a signed pack, not as a marketplace anyone may publish to.

- **Some things have no honest connector.** DRM video services, closed messaging networks
  with no API, and banking stay in the browser or in the vendor's own software. This
  document says so rather than promising a bridge that cannot be built.

- **Two-way sync with a vendor's calendar invites conflicts the vendor's model cannot
  merge.** The first slice is reading plus explicit writes, not a claim of seamless
  merging.

## How this gets proven

- A fresh image has zero connectors and every essential task still works; the boot
  self-test asserts the zero.
- Revoking a connector revokes its credential: a call that succeeded before the revoke
  must be refused after it, and the refusal must be recorded — not merely disappear from a
  menu.
- A connector to a service on the local network, exercised end to end: mail against a
  local IMAP server and calendar against a local CalDAV server, each in a container, with
  the broker refusing a scope that was never granted.
- An injection fixture: a document that orders the assistant to mail a file must be denied
  by the broker, and the denial must appear in the log — not be narrated as a success.
- A per-connector audit check: the log names the connector, the fields read and the
  destination, on every use.
