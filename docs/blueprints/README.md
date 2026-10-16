# Blueprints

These documents describe how the promised experiences are meant to be built. They
are blueprints, not state: nothing here is implemented, and the only evidence that
anything works is a run, a test or an artifact. The schedule lives in
[`../ROADMAP.md`](../ROADMAP.md); what exists today is in
[`../../README.md`](../../README.md). The visual identity is a separate document,
[`../DESIGN.md`](../DESIGN.md).

They exist because the direction deserves more than slogans, and because the
roadmap's design principle deserves concrete answers:

> Nobody should ever have to leave because something was too hard, and nobody
> should ever have to stay because they're locked in.

| Blueprint | Covers | Roadmap |
|---|---|---|
| [FIRST_BOOT.md](FIRST_BOOT.md) | the one question at first login: "What are you coming from?" | Stage 5 |
| [PROFILES.md](PROFILES.md) | simple, power, security, gaming and family setups — presets, not parallel systems | Stage 5 |
| [APP_STORE.md](APP_STORE.md) | one store and launcher for Linux, Windows, Flatpak and web apps | Stage 5 |
| [UNBREAKABLE.md](UNBREAKABLE.md) | updates that roll back, snapshots, rescue from any state | Stage 3 |
| [PHONE_LINK.md](PHONE_LINK.md) | the phone and the computer as one device | Stage 5 |
| [OS_AI.md](OS_AI.md) | the assistant as a system service: diagnose, find, act — audited | Stages 3–4 |
| [PRIVACY.md](PRIVACY.md) | per-app permissions, no telemetry, verifiable builds | Stage 7 |
| [REACH.md](REACH.md) | old laptops to new rigs; what "runs on everything" honestly covers | Stages 1–2 |
| [CREATORS.md](CREATORS.md) | audio, video, design and development packs that work out of the box | Stage 5 |
| [COMMUNITY.md](COMMUNITY.md) | docs, languages, forums, a roadmap people can help steer | every stage |

Every blueprint has the same four sections: *the promise* (what a person gets),
*how it works* (the actual mechanism), *honest boundaries* (what is refused,
deferred or labeled), and *how this gets proven* (what CI or a virtual machine
will assert when the work starts).
