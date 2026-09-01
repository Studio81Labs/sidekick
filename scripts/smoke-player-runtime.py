#!/usr/bin/env python3
"""Verify and exercise an extracted player runtime archive without a checkout."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import signal
import socket
from stat import S_ISREG
import subprocess
import sys
import tarfile
import tempfile
from time import monotonic, sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile


PLAYER_ORIGIN = "http://127.0.0.1:8765"
PLAYER_AUTHORITY = "127.0.0.1:8765"
PLAYER_WORKSPACE_MANIFEST = ".poker-hero-player-workspace.json"


class PlayerPackageSmokeError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_relative(path: PurePosixPath) -> PurePosixPath:
    parts: list[str] = []
    for part in path.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise PlayerPackageSmokeError(
                    "Runtime archive link escapes the bundle"
                )
            parts.pop()
            continue
        parts.append(part)
    return PurePosixPath(*parts)


def _safe_tag(value: str) -> str:
    tag = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not tag:
        raise PlayerPackageSmokeError("Runtime bundle platform tag is invalid")
    return tag


def _safe_member_target(member: tarfile.TarInfo) -> PurePosixPath:
    path = PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts:
        raise PlayerPackageSmokeError(
            f"Runtime archive contains unsafe path {member.name}"
        )
    if member.issym() or member.islnk():
        target = PurePosixPath(member.linkname)
        if target.is_absolute():
            raise PlayerPackageSmokeError(
                f"Runtime archive link {member.name} has an absolute target"
            )
        _normalized_relative(path.parent.joinpath(target))
    if member.isdev() or member.isfifo():
        raise PlayerPackageSmokeError(
            f"Runtime archive contains special entry {member.name}"
        )
    return path


def _extract_archive(archive_path: Path, destination: Path) -> Path:
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        roots = {
            path.parts[0]
            for member in members
            if (path := _safe_member_target(member)).parts
        }
        if len(roots) != 1:
            raise PlayerPackageSmokeError(
                "Runtime archive must contain exactly one root directory"
            )
        root_name = next(iter(roots))
        for member in members:
            if not member.issym():
                continue
            path = PurePosixPath(member.name)
            resolved_link = _normalized_relative(
                path.parent.joinpath(PurePosixPath(member.linkname))
            )
            if not resolved_link.parts or resolved_link.parts[0] != root_name:
                raise PlayerPackageSmokeError(
                    f"Runtime archive link {member.name} escapes the bundle root"
                )
        destination.mkdir(mode=0o700, parents=True)
        links: list[tarfile.TarInfo] = []
        for member in members:
            relative = _safe_member_target(member)
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(mode=member.mode & 0o777, parents=True, exist_ok=True)
                continue
            if member.issym():
                links.append(member)
                continue
            if not member.isfile():
                raise PlayerPackageSmokeError(
                    f"Runtime archive contains unsupported entry {member.name}"
                )
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise PlayerPackageSmokeError(
                    f"Runtime archive file {member.name} cannot be read"
                )
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(member.mode & 0o777)
        resolved_bundle_root = (destination / root_name).resolve(strict=True)
        for member in links:
            relative = _safe_member_target(member)
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not target.parent.resolve(strict=True).is_relative_to(
                resolved_bundle_root
            ):
                raise PlayerPackageSmokeError(
                    f"Runtime archive link {member.name} has an unsafe parent"
                )
            target.symlink_to(member.linkname)
        for member in links:
            relative = _safe_member_target(member)
            target = destination.joinpath(*relative.parts)
            if not target.resolve(strict=True).is_relative_to(resolved_bundle_root):
                raise PlayerPackageSmokeError(
                    f"Runtime archive link {member.name} escapes the bundle"
                )
    bundle_root = destination / roots.pop()
    if bundle_root.is_symlink() or not bundle_root.is_dir():
        raise PlayerPackageSmokeError("Runtime archive root is not a directory")
    return bundle_root


def _bundle_manifest(bundle_root: Path) -> dict[str, Any]:
    manifest_path = bundle_root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise PlayerPackageSmokeError("Runtime bundle manifest is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlayerPackageSmokeError("Runtime bundle manifest is invalid") from exc
    if set(manifest) != {
        "artifact",
        "artifact_name",
        "entrypoint",
        "files",
        "platform",
        "product_version",
        "schema_version",
    }:
        raise PlayerPackageSmokeError("Runtime bundle manifest fields are invalid")
    if manifest.get("schema_version") != 1:
        raise PlayerPackageSmokeError("Runtime bundle schema is unsupported")
    if manifest.get("artifact") != "poker-hero-player-runtime":
        raise PlayerPackageSmokeError("Runtime bundle artifact identity is invalid")
    if manifest.get("artifact_name") != bundle_root.name:
        raise PlayerPackageSmokeError("Runtime bundle artifact name is invalid")
    product_version = manifest.get("product_version")
    if not isinstance(product_version, str) or not product_version:
        raise PlayerPackageSmokeError("Runtime bundle product version is invalid")
    platform_binding = manifest.get("platform")
    if not isinstance(platform_binding, dict) or set(platform_binding) != {
        "machine",
        "python",
        "system",
    }:
        raise PlayerPackageSmokeError("Runtime bundle platform binding is invalid")
    system = platform_binding.get("system")
    machine = platform_binding.get("machine")
    python_version = platform_binding.get("python")
    if system != _safe_tag(platform.system()) or machine != _safe_tag(
        platform.machine()
    ):
        raise PlayerPackageSmokeError(
            "Runtime bundle platform does not match the smoke-test host"
        )
    if not isinstance(python_version, str) or re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+",
        python_version,
    ) is None:
        raise PlayerPackageSmokeError("Runtime bundle Python binding is invalid")
    if python_version != platform.python_version():
        raise PlayerPackageSmokeError(
            "Runtime bundle Python binding does not match the smoke-test host"
        )
    python_parts = python_version.split(".")
    expected_artifact_name = "-".join(
        (
            "poker-hero-player",
            _safe_tag(product_version),
            system,
            machine,
            f"cp{python_parts[0]}{python_parts[1]}",
        )
    )
    if manifest["artifact_name"] != expected_artifact_name:
        raise PlayerPackageSmokeError("Runtime bundle identity bindings disagree")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise PlayerPackageSmokeError("Runtime bundle file inventory is invalid")
    entrypoint = manifest.get("entrypoint")
    if not isinstance(entrypoint, str):
        raise PlayerPackageSmokeError("Runtime bundle entrypoint is invalid")
    entrypoint_path = PurePosixPath(entrypoint)
    if (
        entrypoint_path.is_absolute()
        or len(entrypoint_path.parts) != 1
        or entrypoint_path.name != entrypoint
    ):
        raise PlayerPackageSmokeError("Runtime bundle entrypoint path is unsafe")
    return manifest


def _verify_bundle(bundle_root: Path) -> Path:
    manifest = _bundle_manifest(bundle_root)
    entries = manifest["files"]
    expected_paths: set[str] = set()
    resolved_root = bundle_root.resolve(strict=True)
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise PlayerPackageSmokeError("Runtime bundle file entry is invalid")
        relative = entry["path"]
        pure_path = PurePosixPath(relative)
        if pure_path.is_absolute() or ".." in pure_path.parts or not pure_path.parts:
            raise PlayerPackageSmokeError(
                f"Runtime bundle manifest contains unsafe path {relative}"
            )
        if relative in expected_paths:
            raise PlayerPackageSmokeError(
                f"Runtime bundle manifest repeats path {relative}"
            )
        expected_paths.add(relative)
        path = bundle_root.joinpath(*pure_path.parts)
        kind = entry.get("kind")
        mode = entry.get("mode")
        if not isinstance(mode, int) or not 0 <= mode <= 0o777:
            raise PlayerPackageSmokeError(
                f"Runtime bundle entry {relative} has an invalid mode"
            )
        if kind == "symlink":
            if set(entry) != {"kind", "mode", "path", "target"} or not isinstance(
                entry.get("target"),
                str,
            ):
                raise PlayerPackageSmokeError(
                    f"Runtime bundle symlink {relative} has invalid metadata"
                )
            if not path.is_symlink() or os.readlink(path) != entry.get("target"):
                raise PlayerPackageSmokeError(
                    f"Runtime bundle symlink {relative} does not match its manifest"
                )
            if not path.resolve(strict=True).is_relative_to(resolved_root):
                raise PlayerPackageSmokeError(
                    f"Runtime bundle symlink {relative} escapes the bundle"
                )
            continue
        if kind != "file" or path.is_symlink():
            raise PlayerPackageSmokeError(
                f"Runtime bundle file {relative} has the wrong type"
            )
        if (
            set(entry) != {"kind", "mode", "path", "sha256", "size"}
            or not isinstance(entry.get("size"), int)
            or entry["size"] < 0
            or not isinstance(entry.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None
        ):
            raise PlayerPackageSmokeError(
                f"Runtime bundle file {relative} has invalid metadata"
            )
        metadata = path.stat()
        if not S_ISREG(metadata.st_mode):
            raise PlayerPackageSmokeError(
                f"Runtime bundle file {relative} is not regular"
            )
        if metadata.st_size != entry.get("size"):
            raise PlayerPackageSmokeError(
                f"Runtime bundle file {relative} has the wrong size"
            )
        if metadata.st_mode & 0o777 != mode:
            raise PlayerPackageSmokeError(
                f"Runtime bundle file {relative} has the wrong mode"
            )
        if _sha256_file(path) != entry.get("sha256"):
            raise PlayerPackageSmokeError(
                f"Runtime bundle file {relative} failed its checksum"
            )

    actual_paths = {
        path.relative_to(bundle_root).as_posix()
        for path in bundle_root.rglob("*")
        if (path.is_symlink() or not path.is_dir())
        and path != bundle_root / "manifest.json"
    }
    if actual_paths != expected_paths:
        raise PlayerPackageSmokeError(
            "Runtime bundle file inventory does not match the extracted files"
        )

    entrypoint = bundle_root / manifest["entrypoint"]
    if entrypoint.is_symlink() or not entrypoint.is_file():
        raise PlayerPackageSmokeError("Runtime bundle entrypoint is missing")
    if not os.access(entrypoint, os.X_OK):
        raise PlayerPackageSmokeError("Runtime bundle entrypoint is not executable")
    entrypoint_entry = next(
        (entry for entry in entries if entry.get("path") == manifest["entrypoint"]),
        None,
    )
    if (
        entrypoint_entry is None
        or entrypoint_entry.get("kind") != "file"
        or not entrypoint_entry["mode"] & 0o111
    ):
        raise PlayerPackageSmokeError(
            "Runtime bundle entrypoint is not bound as an executable file"
        )
    return entrypoint


def _verify_archive_checksum(archive_path: Path) -> None:
    checksum_path = archive_path.with_name(archive_path.name + ".sha256")
    if not checksum_path.exists():
        raise PlayerPackageSmokeError("Runtime archive checksum sidecar is missing")
    if checksum_path.is_symlink() or not checksum_path.is_file():
        raise PlayerPackageSmokeError(
            "Runtime archive checksum sidecar must be a regular file"
        )
    fields = checksum_path.read_text(encoding="ascii").strip().split()
    if len(fields) != 2 or fields[1] != archive_path.name:
        raise PlayerPackageSmokeError("Runtime archive checksum sidecar is invalid")
    if fields[0] != _sha256_file(archive_path):
        raise PlayerPackageSmokeError("Runtime archive failed its checksum")


def _request(path: str) -> tuple[int, bytes, dict[str, str]]:
    request = Request(
        f"{PLAYER_ORIGIN}{path}",
        headers={"Host": PLAYER_AUTHORITY},
    )
    try:
        with urlopen(request, timeout=1) as response:
            return (
                response.status,
                response.read(),
                {key.lower(): value for key, value in response.headers.items()},
            )
    except HTTPError as exc:
        return (
            exc.code,
            exc.read(),
            {key.lower(): value for key, value in exc.headers.items()},
        )


def _require_player_port_available() -> None:
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=0.2):
            pass
    except OSError:
        return
    raise PlayerPackageSmokeError(
        "The player runtime smoke-test port 127.0.0.1:8765 is already in use"
    )


def _wait_for_runtime(
    process: subprocess.Popen[bytes],
    *,
    data_dir: Path,
) -> None:
    deadline = monotonic() + 20
    while monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise PlayerPackageSmokeError(
                "Packaged runtime exited before it became ready:\n"
                + stdout.decode(errors="replace")
                + stderr.decode(errors="replace")
            )
        try:
            status, body, headers = _request("/")
        except (OSError, URLError):
            sleep(0.1)
            continue
        if status != 200 or b"Poker Hero" not in body:
            raise PlayerPackageSmokeError(
                "Packaged runtime did not serve the embedded player shell"
            )
        if headers.get("cache-control") != "no-store":
            raise PlayerPackageSmokeError(
                "Packaged runtime shell did not preserve no-store"
            )
        sleep(0.1)
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise PlayerPackageSmokeError(
                "Packaged runtime exited during its readiness check:\n"
                + stdout.decode(errors="replace")
                + stderr.decode(errors="replace")
            )
        if not (data_dir / PLAYER_WORKSPACE_MANIFEST).is_file():
            raise PlayerPackageSmokeError(
                "Packaged runtime did not initialize its requested data workspace"
            )
        return
    raise PlayerPackageSmokeError("Packaged runtime did not become ready")


def _stop_runtime(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify and exercise a player runtime release archive"
    )
    parser.add_argument("archive", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    archive_path = args.archive.expanduser().resolve(strict=True)
    if archive_path.is_symlink() or not archive_path.is_file():
        raise PlayerPackageSmokeError("Runtime archive must be a regular file")
    _verify_archive_checksum(archive_path)

    true_command = shutil.which("true")
    if true_command is None:
        raise PlayerPackageSmokeError(
            "The runtime smoke test requires the POSIX true command"
        )

    with tempfile.TemporaryDirectory(prefix="poker-hero-player-smoke-") as raw:
        temporary = Path(raw)
        bundle_root = _extract_archive(archive_path, temporary / "extract")
        entrypoint = _verify_bundle(bundle_root)
        data_dir = temporary / "player-data"
        data_dir.mkdir(mode=0o700)
        backup_dir = temporary / "backup"
        backup_dir.mkdir(mode=0o700)
        backup_path = backup_dir / "player-backup.zip"
        environment = {
            "BROWSER": true_command,
            "PATH": os.pathsep.join(
                path
                for path in (str(Path(true_command).parent), "/usr/bin", "/bin")
                if path
            ),
            "POKER_DATA_DIR": str(data_dir),
            "POKER_DEPLOYMENT_ENVIRONMENT": "local",
        }
        _require_player_port_available()
        process = subprocess.Popen(
            [str(entrypoint)],
            cwd=bundle_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            _wait_for_runtime(process, data_dir=data_dir)
            status, _body, headers = _request("/api/player/storage")
            if status != 401 or headers.get("cache-control") != "no-store":
                raise PlayerPackageSmokeError(
                    "Packaged runtime did not preserve authenticated storage denial"
                )
        finally:
            _stop_runtime(process)

        result = subprocess.run(
            [
                str(entrypoint),
                "export-and-remove",
                str(backup_path),
                "--data-dir",
                str(data_dir),
                "--confirm-remove-data",
            ],
            cwd=bundle_root,
            env=environment,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise PlayerPackageSmokeError(
                "Packaged export-and-remove failed:\n"
                + result.stdout.decode(errors="replace")
                + result.stderr.decode(errors="replace")
            )
        if data_dir.exists() or not backup_path.is_file():
            raise PlayerPackageSmokeError(
                "Packaged export-and-remove did not preserve its data boundary"
            )
        with zipfile.ZipFile(backup_path) as backup:
            if "manifest.json" not in backup.namelist():
                raise PlayerPackageSmokeError(
                    "Packaged export-and-remove produced an invalid backup"
                )

    print(f"Player runtime archive passed: {archive_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, PlayerPackageSmokeError, tarfile.TarError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
