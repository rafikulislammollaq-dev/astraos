# PROJECT: ASTRA OS

## A Complete, Installable, Linux-Based Desktop Operating System

### YOUR ROLE

Act as a senior operating-system engineer, Linux distribution maintainer, kernel engineer, systems programmer, desktop environment developer, security engineer, release engineer, and quality assurance engineer.

Your assignment is to design, implement, build, and validate a real operating system named **AstraOS**.

This is an engineering project, not a conceptual exercise.

I do not want a website pretending to be an operating system. I do not want a simulated desktop running inside a browser. I do not want a simple Linux theme that we call a new OS.

I want an actual, bootable, installable Linux distribution that can eventually run on physical computers.

The final product must be capable of being delivered as a bootable ISO image, started in VirtualBox, installed into a virtual disk, booted independently, and eventually installed on compatible physical hardware.

You must work directly with the available development environment, inspect the repository, create the necessary files, execute applicable commands, test the implementation, and fix problems that can reasonably be fixed in the available environment.

**Do not stop after producing a plan. Implement the project.**

If a particular operation cannot be completed because the environment lacks the necessary permissions, resources, tools, or hardware, implement everything possible around that limitation and explicitly identify the remaining requirement.

Never pretend that a build, test, installation, or hardware validation succeeded when it did not.

---

# 1. PRODUCT VISION

Build AstraOS as an independent Linux distribution with its own identity, branding, desktop configuration, applications, system configuration, installation experience, documentation, and release process.

AstraOS will use the Linux kernel rather than attempting to create an entirely new kernel during the first release.

However, it must be a genuine operating system distribution with an independent build configuration and a reproducible installation process.

It should eventually become a platform on which we can develop our own system components, desktop applications, AI assistant, security tools, and developer utilities.

The first release must prioritize a reliable, usable, installable operating system.

Fancy features must never take priority over boot reliability, filesystem integrity, security, hardware compatibility, or a working installer.

## Product name

Distribution name: AstraOS

Short description: An independent, lightweight Linux desktop operating system.

Initial release identifier: AstraOS 0.1.0 Alpha.

Architecture: x86_64 / AMD64.

Primary target: Modern Intel and AMD computers.

Virtualization target: Oracle VirtualBox.

Initial desktop: XFCE, extensively configured and branded for AstraOS.

Init system: systemd.

Kernel: A supported Linux kernel supplied by the selected Linux distribution's package repositories.

Base distribution: Current supported Debian Stable release at build time.

Display server: Prefer X11 initially if required for straightforward compatibility with XFCE, while keeping the design ready for a future Wayland transition.

Package format: Debian packages.

Package manager: APT and dpkg.

Bootloader: GRUB, configured for the supported boot modes.

Live image builder: Debian live-build or another officially documented, reproducible image-building mechanism if live-build proves unsuitable.

Graphical installer: Calamares if its modules and Debian configuration support the installation design. Otherwise, use a supported upstream installer rather than inventing a dangerous custom partitioning system.

Default shell: Bash.

Main programming languages: Bash, Python, and C/C++ or Rust where a genuine systems component justifies them.

The desktop must work without a cloud connection.

AI features, if later introduced, must be optional and must not be required for system startup, login, networking, package management, or recovery.

---

# 2. ENGINEERING PRINCIPLES

Follow these principles throughout the project.

## 2.1 Build a real distribution

Use the Linux kernel, system libraries, bootloader, initialization system, graphical stack, and applications required for a complete operating system.

Create an independently maintained distribution configuration, package selection, theme, installer configuration, and build pipeline.

The finished system must have its own OS identity while preserving the provenance and licensing obligations of its upstream components.

Do not represent AstraOS as a completely independent kernel or a from-scratch operating system kernel.

Do not hide the fact that it is Linux-based.

## 2.2 Keep the system lightweight

The operating system must be usable on modest hardware.

Avoid unnecessary background services, duplicate applications, excessive animations, always-running AI processes, and unnecessary graphical frameworks.

Choose applications according to their usefulness, maintenance status, dependencies, resource consumption, and security.

Do not optimize by randomly disabling services that the operating system needs.

## 2.3 Prefer maintained upstream components

Use supported components from official repositories whenever possible.

Do not download arbitrary binaries from untrusted websites.

Do not install unverified kernel modules.

Do not use undocumented bootloader modifications.

Do not replace essential system components with homemade substitutes simply for branding.

## 2.4 Keep the project reproducible

Every important system configuration must be stored in version control.

The build process must be documented and repeatable.

A successful build must produce a manifest describing the distribution version, architecture, package selection, build environment, and other available provenance information.

Where exact byte-for-byte reproducibility is practical, aim for it. Otherwise, make the dependency sources and build configuration reproducible, and record the reasons exact binary reproducibility cannot be guaranteed.

## 2.5 Separate development from installation

Building an ISO must never install AstraOS on the host computer.

Testing the installer must never automatically erase the host computer.

All destructive disk operations must occur only inside the intended virtual machine or after explicit human confirmation on physical hardware.

---

# 3. FIRST TASK: INSPECT THE AVAILABLE ENVIRONMENT

Before implementing anything, inspect the development environment.

Determine:

1. Operating system and version.
2. Available CPU architecture.
3. Available RAM.
4. Available disk space.
5. Available shell and programming tools.
6. Whether a Linux build environment is available.
7. Whether Docker, Podman, virtualization, QEMU, or VirtualBox is available.
8. Whether network access and official package repositories are accessible.
9. Whether Git is available.
10. Whether the current environment can actually build a Debian Live image.

Check installed versions rather than assuming tools are available.

If the development environment is Windows, do not blindly execute Linux-only commands in PowerShell or CMD.

Choose a suitable build environment.

Preferred order:

