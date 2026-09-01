# ADR 0061: Build Platform-Scoped Player Runtime Bundles

Status: accepted

Date: 2026-09-01

## Context

Issue #432 requires a packaged co-located player PWA, API, and writable store.
The current `pnpm player:start` checkpoint runs only from a bootstrapped source
checkout: Node builds the player PWA and the repository virtual environment
starts the Python application. The application and data boundaries are already
separate, but there is no release artifact that can start without the checkout,
Node, pnpm, or a separately installed Python runtime.

The repository has not selected a supported end-user operating system,
installer format, signing identity, notarization policy, or update trust model.
Choosing one implicitly in a packaging checkpoint would be a product and
release decision rather than an implementation detail.

## Decision

The repository builds an unsigned, host-platform runtime archive as the release
bundle contract. It is a checkpoint for release engineering, not yet the
supported operating-system installer.

- PyInstaller creates one directory containing the Python interpreter,
  application modules, native dependencies, and the already built and verified
  `dist-player` PWA. The PWA is not rebuilt when the player launches.
- The archive name binds the product version, operating system, architecture,
  and Python ABI used to build it. A schema-versioned manifest inventories every
  application file with its type, mode, size, and SHA-256 digest. A sidecar
  SHA-256 digest covers the complete compressed archive.
- Bundle creation is supported only on Darwin and Linux build hosts. The bundle
  is for that exact host platform and architecture; it is not cross-compiled.
- A frozen runtime resolves assets only from its bundled immutable asset
  directory. Source-checkout execution keeps the existing `dist-player`
  location.
- A frozen runtime defaults player data to the platform application-data root:
  `~/Library/Application Support/Poker Hero/data` on macOS and
  `${XDG_DATA_HOME:-~/.local/share}/poker-hero/player/data` on Linux.
  `POKER_DATA_DIR` remains an explicit override. The bundle never contains,
  copies, resets, or implicitly migrates this workspace.
- The same executable starts the fixed loopback runtime and dispatches the
  existing `export-and-remove` transaction. Data removal therefore keeps the
  same backup verification, lifetime lease, workspace inventory, and retained
  failure-path behavior as the source command.
- CI builds the host artifact from hash-locked development dependencies,
  extracts it into a clean temporary directory, verifies the complete manifest,
  starts it without a checkout or Node/Python toolchain, checks the embedded
  shell and unauthenticated API denial, then stops it and exercises packaged
  export-before-remove.

The archive is deliberately unsigned and has no installer, auto-updater,
application-file removal command, or browser-PWA removal automation. A future
platform decision must define those trust and lifecycle boundaries before the
artifact is presented as a supported end-user installation.

## Consequences

Release work now has a concrete, versioned artifact contract and a credential-
free smoke test. Packaged execution preserves the same fixed
`127.0.0.1:8765` origin, disabled proxy headers, local authentication, Host and
Origin checks, CSRF protection, player workspace, and export/remove semantics
as source execution.

Application bytes and player data remain independently replaceable. Extracting
a newer bundle cannot silently overwrite or adopt a workspace beyond the
existing versioned migration boundary, and deleting an extracted bundle does
not claim to delete player data.

This progresses the packaging/setup and uninstall handoff criteria of #432. It
does not select a supported user platform, sign or publish a release, install or
update application files, remove a browser PWA, add the missing player import
workflow or future learning stores, implement optional remote solved lookup, or
close the Phase 1 gate.
