# Contributing to AstraOS

Thank you for considering a contribution. AstraOS is an early-stage distribution, so
the most valuable contributions right now are the unglamorous ones: testing on real
hardware, fixing packaging errors, and improving the documentation.

## Before you start

Read, in this order:

1. `README.md` — what AstraOS is and its current status.
2. `docs/ARCHITECTURE.md` — how the pieces fit together.
3. `docs/KNOWN_LIMITATIONS.md` — what is already known to be broken. Please do not
   report these as new defects.
4. `docs/BUILDING.md` — how to build and test a change.

## Non-negotiable rules

These exist because getting them wrong hurts users, not because of style:

1. **Never commit a secret.** No keys, tokens, passwords or credentials. CI and the
   test suite scan for them, but do not rely on that.
2. **Never add a destructive disk operation to a script.** Partitioning, formatting and
   wiping belong to the installer, run by the user, against a disk they chose. If a
   change needs to touch a disk, it needs a design discussion first.
3. **Never weaken an installer safety property.** The target disk is never assumed, and
   erasing is never the default. `tests/static/test_repository.py` asserts this, and so
   does the build.
4. **Never disable package signature verification.** Not to make an install work, not
   temporarily.
5. **Never invent a build result.** If you cannot build or boot something, say so. A
   truthful "untested" is worth more than a confident "works".
6. **Never add a proprietary asset or another project's logo.** All artwork must be
   original and licensed compatibly.
7. **Keep the desktop responsive.** Do not add transparency, blur or animation to panel
   and window chrome. The expensive effects belong on the boot splash and the greeter.
8. **Do not fork an upstream component for branding.** Use the documented configuration
   mechanisms. A bespoke version of Xfce, LightDM or Calamares is out of scope.

## Making a change

```bash
git checkout -b fix/short-description

# make your change

make check                  # the static suite must pass
make lint                   # shell syntax and, if installed, shellcheck
```

If your change affects the package selection:

```bash
python3 scripts/verify-package-availability.py
```

That verifies every configured package exists in the pinned Debian release. It has
already caught invented package names in this project — `kpmcore`, `policykit-1`,
`xfce4-bscreenshooter-plugin` and `apt-xapian-index` were all wrong when first written.

If your change affects branding:

```bash
python3 branding/tools/render_assets.py
```

and include the regenerated assets.

If your change affects a shell script, check it with `shellcheck` as well as `bash -n`.
`syntax is valid` and `is correct` are different claims.

## What a good pull request contains

- **One change.** A packaging fix and a desktop tweak are two pull requests.
- **Why, not just what.** The description should explain the problem being solved.
- **Evidence.** The output of `make check`, and of any build or boot test you ran. If
  you did not run a test, say so rather than implying you did.
- **Updated documentation** when behaviour changes. Documentation that describes the
  previous behaviour is worse than no documentation.
- **A regression test** where practical, in `tests/static/`. If a defect was fixed,
  there should be something preventing it from returning.

## Commit messages

Write a short imperative summary, then explain why if it is not obvious:

```
Preselect no partition scheme in partition.conf

The installer previously defaulted to erasing the selected disk, which meant a
mis-click could destroy a user's data. The default is now "none", so the user has
to make an explicit choice.
```

## Areas that need help

| Area | What is needed |
|---|---|
| Virtual machine testing | Boot the ISO in VirtualBox, run the acceptance procedure in `docs/INSTALLATION_VIRTUALBOX.md`, report what happened |
| Physical hardware | Wi-Fi, graphics, audio and suspend results on real machines |
| Firmware coverage | Which Wi-Fi chipsets actually work, and which need firmware that is missing |
| Accessibility | Screen reader, magnification and high-contrast verification |
| Translations | The installer and the AstraOS utilities are English-only |
| Documentation | Anything in `docs/` that is wrong, unclear or missing |

## Licence of contributions

By contributing you agree that your contribution is licensed under the GNU General
Public License version 3 or later, the same licence as the project. See `LICENSE`.

## Code of conduct

Be straightforward and be kind. Disagree about the technical substance, not about the
person. Assume the other person has a reason for the position they hold, and ask what it
is before arguing against it.