1. An available, properly configured Linux environment.
2. An appropriate cloud Linux machine.
3. A reproducible Linux-based CI build.
4. Another documented environment that can successfully perform the required image-building operations.

Because local development hardware may be limited, design the project so that the expensive ISO-building process can run in cloud CI.

Do not require local AI model training, GPU computation, or other unnecessary resource-intensive work.

If GitHub Actions or another CI system is selected, create a working automated build workflow. Do not assume the workflow works merely because its YAML file exists.

If an external account, repository, or authentication token is required, document the requirement. Never invent credentials, request that users commit secrets, or claim to have created external resources without actually doing so.

After inspecting the environment, create the project repository structure and begin implementation immediately.

Do not spend the entire session researching or describing what you intend to do.

---

# 4. REQUIRED PROJECT STRUCTURE

Organize the repository approximately as follows:

astraos/
│
├── README.md
├── LICENSE
├── SECURITY.md
├── CONTRIBUTING.md
├── CHANGELOG.md
├── VERSION
├── Makefile
├── .gitignore
│
├── config/
│   ├── distribution.env
│   ├── branding.env
│   ├── packages/
│   ├── live-build/
│   └── installer/
│
├── branding/
│   ├── logos/
│   ├── icons/
│   ├── wallpapers/
│   ├── plymouth/
│   ├── grub/
│   ├── lightdm/
│   └── desktop/
│
├── desktop/
│   ├── xfce/
│   ├── themes/
│   ├── wallpapers/
│   ├── launchers/
│   ├── autostart/
│   └── configuration/
│
├── packages/
│   ├── astraos-base/
│   ├── astraos-branding/
│   ├── astraos-desktop/
│   └── astraos-system-tools/
│
├── system/
│   ├── services/
│   ├── security/
│   ├── networking/
│   ├── defaults/
│   └── sysctl/
│
├── installer/
│   ├── calamares/
│   ├── configuration/
│   ├── branding/
│   └── tests/
│
├── scripts/
│   ├── bootstrap-build-environment.sh
│   ├── validate-environment.sh
│   ├── configure-live-build.sh
│   ├── build-iso.sh
│   ├── validate-iso.sh
│   ├── generate-checksums.sh
│   ├── generate-manifest.sh
│   ├── package-release.sh
│   └── cleanup-build.sh
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── security/
│   ├── boot/
│   └── acceptance/
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── BUILDING.md
│   ├── INSTALLATION_VIRTUALBOX.md
│   ├── INSTALLATION_PHYSICAL_PC.md
│   ├── RECOVERY.md
│   ├── SECURITY.md
│   ├── TROUBLESHOOTING.md
│   ├── RELEASE_PROCESS.md
│   └── KNOWN_LIMITATIONS.md
│
├── .github/
│   └── workflows/
│       ├── validate.yml
│       └── build-iso.yml
│
├── build/
│
└── dist/

You may modify this structure if the selected tooling imposes a better organization.

However, keep source configurations, custom packages, automated tests, generated build artifacts, and release outputs clearly separated.

Do not commit large generated ISO files into Git by default.

Configure Git to ignore temporary build directories, caches, logs containing sensitive information, and generated ISO artifacts where appropriate.

Never store API keys, passwords, access tokens, or private signing keys in the repository.

---

# 5. BASE OPERATING SYSTEM AND BUILD ARCHITECTURE

Use a currently supported Debian Stable release.

Verify the actual stable release, architecture support, required package availability, and official documentation at implementation time.

Do not hardcode an obsolete release merely because an old tutorial uses it.

Pin the selected major release for each release branch rather than allowing a build to silently change from one major distribution version to another.

Document how maintainers intentionally update the base release.

## 5.1 Base system

Include the necessary components for a proper desktop Linux installation:

* Linux kernel.
* initramfs generation and maintenance.
* systemd.
* GRUB bootloader.
* UEFI boot support.
* Legacy BIOS support where practical.
* Filesystem utilities.
* Essential shell utilities.
* Core system libraries.
* APT and dpkg.
* NetworkManager.
* User and group management.
* Logging and diagnostics.
* Standard Linux security mechanisms.
* CA certificates.
* Supported hardware firmware where legally distributable.
* Time synchronization.
* Keyboard and locale configuration.
* Filesystem checking and recovery tools.
* Normal system startup and shutdown handling.

Do not add every package available in Debian.

Develop an explicit and reviewed package list.

## 5.2 Graphics

Use a stable graphical stack supported by the chosen Debian release.

Include the required components for:

* Display initialization.
* Window management.
* Rendering.
* Input devices.
* Multiple displays.
* Screen resolution changes.
* Audio output.
* Basic power management.
* Lock screen.
* Session startup.
* Desktop notifications.

Avoid depending on proprietary GPU software for basic desktop operation.

Use appropriate open-source drivers and supported firmware packages.

Do not promise compatibility with every GPU.

Record known hardware limitations.

## 5.3 Boot sequence

The intended boot sequence is:

Firmware
↓
GRUB
↓
Linux kernel and initramfs
↓
System initialization
↓
Hardware and system services
↓
Display manager
↓
AstraOS desktop session

The live image must have its own correctly configured boot sequence.

The installed system must have a functioning bootloader and a correctly generated initramfs.

Do not treat the ability to display a boot logo as evidence that the kernel or operating system is working.

Test the entire boot chain.

---

# 6. THE LIVE ISO

Create an actual bootable AstraOS live image.

It must be possible to attach the ISO to a VirtualBox virtual optical drive and boot it.

The live image must provide a working graphical session without requiring installation first.

## 6.1 Live session requirements

On startup, the user should be able to:

1. Boot AstraOS.
2. Select a supported boot option.
3. Enter the graphical desktop.
4. Open a terminal.
5. Open the file manager.
6. Configure networking.
7. Browse the web when networking is available.
8. Change desktop settings.
9. Inspect basic system information.
10. Launch the installer.

