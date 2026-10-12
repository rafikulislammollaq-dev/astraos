# AstraOS build convenience targets (plan §16).
#
# These are shortcuts only. Every target calls a script in scripts/, so the behaviour is
# identical whether it is invoked through make or directly. That matters because CI, the
# documentation and a human all need to run the same code.
#
# The build targets require a Linux host with the build dependencies installed. The
# check and lint targets run anywhere with Python 3 and a shell.

SHELL := /bin/bash
.DEFAULT_GOAL := help

REPO_ROOT := $(shell cd "$(dir $(lastword $(MAKEFILE_LIST)))" && pwd)
SCRIPTS   := $(REPO_ROOT)/scripts
VERSION   := $(shell sed -n 's/^ASTRAOS_VERSION="\(.*\)"/\1/p' $(REPO_ROOT)/VERSION)

.PHONY: help check test lint packages build iso validate checksums manifest release clean distclean verify-packages

help:
	@echo "AstraOS $(VERSION) - available targets"
	@echo ""
	@echo "  make check              run the static test suite (runs anywhere)"
	@echo "  make lint               shell syntax check on every script"
	@echo "  make verify-packages    check the package list against the Debian archive (needs network)"
	@echo ""
	@echo "  make validate           validate the BUILD HOST (Linux, tools, disk, mirrors)"
	@echo "  make bootstrap          install the build dependencies on this host (asks for sudo)"
	@echo "  make packages           build the AstraOS .deb packages"
	@echo "  make build              build the AstraOS ISO (alias for make iso)"
	@echo "  make iso                build the AstraOS ISO"
	@echo "  make validate-iso       structurally validate the newest ISO in dist/"
	@echo "  make checksums          regenerate checksums for the newest ISO"
	@echo "  make manifest           regenerate the manifest for the newest ISO"
	@echo "  make release            package a release directory from dist/"
	@echo ""
	@echo "  make clean              remove build logs and the live-build working tree"
	@echo "  make distclean          also remove dist/ output and the package build tree"
	@echo ""
	@echo "Building requires a Linux host. See docs/BUILDING.md, and docs/ENVIRONMENT.md"
	@echo "for what was measured on the machine this project was started on."

# ---------------------------------------------------------------------------
# Checks that run anywhere
# ---------------------------------------------------------------------------
check test:
	@echo "==> static test suite"
	@python3 $(REPO_ROOT)/tests/run.py

lint:
	@echo "==> shell syntax check"
	@fail=0; \
	for script in $(SCRIPTS)/*.sh \
	              $(REPO_ROOT)/config/live-build/auto/config \
	              $(REPO_ROOT)/config/live-build/auto/build \
	              $(REPO_ROOT)/config/live-build/config/hooks/live/*.hook.chroot; do \
	    if [ -f "$$script" ]; then \
	        if bash -n "$$script" 2>/dev/null; then \
	            printf '  ok    %s\n' "$${script#$(REPO_ROOT)/}"; \
	        else \
	            printf '  FAIL  %s\n' "$${script#$(REPO_ROOT)/}"; \
	            bash -n "$$script"; \
	            fail=1; \
	        fi; \
	    fi; \
	done; \
	if command -v shellcheck >/dev/null 2>&1; then \
	    echo "==> shellcheck"; \
	    shellcheck -S warning $(SCRIPTS)/*.sh || fail=1; \
	else \
	    echo "==> shellcheck not installed; skipped"; \
	fi; \
	exit $$fail

verify-packages:
	@echo "==> verifying the package selection against the Debian archive"
	@python3 $(SCRIPTS)/verify-package-availability.py

# ---------------------------------------------------------------------------
# Build host and packages
# ---------------------------------------------------------------------------
validate:
	@$(SCRIPTS)/validate-environment.sh

bootstrap:
	@$(SCRIPTS)/bootstrap-build-environment.sh

packages:
	@$(SCRIPTS)/build-packages.sh

# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------
build iso:
	@$(SCRIPTS)/build-iso.sh

NEWEST_ISO := $(shell ls -1t $(REPO_ROOT)/dist/*.iso 2>/dev/null | head -n1)

validate-iso:
	@if [ -z "$(NEWEST_ISO)" ]; then \
	    echo "no ISO found in dist/. Build one first: make build" >&2; exit 1; \
	fi
	@$(SCRIPTS)/validate-iso.sh "$(NEWEST_ISO)"

checksums:
	@if [ -z "$(NEWEST_ISO)" ]; then \
	    echo "no ISO found in dist/. Build one first: make build" >&2; exit 1; \
	fi
	@$(SCRIPTS)/generate-checksums.sh "$(NEWEST_ISO)"

manifest:
	@if [ -z "$(NEWEST_ISO)" ]; then \
	    echo "no ISO found in dist/. Build one first: make build" >&2; exit 1; \
	fi
	@$(SCRIPTS)/generate-manifest.sh "$(NEWEST_ISO)"

release:
	@$(SCRIPTS)/package-release.sh

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
# clean removes things that are cheap to rebuild and safe to lose.
# distclean additionally removes release artifacts, which are expensive to rebuild.
clean:
	@echo "==> removing logs and the live-build working tree"
	@rm -rf "$(REPO_ROOT)/logs"
	@rm -rf "$(REPO_ROOT)/build/live-build"
	@echo "    kept: dist/ output and build/packages"
	@echo "    note: no ISO was deleted and no source file was touched"

distclean:
	@echo "==> removing all generated output"
	@echo "    this deletes build artifacts AND any built ISO in dist/"
	@rm -rf "$(REPO_ROOT)/logs"
	@rm -rf "$(REPO_ROOT)/build"
	@rm -rf "$(REPO_ROOT)/dist"
	@mkdir -p "$(REPO_ROOT)/build" "$(REPO_ROOT)/dist"
	@touch "$(REPO_ROOT)/build/.gitkeep" "$(REPO_ROOT)/dist/.gitkeep"
	@echo "    regenerated branding assets are NOT deleted (they are inputs to a build)"
	@echo "    regenerate them with: python3 branding/tools/render_assets.py"
