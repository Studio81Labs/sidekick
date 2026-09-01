#!/usr/bin/env python3
"""Verify and exercise an extracted player runtime archive without a checkout."""

from __future__ import annotations

import argparse
from hashlib import sha256
from ipaddress import ip_address
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
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PLAYER_ORIGIN = "http://127.0.0.1:8765"
PLAYER_AUTHORITY = "127.0.0.1:8765"
PLAYER_WORKSPACE_MANIFEST = ".poker-hero-player-workspace.json"
LAUNCH_CAPTURE_HELPER = ROOT / "scripts" / "capture-player-launch-url.sh"


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
    python_parts = python_version.split(".")
    host_python_parts = platform.python_version().split(".")
    if python_parts[:2] != host_python_parts[:2]:
        raise PlayerPackageSmokeError(
            "Runtime bundle Python ABI does not match the smoke-test host"
        )
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


def _request_url(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    request_headers = {"Host": PLAYER_AUTHORITY}
    if headers is not None:
        request_headers.update(headers)
    request = Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=1) as response:
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


def _request(
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    return _request_url(
        f"{PLAYER_ORIGIN}{path}",
        method=method,
        headers=headers,
        body=body,
    )


def _require_response(
    response: tuple[int, bytes, dict[str, str]],
    *,
    status: int,
    description: str,
) -> bytes:
    actual_status, body, headers = response
    if actual_status != status:
        raise PlayerPackageSmokeError(
            f"{description} returned HTTP {actual_status}, expected {status}"
        )
    if headers.get("cache-control") != "no-store":
        raise PlayerPackageSmokeError(f"{description} did not preserve no-store")
    return body


def _decode_json_object(body: bytes, *, description: str) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PlayerPackageSmokeError(f"{description} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise PlayerPackageSmokeError(f"{description} did not return an object")
    return value


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


def _wait_for_launch_ticket(capture_path: Path) -> str:
    deadline = monotonic() + 5
    while not capture_path.exists() and monotonic() < deadline:
        sleep(0.05)
    if capture_path.is_symlink():
        raise PlayerPackageSmokeError("Player launch URL capture is a symlink")
    try:
        metadata = capture_path.stat()
    except FileNotFoundError as exc:
        raise PlayerPackageSmokeError(
            "Packaged runtime did not invoke the browser capture helper"
        ) from exc
    if not S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
        raise PlayerPackageSmokeError("Player launch URL capture is not private")
    if metadata.st_size > 1024:
        raise PlayerPackageSmokeError("Player launch URL capture is oversized")
    try:
        launch_url = capture_path.read_text(encoding="utf-8").strip()
    finally:
        capture_path.unlink(missing_ok=True)
    parsed = urlsplit(launch_url)
    fragment_name, separator, ticket = parsed.fragment.partition("=")
    if (
        parsed.scheme != "http"
        or parsed.netloc != PLAYER_AUTHORITY
        or parsed.path != "/"
        or parsed.query
        or fragment_name != "ticket"
        or separator != "="
        or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", ticket) is None
    ):
        raise PlayerPackageSmokeError("Packaged runtime launch URL is invalid")
    return ticket


def _non_loopback_ipv4() -> str | None:
    candidates: set[str] = set()
    try:
        candidates.update(
            address[4][0]
            for address in socket.getaddrinfo(
                socket.gethostname(),
                None,
                family=socket.AF_INET,
            )
        )
    except OSError:
        pass
    route_probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        route_probe.connect(("192.0.2.1", 9))
        candidates.add(route_probe.getsockname()[0])
    except OSError:
        pass
    finally:
        route_probe.close()
    return next(
        (
            candidate
            for candidate in sorted(candidates)
            if not ip_address(candidate).is_loopback
        ),
        None,
    )


def _require_lan_refusal() -> None:
    lan_address = _non_loopback_ipv4()
    if lan_address is None:
        if platform.system() == "Linux":
            raise PlayerPackageSmokeError(
                "Linux bundle smoke requires a non-loopback IPv4 address"
            )
        print(
            "SKIP: no non-loopback IPv4 interface is available for LAN refusal",
            file=sys.stderr,
        )
        return
    try:
        response = _request_url(f"http://{lan_address}:8765/")
    except (OSError, URLError):
        return
    raise PlayerPackageSmokeError(
        "Packaged runtime accepted a direct LAN request "
        f"with HTTP {response[0]}"
    )


def _exercise_runtime_security(ticket: str) -> None:
    _require_response(
        _request("/", headers={"Host": "localhost:8765"}),
        status=400,
        description="Wrong-Host request",
    )
    _require_response(
        _request("/", headers={"Origin": "https://attacker.example"}),
        status=403,
        description="Cross-origin request",
    )
    _require_response(
        _request("/", headers={"X-Forwarded-For": "127.0.0.1"}),
        status=400,
        description="Proxy-header request",
    )

    exchange_headers = {
        "Authorization": f"Bearer {ticket}",
        "Origin": PLAYER_ORIGIN,
    }
    session_body = _require_response(
        _request(
            "/api/player/session",
            method="POST",
            headers=exchange_headers,
            body=b"",
        ),
        status=200,
        description="Bootstrap ticket exchange",
    )
    session = _decode_json_object(
        session_body,
        description="Bootstrap ticket exchange",
    )
    if (
        set(session) != {"csrf_token", "expires_in_seconds", "session_token"}
        or not isinstance(session.get("session_token"), str)
        or not session["session_token"]
        or not isinstance(session.get("csrf_token"), str)
        or not session["csrf_token"]
        or session.get("expires_in_seconds") != 86400
    ):
        raise PlayerPackageSmokeError(
            "Bootstrap ticket exchange returned an invalid session"
        )
    _require_response(
        _request(
            "/api/player/session",
            method="POST",
            headers=exchange_headers,
            body=b"",
        ),
        status=401,
        description="Bootstrap ticket replay",
    )

    session_headers = {"Authorization": f"Bearer {session['session_token']}"}
    _require_response(
        _request("/api/player/storage"),
        status=401,
        description="Missing-session storage request",
    )
    _require_response(
        _request(
            "/api/player/storage",
            headers={"Authorization": "Bearer forged-session"},
        ),
        status=401,
        description="Forged-session storage request",
    )
    _require_response(
        _request("/api/player/storage", headers=session_headers),
        status=200,
        description="Authenticated storage request",
    )
    health_body = _require_response(
        _request("/api/player/health", headers=session_headers),
        status=200,
        description="Authenticated health request",
    )
    if _decode_json_object(
        health_body,
        description="Authenticated health request",
    ) != {"runtime": "local-player", "status": "ok"}:
        raise PlayerPackageSmokeError(
            "Authenticated health request returned the wrong runtime identity"
        )

    mutation_headers = {**session_headers, "Origin": PLAYER_ORIGIN}
    _require_response(
        _request(
            "/api/player/session",
            method="DELETE",
            headers=mutation_headers,
        ),
        status=403,
        description="Missing-CSRF session mutation",
    )
    _require_response(
        _request(
            "/api/player/session",
            method="DELETE",
            headers={**mutation_headers, "X-Poker-CSRF-Token": "forged-csrf"},
        ),
        status=403,
        description="Forged-CSRF session mutation",
    )
    revoked_body = _require_response(
        _request(
            "/api/player/session",
            method="DELETE",
            headers={
                **mutation_headers,
                "X-Poker-CSRF-Token": str(session["csrf_token"]),
            },
        ),
        status=204,
        description="Authenticated session revocation",
    )
    if revoked_body:
        raise PlayerPackageSmokeError(
            "Authenticated session revocation returned an unexpected body"
        )
    _require_response(
        _request("/api/player/health", headers=session_headers),
        status=401,
        description="Revoked-session health request",
    )
    _require_lan_refusal()


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

    if (
        LAUNCH_CAPTURE_HELPER.is_symlink()
        or not LAUNCH_CAPTURE_HELPER.is_file()
        or not os.access(LAUNCH_CAPTURE_HELPER, os.X_OK)
    ):
        raise PlayerPackageSmokeError(
            "The player launch URL capture helper is missing"
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
        capture_dir = temporary / "browser-capture"
        capture_dir.mkdir(mode=0o700)
        launch_capture_path = capture_dir / "launch-url"
        environment = {
            "BROWSER": str(LAUNCH_CAPTURE_HELPER),
            "PATH": os.pathsep.join(("/usr/bin", "/bin")),
            "POKER_DATA_DIR": str(data_dir),
            "POKER_DEPLOYMENT_ENVIRONMENT": "local",
            "POKER_HERO_PLAYER_LAUNCH_URL_FILE": str(launch_capture_path),
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
            ticket = _wait_for_launch_ticket(launch_capture_path)
            _exercise_runtime_security(ticket)
        finally:
            launch_capture_path.unlink(missing_ok=True)
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