The live session must clearly identify itself as a live environment.

Do not imply that changes made in a nonpersistent live session will necessarily survive reboot.

## 6.2 ISO requirements

Generate an ISO image suitable for x86_64 hardware.

Use a documented hybrid boot-image arrangement supported by the selected image builder.

Include UEFI boot support.

Include legacy BIOS boot support if the selected tooling supports it reliably.

Do not claim Secure Boot support unless the complete boot path has been verified.

Test that the resulting ISO is structurally valid.

Verify:

* The image file exists.
* The image has a plausible size.
* The image can be inspected using suitable ISO utilities.
* The bootloader files exist.
* The live filesystem is present.
* The required kernel and initramfs exist.
* The boot menu configuration is valid.
* The configured boot modes are present.
* The checksum can be generated and verified.

Where supported, use tools such as xorriso, file, unsquashfs, and other appropriate image-inspection utilities.

Do not merely rename a Debian ISO and call it AstraOS.

The image must be produced from the AstraOS build configuration.

---

# 7. THE ASTRAOS DESKTOP

Create a distinct, professional desktop experience.

Use XFCE as the initial desktop foundation because the first release should emphasize responsiveness, compatibility, and low resource usage.

Do not attempt to develop a complete graphical environment from scratch for the first release.

However, the desktop should not look like an untouched Debian installation.

## 7.1 Visual identity

Establish a consistent visual system.

Initial design direction:

* Modern.
* Clean.
* Professional.
* Technically sophisticated.
* Minimal visual clutter.
* Consistent spacing.
* Readable typography.
* High contrast for important controls.
* Suitable for both laptops and desktop monitors.

Use a cohesive palette of dark graphite, cool blue, and restrained cyan accents. Provide a usable light theme as well.

Avoid excessive transparency and blur effects that may degrade performance on low-end computers.

Do not imitate Windows, macOS, or another operating system's trademarks, logos, or proprietary assets.

Create original branding.

## 7.2 Desktop components

Configure:

* Desktop wallpaper.
* Desktop icons where useful.
* Panel or taskbar.
* Application launcher.
* Window controls.
* Notification area.
* Clock and calendar.
* Network indicator.
* Audio controls.
* Battery indicator on supported hardware.
* Application menu.
* Window switching.
* Keyboard shortcuts.
* Screen locking.
* Session logout and shutdown.
* Display settings.
* Keyboard settings.
* Theme settings.

Create a recognizable AstraOS desktop layout.

Keep the interface configurable rather than hardcoding all settings into an unmodifiable shell.

## 7.3 Login screen

Configure a branded LightDM login screen if this is compatible with the chosen desktop configuration.

It should provide:

* AstraOS branding.
* User selection.
* Password authentication.
* Session selection where appropriate.
* A graceful response to incorrect passwords.
* An orderly shutdown and restart path.

Do not automatically log in as root.

Do not ship with a shared administrator password.

## 7.4 Boot splash

Create a simple branded boot animation or splash screen using supported tools.

The splash must not hide critical boot failures indefinitely.

Users must have a documented way to inspect boot messages when troubleshooting.

If the splash system fails, normal boot and recovery must remain possible.

## 7.5 Accessibility

Provide:

* Readable default font sizes.
* Keyboard navigation.
* Screen magnification or a documented supported alternative.
* High-contrast configuration.
* Reduced-animation options where practical.
* Keyboard-based access to essential settings.

---

# 8. DEFAULT APPLICATIONS

Provide a practical set of desktop applications without unnecessary duplication.

Potential categories include:

### Internet

A maintained browser available from the selected distribution's repositories.

### File management

A capable graphical file manager with mounted-volume access.

### Terminal

A terminal emulator with normal shell functionality.

### Text editing

A lightweight graphical text editor.

### System administration

Tools for inspecting CPU, RAM, disks, processes, and running services.

### Networking

Network management tools integrated with NetworkManager.

### Audio

Supported audio services and volume controls.

### Archive management

Tools for common archive formats.

### Screenshots

A screenshot utility.

### PDF viewing

A maintained document viewer.

### Software installation

A graphical software-management solution if a supported option is available.

Do not create fake application launchers.

Do not include applications merely to make the menu appear full.

Every default application must be genuinely installable, launchable, and useful.

Use maintained upstream programs rather than writing replacements for established applications without a compelling technical reason.

---

# 9. ASTRAOS IDENTITY AND BRANDING

Create a coherent distribution identity.

Establish:

* Distribution name: AstraOS.
* Version: 0.1.0 Alpha.
* An original SVG logo.
* A simplified monochrome logo.
* A desktop wallpaper.
* A boot splash asset.
* Login-screen branding.
* Desktop theme settings.
* A consistent application icon style.
* Installer branding.
* System-information branding.

Prefer SVG assets and appropriately licensed fonts.

If custom fonts are needed, use fonts whose licenses permit redistribution.

Maintain attribution and license notices for third-party assets.

Configure system identity carefully.

Where appropriate, configure:

* `/etc/os-release`.
* Distribution release information.
* Hostname defaults.
* Distribution-specific desktop settings.
* Installer display name.
* Welcome screen text.
* Support and documentation links.
* Release-version reporting.

Only populate fields according to their defined meaning.

For example, do not label a Debian-based distribution as a different kernel merely because its branding has changed.

Do not overwrite core Debian package ownership or package-management metadata in a way that breaks compatibility.

AstraOS must retain the ability to receive updates from its selected upstream repositories.

---

# 10. GRAPHICAL INSTALLER

The installer is a critical deliverable.

AstraOS must not remain a live-only operating system.

It must provide a supported method of installing the actual operating system onto a target disk.

