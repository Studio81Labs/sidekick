# Dependency And Infrastructure Pin Updates

This procedure updates immutable inputs without weakening the checks described
by [ADR 0043](../decisions/0043-adopt-studio81-security-and-ci-baseline.md).

## Python Locks

Edit `apps/backend/pyproject.toml`, then regenerate under the declared Python
3.12 image and pinned compiler:

```bash
scripts/ci/compile-python-locks.sh --write
scripts/ci/compile-python-locks.sh --check
```

Review both lock diffs. Validate production and development installs with
`--require-hashes`, install the local project with `--no-deps
--no-build-isolation`, and run `python -m pip check`. A compiler or build-backend
upgrade is part of the same review and must regenerate both locks.
`--write` deliberately resolves the complete compatible graph without using the
existing locks as constraints, allowing changed manifest pins to move; review
every direct and transitive change it produces. `--check` constrains resolution
to the committed pins, so later PyPI publication timing cannot make an unchanged
lock fail freshness validation.

## Container Images And GitHub Actions

Keep the readable tag and replace the digest with the registry digest for that
exact tag and platform manifest. Renovate normally proposes these updates.
After a manual update, run:

```bash
python3 scripts/ci/check-container-pins.py
docker build -f apps/backend/Dockerfile -t poker-hero-backend:test .
docker build -f apps/pwa/Dockerfile -t poker-hero-pwa:test .
```

GitHub Actions must use a full reviewed commit SHA with the release version in a
comment. Apply a shared action update consistently across every workflow and
compare it with the sibling baseline.

## Debian Snapshot And `gosu`

The backend Dockerfile declares both pins. To refresh them:

1. Choose a UTC snapshot timestamp and confirm
   `https://snapshot.debian.org/archive/debian/<timestamp>/dists/trixie/Release`
   exists.
2. In the digest-pinned Python base, replace the sources with only that snapshot,
   run `apt-get update`, and inspect `apt-cache policy gosu`.
3. Update the snapshot and exact candidate version together in
   `apps/backend/Dockerfile` and `scripts/ci/check-container-pins.py`.
4. Build the backend image for `linux/amd64` and `linux/arm64` when the base
   digest supports both. Confirm `dpkg-query -W -f='${Version}' gosu` equals the
   declared version and `gosu --version` succeeds.
5. Run the container-pin guard, backend tests, image healthcheck, and Compose
   validation. Review the signed `Release` source and package diff before merge.

Do not add a live Debian mirror as a fallback. If a snapshot is unavailable,
select another dated snapshot and review the resulting package version.
