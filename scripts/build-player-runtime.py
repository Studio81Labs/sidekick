#!/usr/bin/env python3
"""Build a host-platform Poker Hero player runtime archive."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import shutil
from stat import S_ISDIR, S_ISREG
import subprocess
import sys
import tarfile
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "apps" / "backend"
PLAYER_ENTRYPOINT = BACKEND / "app" / "player_main.py"
PLAYER_ASSETS = ROOT / "apps" / "pwa" / "dist-player"
REQUIRED_PLAYER_ASSETS = (
    "index.html",
    "manifest.webmanifest",
    "sw.js",
)
ARTIFACT_SCHEMA_VERSION = 1


class PlayerPackageError(RuntimeError):
    pass


def _safe_tag(value: str) -> str:
    tag = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not tag:
        raise PlayerPackageError("Could not derive a safe runtime artifact tag")
    return tag


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bundle_entries(bundle_root: Path) -> list[dict[str, Any]]:
    resolved_root = bundle_root.resolve(strict=True)
    entries: list[dict[str, Any]] = []
    for path in sorted(bundle_root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(bundle_root).as_posix()
        if path == bundle_root / "manifest.json":
            continue
        metadata = path.lstat()
        if path.is_symlink():
            target = os.readlink(path)
            if Path(target).is_absolute():
                raise PlayerPackageError(
                    f"Runtime bundle symlink {relative} has an absolute target"
                )
            resolved_target = (path.parent / target).resolve(strict=True)
            if not resolved_target.is_relative_to(resolved_root):
                raise PlayerPackageError(
                    f"Runtime bundle symlink {relative} escapes the bundle"
                )
            entries.append(
                {
                    "kind": "symlink",
                    "mode": metadata.st_mode & 0o777,
                    "path": relative,
                    "target": target,
                }
            )
            continue
        if S_ISDIR(metadata.st_mode):
            continue
        if not S_ISREG(metadata.st_mode):
            raise PlayerPackageError(
                f"Runtime bundle entry {relative} is not a regular file"
            )
        entries.append(
            {
                "kind": "file",
                "mode": metadata.st_mode & 0o777,
                "path": relative,
                "sha256": _sha256_file(path),
                "size": metadata.st_size,
            }
        )
    return entries


def _write_bundle_manifest(
    bundle_root: Path,
    *,
    artifact_name: str,
    product_version: str,
    entrypoint: str,
) -> None:
    manifest = {
        "artifact": "poker-hero-player-runtime",
        "artifact_name": artifact_name,
        "entrypoint": entrypoint,
        "files": _bundle_entries(bundle_root),
        "platform": {
            "machine": _safe_tag(platform.machine()),
            "python": platform.python_version(),
            "system": _safe_tag(platform.system()),
        },
        "product_version": product_version,
        "schema_version": ARTIFACT_SCHEMA_VERSION,
    }
    (bundle_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_archive(bundle_root: Path, archive_path: Path) -> None:
    with tarfile.open(archive_path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        paths = [bundle_root, *sorted(bundle_root.rglob("*"))]
        for path in paths:
            relative = path.relative_to(bundle_root.parent)
            info = archive.gettarinfo(str(path), arcname=relative.as_posix())
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            if info.isfile():
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
            else:
                archive.addfile(info)


def _require_player_assets() -> None:
    if PLAYER_ASSETS.is_symlink() or not PLAYER_ASSETS.is_dir():
        raise PlayerPackageError(
            "The verified player PWA build is missing; run pnpm player:build"
        )
    for relative in REQUIRED_PLAYER_ASSETS:
        candidate = PLAYER_ASSETS / relative
        if candidate.is_symlink() or not candidate.is_file():
            raise PlayerPackageError(
                f"The verified player PWA asset {relative} is missing"
            )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a versioned, host-platform player runtime archive with an "
            "embedded Python runtime and verified PWA assets."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "dist" / "player-runtime",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace this version's existing archive and checksum",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    if platform.system() not in {"Darwin", "Linux"}:
        raise PlayerPackageError(
            "Player runtime bundle builds currently support Darwin and Linux hosts"
        )
    _require_player_assets()

    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    product_version = package.get("version")
    if not isinstance(product_version, str) or not product_version:
        raise PlayerPackageError("package.json must define a product version")
    python_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    artifact_name = "-".join(
        (
            "poker-hero-player",
            _safe_tag(product_version),
            _safe_tag(platform.system()),
            _safe_tag(platform.machine()),
            python_tag,
        )
    )
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"{artifact_name}.tar.gz"
    checksum_path = output_dir / f"{artifact_name}.tar.gz.sha256"
    existing = [path for path in (archive_path, checksum_path) if path.exists()]
    if existing and not args.force:
        raise PlayerPackageError(
            "Refusing to replace an existing player runtime artifact; pass --force"
        )
    for path in existing:
        if path.is_symlink() or not path.is_file():
            raise PlayerPackageError(
                f"Refusing to replace unsafe artifact destination {path}"
            )

    with tempfile.TemporaryDirectory(prefix="poker-hero-player-package-") as raw:
        temporary = Path(raw)
        dist_path = temporary / "pyinstaller-dist"
        work_path = temporary / "pyinstaller-work"
        spec_path = temporary / "pyinstaller-spec"
        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            "--noupx",
            "--onedir",
            "--name",
            "poker-hero-player",
            "--paths",
            str(BACKEND),
            "--add-data",
            f"{PLAYER_ASSETS}{os.pathsep}player-assets",
            "--distpath",
            str(dist_path),
            "--workpath",
            str(work_path),
            "--specpath",
            str(spec_path),
            "--log-level",
            "WARN",
            str(PLAYER_ENTRYPOINT),
        ]
        subprocess.run(command, cwd=BACKEND, check=True)

        pyinstaller_bundle = dist_path / "poker-hero-player"
        executable_name = (
            "poker-hero-player.exe"
            if platform.system() == "Windows"
            else "poker-hero-player"
        )
        executable = pyinstaller_bundle / executable_name
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise PlayerPackageError(
                "PyInstaller did not produce an executable player runtime"
            )

        bundle_root = temporary / artifact_name
        shutil.copytree(pyinstaller_bundle, bundle_root, symlinks=True)
        (bundle_root / "BUNDLE-README.txt").write_text(
            "Poker Hero local player runtime\n"
            f"Version: {product_version}\n"
            f"Platform: {platform.system()} {platform.machine()}\n\n"
            f"Start: ./{executable_name}\n"
            "Export and remove player data:\n"
            f"  ./{executable_name} export-and-remove /absolute/private/backup.zip "
            "--confirm-remove-data\n\n"
            "This archive contains application files only. It does not contain, "
            "install, migrate, or remove the player data workspace.\n",
            encoding="utf-8",
        )
        _write_bundle_manifest(
            bundle_root,
            artifact_name=artifact_name,
            product_version=product_version,
            entrypoint=executable_name,
        )

        temporary_archive = temporary / archive_path.name
        _write_archive(bundle_root, temporary_archive)
        archive_digest = _sha256_file(temporary_archive)
        temporary_checksum = temporary / checksum_path.name
        temporary_checksum.write_text(
            f"{archive_digest}  {archive_path.name}\n",
            encoding="ascii",
        )
        os.replace(temporary_archive, archive_path)
        os.replace(temporary_checksum, checksum_path)

    print(archive_path)
    print(checksum_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, PlayerPackageError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