## 10.1 Installer selection

First verify whether Calamares can be used successfully with the chosen Debian Stable packages and the intended live-image configuration.

Use the maintained upstream Calamares framework where practical.

Inspect its available configuration modules and their documented requirements.

Do not assume that copying a configuration file from another distribution creates a working installer.

If a required module is unavailable or incompatible, resolve that incompatibility or select a supported upstream installer.

Do not build a homemade partitioning program as a shortcut.

## 10.2 Installer interface

The installer should provide a professional, branded experience.

Include the relevant supported options for:

* Welcome and introduction.
* Language selection.
* Keyboard layout.
* Time zone.
* Target disk identification.
* Installation type.
* Partitioning.
* Filesystem selection where supported.
* User account creation.
* Hostname.
* Installation summary.
* Progress reporting.
* Error reporting.
* Installation completion.
* Reboot into the installed system.

Do not show options that are not actually implemented.

## 10.3 Disk safety requirements

Disk management is a high-risk part of operating-system installation.

The installer must distinguish the intended target drive from unrelated drives.

Never silently format a disk.

Never begin installation before the user confirms the final disk and partitioning plan.

Provide a clearly identified custom-partitioning path if the selected installer supports it reliably.

Where possible, support both:

* Installation using unallocated or explicitly selected disk space.
* Erasing a specifically selected target disk after a clear warning and explicit confirmation.

The default selection must not automatically authorize erasure.

Do not assume that `/dev/sda` is the correct disk.

Do not assume a virtual disk is the only disk connected to a computer.

Do not run destructive partitioning commands while building the ISO.

Do not invoke the installer against the development host's drives during automated tests.

Automated installer tests must use dedicated disposable virtual disks.

Ensure the installation process preserves the host operating system when the user has not explicitly selected a destructive installation operation.

The final confirmation screen must summarize what will happen.

## 10.4 User creation

Create a normal, non-root account.

Configure administrator privileges through an appropriate sudo policy.

Use secure authentication.

Do not ship fixed credentials.

Do not enable passwordless unrestricted root access.

Document account-recovery options where appropriate.

## 10.5 Installation completeness

After installation, the system must be able to:

* Boot without the live ISO.
* Load the installed kernel and initramfs.
* Mount its filesystems.
* Start essential services.
* Display the login screen.
* Authenticate a user.
* Open the desktop.
* Access the installed package database.
* Configure networking.
* Shut down and reboot correctly.

Check that the installed system is not accidentally dependent on files residing only in the live filesystem.

The installed system must have its own valid bootloader configuration.

The installation must not finish successfully if essential installation steps have failed.

If the installer does not finish, preserve meaningful diagnostic information.

---

# 11. STORAGE AND FILESYSTEM DESIGN

Use a straightforward, well-supported filesystem layout.

For the first release, prefer ext4 for the root filesystem.

Use a supported UEFI EFI System Partition when installing in UEFI mode.

Keep the default partition scheme simple.

Support a reasonable root partition layout and swap configuration consistent with the chosen installer.

Do not require complicated storage configurations in the first release.

Where the installer supports encryption reliably, consider an optional encrypted installation.

Never claim disk encryption is enabled unless it was actually configured.

Never implement an undocumented encryption scheme.

Do not make encryption mandatory for systems where the installer cannot handle it correctly.

For automated tests, create separate disposable virtual disks.

Add checks to scripts that prevent accidental execution against the physical host's disks.

Do not store persistent user data in a temporary live filesystem.

Do not hardcode device names.

Document storage requirements and the differences between a live session and an installed system.

---

# 12. NETWORKING AND HARDWARE SUPPORT

The system should use standard Linux hardware support wherever possible.

Prioritize compatibility with:

* Standard SATA storage.
* NVMe storage.
* Common USB devices.
* USB keyboards and mice.
* VirtualBox virtual hardware.
* Standard Ethernet interfaces.
* Common Wi-Fi chipsets supported by the selected kernel and firmware.
* Intel integrated graphics.
* AMD graphics with supported drivers.
* Common audio devices.
* Common display resolutions.
* Laptop battery reporting when supported.

Use NetworkManager for desktop networking.

Configure sane DNS behavior using the selected distribution's supported networking components.

Do not hardcode Wi-Fi credentials.

Do not collect network passwords.

Do not disable certificate validation to resolve connectivity problems.

Do not promise support for every Wi-Fi chipset or graphics card.

If firmware redistribution has licensing implications, handle those through the distribution's documented package and licensing configuration.

Do not download a collection of arbitrary drivers simply to claim broader compatibility.

Produce a hardware compatibility document identifying tested and untested configurations.

---

# 13. SECURITY BASELINE

Treat AstraOS as an operating system that will eventually connect to the internet and store personal information.

Security is a core requirement.

## 13.1 Accounts and permissions

Use normal Linux users and groups.

Require privilege escalation for administrative operations.

Use least-privilege permissions for custom scripts and services.

Do not run the desktop or ordinary applications as root.

Do not use globally writable system directories for executables or privileged configuration.

## 13.2 Services

Enable only services that are genuinely needed.

Audit the enabled service list.

Explain any unusual service.

Do not introduce remote administration daemons unless there is a clear requirement.

If SSH is included, leave remote access configured conservatively and document how to enable it.

## 13.3 Updates

Use authenticated package repositories.

Preserve APT signature verification.

Support routine operating-system security updates.

Document how users can update installed software.

Do not disable automatic or manual security-update capabilities without a justified reason.

## 13.4 Firewall

Provide a documented host-firewall configuration.

Where a firewall tool is included, use the distro-supported implementation.

Avoid rules that unnecessarily break local networking or DHCP.

Document the default inbound policy and how the user can inspect it.

## 13.5 Secrets

Do not commit secrets.

Do not embed API tokens or private signing keys in the ISO.

Do not write user passwords into logs.

Avoid recording sensitive environment variables in CI logs.

## 13.6 AI isolation

If AI capabilities are developed in later releases, they must operate under normal user permissions unless a particular privileged action has been explicitly authorized.

The AI must not receive unrestricted root access by default.

For actions involving deletion, partitioning, software installation, account modification, security settings, or data transmission, require appropriate validation and human confirmation.

Do not make an online AI service part of the trusted boot path.

---

# 14. SYSTEM RECOVERY AND DIAGNOSTICS

A real operating system needs a troubleshooting strategy.

Provide clear mechanisms for inspecting:

* System logs.
* Kernel messages.
* Startup failures.
* Failed services.
* Disk space.
* Filesystem status.
* Memory pressure.
* Network connectivity.
* Installed kernel versions.
* Package-manager failures.

Use standard Linux diagnostics where possible.

Create a distribution-specific diagnostic command only if it adds meaningful value.

For example, an `astraos-info` command may report:

* AstraOS release.
* Kernel version.
* CPU architecture.
* Available memory.
* Root filesystem usage.
* Current desktop session.
* Active network interface status.
* Boot mode where detectable.

The command must not disclose passwords, authentication tokens, Wi-Fi credentials, or other secrets.

Create a recovery guide for:

* An unbootable desktop.
* A failed graphical login.
* A broken package transaction.
* An incomplete kernel update.
* A bootloader configuration problem.
* Insufficient disk space.
* A network problem.

Do not claim that every failure can be recovered automatically.

---

# 15. OPTIONAL ASTRAOS SYSTEM UTILITIES

Create small, maintainable distribution-specific utilities when they solve real problems.

Potential utilities include:

1. AstraOS Welcome.
2. AstraOS System Information.
3. AstraOS Update Guide.
4. AstraOS Help.
5. AstraOS Recovery Guide.
6. AstraOS Release Information.

The Welcome application may provide:

* Distribution version.
* A short introduction.
* Links to documentation.
* System requirements.
* An installer launcher in the live session.
* Initial setup guidance for an installed system.

It should not perform destructive actions automatically.

Do not create a custom system settings application that merely duplicates existing functionality without adding value.

Every custom application must have a clear purpose.

---

# 16. BUILD SYSTEM

Create a reliable, automated build process.

The main build command should be:

```
./scripts/build-iso.sh
```

Also provide appropriate Makefile shortcuts.

For example:

```
make check
make build
make validate
make checksums
make clean
```

Document the exact environment in which the commands are supported.

## 16.1 Build process

The build process should:

1. Validate the host environment.
2. Confirm the architecture.
3. Check required dependencies.
4. Validate the distribution configuration.
5. Validate the package list.
6. Verify access to the required package repositories.
7. Prepare the build environment.
8. Configure Debian Live.
9. Apply AstraOS branding.
10. Install the selected package set into the live filesystem.
11. Apply supported system configurations.
12. Configure the graphical session.
13. Configure the installer.
14. Generate the live image.
15. Generate the bootable ISO.
16. Inspect the resulting image.
17. Generate a package manifest.
18. Generate a SHA-256 checksum.
19. Produce a build report.

Use official tool documentation for the selected Debian Live version.

Do not delete caches or existing artifacts indiscriminately just because the build process might be simpler.

Implement an explicit cleanup operation.

## 16.2 Build failure handling

The build must stop when a critical operation fails.

Do not continue after a failed dependency installation and then report success.

Use sensible shell error handling.

Use quoted variables.

Avoid unsafe string interpolation.

Write useful error messages.

Save build logs in a documented location.

Never leak credentials into the logs.

Handle interrupted builds predictably.

Distinguish between a failed build, an incomplete build, and a successful build.

## 16.3 Dependency management

Install only necessary host-build dependencies.

Keep build dependencies separate from the software included in AstraOS.

Where appropriate, verify package availability before adding dependencies.

Do not rely on obsolete package names from old Debian releases.

Do not use `sudo` indiscriminately throughout every script.

Use elevated privileges only when required.

If the image builder requires privileged operations, isolate those operations in the build environment and document why they are needed.

## 16.4 Repeated builds

Running the build process more than once must not corrupt the repository.

Handle stale build output.

Keep build logs.

Prevent two simultaneous builds from unintentionally sharing mutable build directories.

Make clean and build operations behave predictably.

---

# 17. CLOUD BUILD AND CI/CD

Design the repository so ISO compilation can take place in a suitable Linux cloud environment rather than requiring a powerful local PC.

Implement a CI workflow that validates the project whenever relevant files change.

For ISO builds, use an appropriate manually triggered workflow or release workflow.

A pull request validation job should run inexpensive static checks rather than unexpectedly launching an expensive full OS build for every trivial change.

The image-building job should:

1. Check out the source.
2. Identify the target architecture.
3. Prepare a suitable Linux build environment.
4. Install required build dependencies.
5. Validate the configuration.
6. Build the ISO.
7. Check whether the ISO exists.
8. Validate the image.
9. Generate checksums.
10. Generate a package manifest.
11. Upload the completed artifact.
12. Preserve logs and validation reports.

If the CI platform does not support an operation required by Debian Live, do not silently skip it.

Investigate the correct supported runner or use a suitably configured build machine.

Do not create a fictional release URL.

Do not claim an artifact was uploaded when the workflow has not run successfully.

Document where the actual build artifact becomes available after CI completes.

Do not commit the generated ISO to the repository by default.

If release signing is implemented, use an appropriate signing mechanism and protect private keys. Do not invent signatures or embed release-signing secrets in the workflow source.

---

# 18. TESTING STRATEGY

The OS must have a real testing process.

Separate configuration validation, image validation, virtual machine tests, installation tests, and physical hardware tests.

Passing a shell syntax check is not evidence that the OS boots.

Passing a boot test is not evidence that the installer works.

Passing a virtual machine test is not evidence of universal physical hardware compatibility.

## 18.1 Static tests

Validate:

* Shell script syntax.
* Configuration syntax.
* Package-list structure.
* File permissions.
* Installer configuration.
* Desktop launcher files.
* Systemd unit files.
* Boot configuration.
* Repository structure.
* Required documentation.

Use appropriate tools when available, including ShellCheck and relevant configuration validators.

## 18.2 Build tests

Verify:

* The build process completes.
* The expected ISO is generated.
* The checksum matches the artifact.
* The image structure is valid.
* The expected package manifest exists.
* The installer configuration is present.
* Required branding assets are included.

## 18.3 Virtual machine tests

Use QEMU or VirtualBox where available.

If automated virtualization cannot be executed in the current environment, provide an exact manual acceptance procedure.

Test at least:

* UEFI boot where supported.
* Legacy BIOS boot where supported.
* Live desktop startup.
* Mouse and keyboard input.
* Screen resolution.
* Terminal launch.
* File manager launch.
* Network interface recognition.
* Browser launch.
* Restart and shutdown.
* Installer launch.

Do not mark a test as passed unless it actually ran and passed.

## 18.4 Installation tests

Create a separate disposable virtual disk.

Boot the ISO.

Launch the graphical installer.

Install AstraOS to the designated virtual disk.

Detach the ISO.

Boot from the installed virtual disk.

Confirm that the installed system works without the live image.

Test user authentication, networking, desktop startup, software installation, system updates, restart, and shutdown.

Where possible, test both UEFI and legacy BIOS installations.

Use a clean virtual machine for each installation scenario.

Never perform automated installation testing on the development computer's real system disk.

## 18.5 Regression testing

Every bug discovered during implementation should produce a regression test where practical.

Examples include:

* Missing package in the ISO.
* Broken application launcher.
* Invalid installer configuration.
* Missing bootloader file.
* Failure to generate an initramfs.
* Incorrect desktop permissions.
* Installer completion followed by an unbootable system.

The goal is to prevent a resolved problem from silently reappearing in later builds.

---

# 19. VIRTUALBOX ACCEPTANCE REQUIREMENTS

The first major milestone is to produce an ISO that a user can test in Oracle VirtualBox.

Provide an installation guide with exact settings and screenshots only if screenshots have actually been captured.

Do not fabricate screenshots.

Document a reasonable initial VM configuration:

* Operating system family: Linux.
* Architecture: 64-bit x86 Linux.
* CPUs: 2 virtual CPUs, subject to host capacity.
* RAM: 4 GB initially if the host has sufficient memory.
* Virtual disk: approximately 30 GB.
* Network: ordinary virtual NAT networking.
* Firmware: test UEFI and BIOS separately when supported.
* Optical drive: attach the AstraOS ISO.

These are starting values, not absolute requirements.

Explain how to adjust RAM and CPU allocation if the host is resource-constrained.

The user should be able to create a new VM without modifying the host operating system.

The acceptance procedure must include the following exact sequence:

1. Obtain the completed AstraOS ISO.
2. Verify its SHA-256 checksum.
3. Open VirtualBox.
4. Create a new Linux virtual machine.
5. Allocate a virtual disk.
6. Attach the AstraOS ISO.
7. Boot the VM.
8. Inspect the boot menu.
9. Enter the live desktop.
10. Test basic applications.
11. Launch the installer.
12. Install to the virtual disk.
13. Shut down the VM.
14. Remove the ISO from the virtual optical drive.
15. Start the VM from the virtual disk.
16. Complete first login.
17. Test networking and updates.
18. Shut down and boot again.
19. Record any failures and relevant logs.

Do not declare the installation complete until the installed virtual machine boots without depending on the live ISO.

---

# 20. PHYSICAL PC INSTALLATION

Physical installation is a later milestone.

Do not instruct the user to install AstraOS directly on their main computer before the VirtualBox installation has passed the acceptance tests.

Create a detailed `docs/INSTALLATION_PHYSICAL_PC.md`.

The guide must explain:

## Before installation

* Verify the downloaded ISO checksum.
* Verify that the target computer supports the selected architecture.
* Create a backup of important files.
* Identify the existing operating systems and storage devices.
* Confirm that sufficient storage is available.
* Investigate Wi-Fi and graphics compatibility where necessary.
* Understand UEFI versus legacy BIOS boot mode.
* Determine whether the machine uses disk encryption or other settings that could complicate installation.
* Confirm whether the user intends a replacement installation, dual boot, or a separate test disk.

## Preferred first physical test

Recommend using a spare computer or a separate physical SSD when practical.

This reduces the risk of damaging the user's existing operating system or personal files.

Do not make assumptions about the user's drive layout.

## Live USB preparation

Document a supported method for writing the verified ISO to a USB drive.

Warn clearly that writing an ISO to a USB drive erases the selected USB drive.

Require careful identification of the target USB device.

Do not provide an automated host-side command that guesses which disk should be overwritten.

## Booting the live OS

Explain how to select the USB boot device using the computer's firmware boot menu.

Explain what to do if the machine does not recognize the USB drive.

Document any limitations relating to Secure Boot.

Do not instruct the user to disable security features without first explaining the reason, consequences, and available alternatives.

## Installation

Explain the disk-selection screen.

Explain the difference between installing onto an empty disk and replacing an existing operating system.

Explain the risks of formatting partitions.

Require the user to verify the intended target disk before confirming any destructive operation.

If the user intends to preserve an existing operating system, do not tell them to erase the disk.

Document backup and recovery precautions.

## After installation

Explain how to:

* Remove the installation USB.
* Restart into AstraOS.
* Complete the initial login.
* Connect to the internet.
* Apply security updates.
* Verify the installed kernel.
* Check display resolution and audio.
* Verify networking.
* Inspect the disk layout.
* Create a recovery backup.

If a hardware driver is unsupported, document how to identify the problem and return to the previous operating system if necessary.

The physical installation guide must never imply that installation is risk-free.

---

# 21. POST-INSTALLATION CONFIGURATION

Create a conservative first-boot experience.

After the user logs in, provide useful system information and instructions.

Do not launch a collection of unnecessary setup wizards.

Where practical, provide guidance for:

* Connecting to Wi-Fi.
* Applying system updates.
* Setting the correct time zone.
* Configuring display resolution.
* Changing the desktop theme.
* Installing applications.
* Inspecting storage.
* Reading troubleshooting documentation.

Do not automatically download large AI models, GPU drivers, or optional development tools during initial login.

Do not run package upgrades without the appropriate permissions and error handling.

Do not require an online account merely to use AstraOS.

The basic desktop must remain usable offline.

---

# 22. FUTURE EXTENSIBILITY

Design AstraOS so future versions can introduce original system components without destabilizing the initial release.

Potential future projects include:

* An original desktop shell.
* A custom application launcher.
* An AstraOS system control panel.
* A package discovery application.
* A desktop search engine.
* A native AI assistant.
* A permission-controlled automation framework.
* A developer environment.
* A recovery interface.
* A custom display manager theme.
* Original system-management utilities.

These are extension points, not reasons to delay the initial bootable release.

Do not build all of these before producing the first valid ISO.

The first release must establish a stable foundation upon which future features can be developed.

Keep custom applications modular.

Use documented APIs and IPC mechanisms when needed.

Do not introduce unnecessary coupling between the desktop and the operating system's critical startup components.

---

# 23. LICENSING AND DISTRIBUTION

AstraOS must respect the licensing requirements of Debian, Linux, XFCE, Calamares, and all included third-party software.

Do not copy branding assets from other Linux distributions without checking their licensing terms.

Do not use proprietary assets unless redistribution is legally permitted.

Maintain appropriate upstream attribution.

Include required license notices.

Document how users can access applicable source code.

Review the trademark and redistribution policies relevant to the selected upstream distribution.

Do not claim that AstraOS is an official Debian release.

Clearly describe AstraOS as an independent distribution based on Debian.

Do not claim certifications, hardware compatibility, or security audits that have not occurred.

The release should clearly identify its status as an alpha release.

---

# 24. RELEASE VERSIONING

Use a documented versioning convention.

Initial release:

```
AstraOS 0.1.0 Alpha
```

Each build must report its distribution version.

Generate a manifest containing the available build metadata:

* AstraOS version.
* Base distribution and release.
* CPU architecture.
* Kernel package version.
* Build timestamp in UTC.
* Build-tool versions.
* Package manifest.
* ISO filename.
* ISO size.
* SHA-256 checksum.
* Build status.
* Validation status.

Keep the manifest consistent with the actual build.

Clearly distinguish the package manifest from the ISO checksum.

Do not include a fake release date or fabricated validation result.

Do not describe an image as stable while it is still an alpha release.

---

# 25. REQUIRED DOCUMENTATION

Create complete documentation rather than empty placeholder files.

## README.md

Explain what AstraOS is, its relationship to Debian, its main features, its current limitations, and the intended use of the alpha release.

Include a high-level architecture overview.

Document the project requirements and current build status.

## ARCHITECTURE.md

Describe:

* Boot process.
* Linux kernel.
* Initramfs.
* systemd.
* Graphical stack.
* Desktop session.
* Networking.
* Package management.
* Live image construction.
* Installer.
* Installed filesystem.
* Update mechanism.
* Security boundaries.

Explain the major design decisions.

## BUILDING.md

Provide:

* Supported build environment.
* Required packages.
* Build commands.
* Build outputs.
* Common errors.
* Cleanup behavior.
* CI instructions.
* Checksum generation.
* Troubleshooting instructions.

Include working commands that match the actual repository.

## INSTALLATION_VIRTUALBOX.md

Provide the complete VM test procedure described above.

## INSTALLATION_PHYSICAL_PC.md

Provide the complete physical installation and recovery precautions described above.

## SECURITY.md

Describe security reporting procedures and important distribution security limitations.

## KNOWN_LIMITATIONS.md

List all known functional problems, untested components, unsupported boot modes, hardware limitations, and unresolved installer issues.

Do not hide defects simply because they make the alpha release look less polished.

---

# 26. REQUIRED IMPLEMENTATION PHASES

Work in the following order.

## PHASE 1 — PROJECT FOUNDATION

Create the repository.

Inspect the build environment.

Select and verify the supported Debian base.

Establish distribution metadata.

Create the package list and configuration structure.

Create the initial branding assets.

Create the build scripts.

Create static validation tests.

Acceptance criterion:

The repository is organized, the build dependencies are documented, and the configuration can be validated.

## PHASE 2 — FIRST BOOTABLE IMAGE

Configure Debian Live.

Build an initial AstraOS image containing a working Linux kernel, live boot configuration, and minimal functional graphical desktop.

Generate the ISO.

Inspect the image.

Acceptance criterion:

A valid ISO artifact is generated and passes structural validation.

## PHASE 3 — DESKTOP INTEGRATION

Add the XFCE desktop.

Configure the display manager.

Apply branding.

Add practical default applications.

Configure networking and audio.

Test the live session.

Acceptance criterion:

A user can boot the ISO and use the graphical desktop.

## PHASE 4 — INSTALLER

Configure and integrate the selected upstream installer.

Implement the appropriate disk-selection and confirmation flow.

Verify user creation and installed-system configuration.

Acceptance criterion:

The installer can install AstraOS onto a designated disposable virtual disk.

## PHASE 5 — INSTALLED SYSTEM VALIDATION

Boot the newly installed virtual machine without the ISO.

Validate startup, login, networking, package management, updates, shutdown, and reboot.

Fix installation-related defects.

Acceptance criterion:

The installed VM can be used independently of the live environment.

## PHASE 6 — RELIABILITY AND SECURITY

Review system services, permissions, package selection, boot configuration, installer safety, and error handling.

Run all feasible automated tests.

Fix high-priority failures.

Acceptance criterion:

All critical tests pass, and unresolved problems are explicitly documented.

## PHASE 7 — RELEASE AUTOMATION

Configure cloud or CI image generation.

Produce a checksum and package manifest.

Upload the actual image artifact when the CI platform permits it.

Document where the user can retrieve it.

Acceptance criterion:

A successful build has a verifiable ISO artifact and associated build metadata.

## PHASE 8 — PHYSICAL HARDWARE PREPARATION

Write the physical installation guide.

Document firmware requirements, Secure Boot status, backup steps, USB creation, and hardware limitations.

Do not attempt physical installation automatically.

Acceptance criterion:

The documentation provides a safe, understandable path from VM testing to a later physical installation.

---

# 27. DEFINITION OF DONE

The first AstraOS release is complete only when the following conditions are met.

[ ] The repository contains the actual source configuration.

[ ] The selected Debian base is documented.

[ ] The package configuration is valid.

[ ] The build process executes in its documented environment.

[ ] A bootable x86_64 ISO is generated.

[ ] The ISO passes structural validation.

[ ] An SHA-256 checksum is generated and verified.

[ ] The live image boots in a tested virtual machine, if virtualization is available.

[ ] The graphical desktop starts successfully.

[ ] Essential desktop applications work.

[ ] Networking works in the tested environment.

[ ] The installer launches successfully.

[ ] Installation completes on a disposable virtual disk.

[ ] The installed VM boots without the live ISO.

[ ] The installed user can authenticate.

[ ] Basic system administration and package updates work.

[ ] Restart and shutdown work.

[ ] Installation does not require fixed or shared credentials.

[ ] No automated test attempts to erase the host computer's physical disks.

[ ] Required licensing notices and upstream attributions are included.

[ ] The main documentation describes the actual implementation.

[ ] Known limitations are documented honestly.

[ ] The cloud or CI build workflow is implemented if the selected environment supports it.

[ ] The build manifest reports the actual result.

[ ] The physical installation guide contains backup and disk-safety precautions.

If a criterion has not been tested, mark it UNTESTED.

If a criterion has failed, mark it FAILED and describe the error.

If a criterion cannot be tested in the current environment, mark it BLOCKED and state what environment or capability is missing.

Do not mark the project complete merely because all the expected files exist.

---

# 28. STRICT INSTRUCTIONS FOR THE AI CODING AGENT

Follow these execution rules throughout the project.

### Rule 1: Implement, do not just explain.

Create the real files, scripts, configurations, and tests.

Do not respond with only architectural recommendations.

### Rule 2: Work incrementally.

Establish a working bootable base before adding optional features.

Build and validate each major phase.

Do not accumulate hundreds of untested changes.

### Rule 3: Use actual tools.

Inspect command output.

Run tests.

Read build logs.

Investigate failures.

Make corrective changes.

Do not infer that an operation succeeded simply because a command was issued.

### Rule 4: Never fabricate output.

Do not invent ISO filenames, download URLs, package manifests, checksums, test results, CI run identifiers, or successful boot reports.

### Rule 5: Respect the user's computer.

Do not repartition, format, wipe, or modify the real host computer's bootloader or system disk.

Do not flash a USB drive automatically.

Do not execute destructive installation commands on the development host.

All installer tests must use designated disposable virtual disks.

### Rule 6: Prefer low-resource development.

Avoid unnecessary GPU requirements.

Use lightweight desktop components.

Favor cloud-based ISO building if the local PC is underpowered.

### Rule 7: Do not introduce avoidable complexity.

Do not write a new kernel for the first release.

Do not create an entirely new package manager.

Do not build an independent desktop environment before the working distribution exists.

Do not replace established security components without a compelling reason.

### Rule 8: Do not silently ignore failures.

If a build or test fails, investigate it.

If a problem cannot be resolved, document it and continue with independent work that remains possible.

### Rule 9: Never compromise disk safety for convenience.

Use established installer components.

Show the target disk clearly.

Require explicit confirmation before destructive operations.

Do not infer which disk the user intends to erase.

### Rule 10: Finish with an actionable handoff.

At the end of the available work, provide:

1. A summary of what was implemented.
2. The repository structure.
3. The exact build command.
4. The actual build status.
5. The actual test results.
6. The location of the ISO if it was successfully generated.
7. The checksum and manifest locations.
8. Instructions for testing the ISO in VirtualBox.
9. Known limitations.
10. The remaining steps required before physical installation.

If the ISO could not be built, say so explicitly and explain the immediate blocker.

Never pretend that creating a build script is equivalent to producing an operating system.

---

# FINAL DIRECTIVE

Begin by examining the current development environment and determining the most reliable way to produce the AstraOS bootable ISO.

Then create the repository, implement the foundation, build the image, and validate the results.

Do not wait for additional instructions to start routine engineering work.

Make reasonable, documented decisions when minor implementation details are unspecified.

Prioritize actual bootability, installation reliability, security, low resource consumption, reproducible builds, and safe testing.

**The objective is not to make an operating system look real. The objective is to build a real, bootable, installable Linux distribution that we can test in VirtualBox first and consider installing on physical hardware only after it passes the required validation.**
