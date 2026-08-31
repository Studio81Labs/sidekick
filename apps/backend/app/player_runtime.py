from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import hmac
from ipaddress import ip_address
from mimetypes import guess_type
import os
from pathlib import Path
import secrets
from stat import S_ISREG
from threading import Lock
from time import monotonic
from types import MappingProxyType
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.data_lock import (
    DEFAULT_DATA_LOCK_EXPORT_TIMEOUT_SECONDS,
    DEFAULT_DATA_LOCK_SHARED_TIMEOUT_SECONDS,
    DEFAULT_DATA_LOCK_TIMEOUT_SECONDS,
    DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS,
    DataLockTimeoutError,
)
from app.player_backup import (
    DEFAULT_MAX_PLAYER_BACKUP_BYTES,
    PlayerBackupError,
    build_player_backup_archive,
    restore_player_backup,
    stream_player_backup,
)
from app.player_namespace import (
    PLAYER_API_PREFIX,
    is_player_api_scope,
)
from app.player_workspace import PlayerWorkspace


PLAYER_HOST = "127.0.0.1"
PLAYER_PORT = 8765
PLAYER_AUTHORITY = f"{PLAYER_HOST}:{PLAYER_PORT}"
PLAYER_ORIGIN = f"http://{PLAYER_AUTHORITY}"
PLAYER_SECRET_FILENAME = ".player-runtime-key"
DEFAULT_PLAYER_ASSETS_DIR = (
    Path(__file__).resolve().parents[2] / "pwa" / "dist-player"
)
REQUIRED_PLAYER_ASSETS = (
    "index.html",
    "manifest.webmanifest",
    "sw.js",
)
REQUIRED_PLAYER_ASSET_DIRECTORIES = ("assets", "icons")
BOOTSTRAP_TTL_SECONDS = 120
SESSION_TTL_SECONDS = 24 * 60 * 60
MUTATING_METHODS = frozenset({"DELETE", "PATCH", "POST", "PUT"})
PROXY_HEADERS = frozenset(
    {
        b"forwarded",
        b"x-forwarded-for",
        b"x-forwarded-host",
        b"x-forwarded-port",
        b"x-forwarded-proto",
    }
)


class PlayerCredentialError(RuntimeError):
    pass


class PlayerAssetError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlayerAssetBundle:
    document: bytes
    manifest: bytes
    service_worker: bytes
    public_files: Mapping[str, bytes]


def _read_player_asset(root: Path, asset: Path, relative_path: str) -> bytes:
    if asset.is_symlink():
        raise PlayerAssetError(
            f"The player PWA asset {relative_path} must not be a symlink"
        )
    try:
        resolved_asset = asset.resolve(strict=True)
    except OSError as exc:
        raise PlayerAssetError(
            f"The player PWA is missing {relative_path}; run pnpm player:build"
        ) from exc
    if not resolved_asset.is_relative_to(root) or not resolved_asset.is_file():
        raise PlayerAssetError(
            f"The player PWA asset {relative_path} must be a regular file"
        )
    try:
        return resolved_asset.read_bytes()
    except OSError as exc:
        raise PlayerAssetError(
            f"The player PWA asset {relative_path} could not be read"
        ) from exc


def _load_player_asset_directory(
    root: Path,
    directory: Path,
    relative_directory: str,
) -> dict[str, bytes]:
    if directory.is_symlink() or not directory.is_dir():
        raise PlayerAssetError(
            f"The player PWA is missing its {relative_directory} directory; "
            "run pnpm player:build"
        )
    loaded: dict[str, bytes] = {}
    try:
        entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
    except OSError as exc:
        raise PlayerAssetError(
            f"The player PWA {relative_directory} directory could not be read"
        ) from exc
    for entry in entries:
        relative_path = entry.relative_to(root).as_posix()
        if entry.is_symlink():
            raise PlayerAssetError(
                f"The player PWA asset {relative_path} must not be a symlink"
            )
        if entry.is_dir():
            loaded.update(_load_player_asset_directory(root, entry, relative_path))
            continue
        loaded[relative_path] = _read_player_asset(root, entry, relative_path)
    return loaded


def validate_player_assets(player_assets_dir: Path) -> PlayerAssetBundle:
    candidate_root = Path(player_assets_dir)
    if candidate_root.is_symlink():
        raise PlayerAssetError("The player PWA directory must not be a symlink")
    try:
        root = candidate_root.resolve(strict=True)
    except OSError as exc:
        raise PlayerAssetError(
            "The player PWA has not been built; run pnpm player:build"
        ) from exc
    if not root.is_dir():
        raise PlayerAssetError("The player PWA path must be a directory")
    root_files = {
        relative_path: _read_player_asset(root, root / relative_path, relative_path)
        for relative_path in REQUIRED_PLAYER_ASSETS
    }
    public_files: dict[str, bytes] = {}
    for relative_path in REQUIRED_PLAYER_ASSET_DIRECTORIES:
        public_files.update(
            _load_player_asset_directory(root, root / relative_path, relative_path)
        )
    return PlayerAssetBundle(
        document=root_files["index.html"],
        manifest=root_files["manifest.webmanifest"],
        service_worker=root_files["sw.js"],
        public_files=MappingProxyType(public_files),
    )


def load_or_create_installation_secret(data_dir: Path) -> bytes:
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    secret_path = data_dir / PLAYER_SECRET_FILENAME
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(secret_path, flags)
    except FileNotFoundError:
        create_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            create_flags |= os.O_NOFOLLOW
        secret = secrets.token_bytes(32)
        try:
            descriptor = os.open(secret_path, create_flags, 0o600)
        except FileExistsError:
            return load_or_create_installation_secret(data_dir)
        try:
            written = 0
            while written < len(secret):
                written += os.write(descriptor, secret[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return secret
    except OSError as exc:
        raise PlayerCredentialError(
            f"Cannot safely open the player installation credential: {exc}"
        ) from exc

    try:
        file_stat = os.fstat(descriptor)
        if not S_ISREG(file_stat.st_mode):
            raise PlayerCredentialError(
                "The player installation credential must be a regular file"
            )
        if file_stat.st_mode & 0o077:
            raise PlayerCredentialError(
                "The player installation credential must be readable only by its owner"
            )
        if hasattr(os, "getuid") and file_stat.st_uid != os.getuid():
            raise PlayerCredentialError(
                "The player installation credential must be owned by the current user"
            )
        secret = os.read(descriptor, 33)
    finally:
        os.close(descriptor)
    if len(secret) != 32:
        raise PlayerCredentialError(
            "The player installation credential must contain exactly 32 bytes"
        )
    return secret


@dataclass(frozen=True)
class PlayerSession:
    session_token: str
    csrf_token: str
    expires_in_seconds: int


class PlayerSessionAuthority:
    def __init__(
        self,
        installation_secret: bytes,
        *,
        clock: Callable[[], float] = monotonic,
        bootstrap_ttl_seconds: int = BOOTSTRAP_TTL_SECONDS,
        session_ttl_seconds: int = SESSION_TTL_SECONDS,
    ) -> None:
        if len(installation_secret) != 32:
            raise ValueError("installation_secret must contain exactly 32 bytes")
        self._secret = installation_secret
        self._clock = clock
        self._bootstrap_ttl_seconds = bootstrap_ttl_seconds
        self._session_ttl_seconds = session_ttl_seconds
        self._bootstrap_tickets: dict[bytes, float] = {}
        self._sessions: dict[bytes, tuple[bytes, float]] = {}
        self._lock = Lock()

    def _digest(self, kind: str, token: str) -> bytes:
        return hmac.new(
            self._secret,
            f"{kind}:{token}".encode("utf-8"),
            sha256,
        ).digest()

    def issue_bootstrap_ticket(self) -> str:
        ticket = secrets.token_urlsafe(32)
        with self._lock:
            self._bootstrap_tickets[self._digest("bootstrap", ticket)] = (
                self._clock() + self._bootstrap_ttl_seconds
            )
        return ticket

    def exchange_bootstrap_ticket(self, ticket: str) -> PlayerSession | None:
        now = self._clock()
        with self._lock:
            expires_at = self._bootstrap_tickets.pop(
                self._digest("bootstrap", ticket),
                None,
            )
            if expires_at is None or expires_at <= now:
                return None
            session_token = secrets.token_urlsafe(32)
            csrf_token = secrets.token_urlsafe(32)
            self._sessions[self._digest("session", session_token)] = (
                self._digest("csrf", csrf_token),
                now + self._session_ttl_seconds,
            )
        return PlayerSession(
            session_token=session_token,
            csrf_token=csrf_token,
            expires_in_seconds=self._session_ttl_seconds,
        )

    def authorize(self, session_token: str) -> bool:
        digest = self._digest("session", session_token)
        with self._lock:
            session = self._sessions.get(digest)
            if session is None:
                return False
            _csrf_digest, expires_at = session
            if expires_at <= self._clock():
                self._sessions.pop(digest, None)
                return False
            return True

    def authorize_mutation(self, session_token: str, csrf_token: str) -> bool:
        session_digest = self._digest("session", session_token)
        with self._lock:
            session = self._sessions.get(session_digest)
            if session is None:
                return False
            expected_csrf_digest, expires_at = session
            if expires_at <= self._clock():
                self._sessions.pop(session_digest, None)
                return False
            return hmac.compare_digest(
                self._digest("csrf", csrf_token),
                expected_csrf_digest,
            )

    def revoke(self, session_token: str) -> bool:
        with self._lock:
            return self._sessions.pop(
                self._digest("session", session_token),
                None,
            ) is not None


def _header_values(scope: Scope, name: bytes) -> list[str]:
    values: list[str] = []
    for header_name, value in scope.get("headers", []):
        if header_name.lower() != name:
            continue
        try:
            values.append(value.decode("ascii"))
        except UnicodeDecodeError:
            values.append("")
    return values


def _json_denial(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(
        {"detail": detail},
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


async def _read_bounded_body(request: Request, *, limit: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise PlayerBackupError("Content-Length must be a decimal integer") from exc
        if declared_length < 0 or declared_length > limit:
            raise PlayerBackupError(
                f"Player backup exceeds the configured {limit}-byte limit"
            )
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise PlayerBackupError(
                f"Player backup exceeds the configured {limit}-byte limit"
            )
    return bytes(body)


class PlayerNetworkBoundaryMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        authority: str = PLAYER_AUTHORITY,
        origin: str = PLAYER_ORIGIN,
    ) -> None:
        self.app = app
        self.authority = authority
        self.origin = origin

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        try:
            loopback_peer = client is not None and ip_address(client[0]).is_loopback
        except ValueError:
            loopback_peer = False
        if not loopback_peer:
            await _json_denial(403, "Forbidden")(scope, receive, send)
            return

        hosts = _header_values(scope, b"host")
        if len(hosts) != 1 or hosts[0].lower() != self.authority:
            await _json_denial(400, "Invalid Host header")(scope, receive, send)
            return
        if any(
            header_name.lower() in PROXY_HEADERS
            for header_name, _value in scope.get("headers", [])
        ):
            await _json_denial(400, "Proxy headers are not accepted")(
                scope,
                receive,
                send,
            )
            return

        origins = _header_values(scope, b"origin")
        if len(origins) > 1 or (origins and origins[0] != self.origin):
            await _json_denial(403, "Origin is not allowed")(
                scope,
                receive,
                send,
            )
            return
        if (
            scope.get("method", "").upper() in MUTATING_METHODS
            and scope.get("path", "").startswith(PLAYER_API_PREFIX)
            and origins != [self.origin]
        ):
            await _json_denial(403, "Origin is required")(
                scope,
                receive,
                send,
            )
            return
        await self.app(scope, receive, send)


class PlayerResponsePolicyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        async def send_with_policy(message: Message) -> None:
            if message["type"] == "http.response.start":
                policy_header_names = {
                    b"cache-control",
                    b"content-security-policy",
                    b"referrer-policy",
                    b"x-content-type-options",
                    b"x-frame-options",
                }
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() not in policy_header_names
                ]
                headers.extend(
                    [
                        (b"cache-control", b"no-store"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; base-uri 'none'; connect-src 'self'; "
                            b"frame-ancestors 'none'; form-action 'none'; "
                            b"object-src 'none'; script-src 'self'; style-src 'self'",
                        ),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_policy)


def _bearer_token_from_scope(scope: Scope) -> str:
    authorization_values = _header_values(scope, b"authorization")
    if len(authorization_values) != 1:
        return ""
    authorization = authorization_values[0]
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token or " " in token:
        return ""
    return token


class PlayerApiSessionMiddleware:
    def __init__(self, app: ASGIApp, sessions: PlayerSessionAuthority) -> None:
        self.app = app
        self.sessions = sessions

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http" or not is_player_api_scope(scope):
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "").upper()
        path = scope.get("path", "")
        if method == "POST" and path == f"{PLAYER_API_PREFIX}/session":
            await self.app(scope, receive, send)
            return

        session_token = _bearer_token_from_scope(scope)
        if not self.sessions.authorize(session_token):
            await _json_denial(401, "Unauthorized")(scope, receive, send)
            return
        if method in MUTATING_METHODS:
            csrf_values = _header_values(scope, b"x-poker-csrf-token")
            csrf_token = csrf_values[0] if len(csrf_values) == 1 else ""
            if not self.sessions.authorize_mutation(session_token, csrf_token):
                await _json_denial(403, "CSRF validation failed")(
                    scope,
                    receive,
                    send,
                )
                return
        scope.setdefault("state", {})["player_session_token"] = session_token
        await self.app(scope, receive, send)


@dataclass(frozen=True)
class PlayerRuntime:
    app: ASGIApp
    api_application: FastAPI
    sessions: PlayerSessionAuthority
    workspace: PlayerWorkspace
    origin: str = PLAYER_ORIGIN

    def issue_launch_url(self) -> str:
        ticket = self.sessions.issue_bootstrap_ticket()
        return f"{self.origin}/#ticket={ticket}"


def _player_public_asset_response(
    bundle: PlayerAssetBundle,
    namespace: str,
    asset_path: str,
) -> Response:
    content = bundle.public_files.get(f"{namespace}/{asset_path}")
    if content is None:
        return Response(status_code=404)
    media_type, _encoding = guess_type(asset_path)
    return Response(
        content,
        media_type=media_type or "application/octet-stream",
    )


def create_player_runtime(
    data_dir: Path,
    *,
    player_assets_dir: Path = DEFAULT_PLAYER_ASSETS_DIR,
    authority: str = PLAYER_AUTHORITY,
    origin: str = PLAYER_ORIGIN,
    clock: Callable[[], float] = monotonic,
    recovery_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_TIMEOUT_SECONDS,
    startup_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_SHARED_TIMEOUT_SECONDS,
    write_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS,
    backup_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_EXPORT_TIMEOUT_SECONDS,
    status_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_SHARED_TIMEOUT_SECONDS,
    max_player_backup_bytes: int = DEFAULT_MAX_PLAYER_BACKUP_BYTES,
) -> PlayerRuntime:
    player_assets = validate_player_assets(player_assets_dir)
    workspace = PlayerWorkspace.open(
        data_dir,
        recovery_lock_timeout_seconds=recovery_lock_timeout_seconds,
        startup_lock_timeout_seconds=startup_lock_timeout_seconds,
        write_lock_timeout_seconds=write_lock_timeout_seconds,
    )
    sessions = PlayerSessionAuthority(
        load_or_create_installation_secret(workspace.data_dir),
        clock=clock,
    )
    restore_status_gate = Lock()
    app = FastAPI(
        title="Poker Hero Local Player Runtime",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/")
    async def player_shell() -> Response:
        return Response(player_assets.document, media_type="text/html")

    @app.get("/manifest.webmanifest")
    async def player_manifest() -> Response:
        return Response(
            player_assets.manifest,
            media_type="application/manifest+json",
        )

    @app.get("/sw.js")
    async def player_service_worker() -> Response:
        return Response(
            player_assets.service_worker,
            media_type="text/javascript",
        )

    @app.post(f"{PLAYER_API_PREFIX}/session")
    async def exchange_session(request: Request) -> JSONResponse:
        session = sessions.exchange_bootstrap_ticket(
            _bearer_token_from_scope(request.scope)
        )
        if session is None:
            return _json_denial(401, "Unauthorized")
        return JSONResponse(
            {
                "session_token": session.session_token,
                "csrf_token": session.csrf_token,
                "expires_in_seconds": session.expires_in_seconds,
            }
        )

    @app.get(f"{PLAYER_API_PREFIX}/health")
    async def player_health() -> JSONResponse:
        return JSONResponse({"status": "ok", "runtime": "local-player"})

    @app.get(f"{PLAYER_API_PREFIX}/storage")
    async def player_storage() -> JSONResponse:
        def stable_status_payload() -> dict[str, object]:
            # The local gate covers request-body reading and archive parsing,
            # before restore_player_backup takes the cross-process exclusive
            # lock. The shared data lock inside status_payload then protects
            # the filesystem snapshot itself.
            with restore_status_gate:
                return workspace.status_payload(
                    lock_timeout_seconds=status_lock_timeout_seconds,
                )

        try:
            payload = await run_in_threadpool(stable_status_payload)
        except DataLockTimeoutError as exc:
            return _json_denial(409, str(exc))
        return JSONResponse(payload)

    @app.get(f"{PLAYER_API_PREFIX}/backups/export")
    async def export_player_backup() -> Response:
        try:
            archive_file = await run_in_threadpool(
                build_player_backup_archive,
                workspace,
                max_archive_bytes=max_player_backup_bytes,
                lock_timeout_seconds=backup_lock_timeout_seconds,
            )
        except PlayerBackupError as exc:
            return _json_denial(exc.status_code, str(exc))
        except DataLockTimeoutError as exc:
            return _json_denial(409, str(exc))
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return StreamingResponse(
            stream_player_backup(archive_file),
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    "attachment; filename=\"poker-hero-player-backup-"
                    f"{timestamp}.zip\""
                )
            },
        )

    @app.post(f"{PLAYER_API_PREFIX}/backups/restore")
    async def restore_uploaded_player_backup(request: Request) -> JSONResponse:
        # Acquire without yielding when no restore is active. A status request
        # that follows a lost response will then wait from the start of body
        # handling until the restore has either committed or failed.
        if not restore_status_gate.acquire(blocking=False):
            return _json_denial(409, "Another player restore is already in progress")
        try:
            media_type = request.headers.get("content-type", "").partition(";")[0]
            if media_type.strip().lower() not in {
                "application/zip",
                "application/octet-stream",
            }:
                return _json_denial(415, "Upload must be a player backup ZIP")
            try:
                archive_bytes = await _read_bounded_body(
                    request,
                    limit=max_player_backup_bytes,
                )
                result = await run_in_threadpool(
                    restore_player_backup,
                    workspace,
                    archive_bytes,
                    max_archive_bytes=max_player_backup_bytes,
                    lock_timeout_seconds=backup_lock_timeout_seconds,
                )
            except PlayerBackupError as exc:
                return _json_denial(exc.status_code, str(exc))
            except DataLockTimeoutError as exc:
                return _json_denial(409, str(exc))
        finally:
            restore_status_gate.release()
        return JSONResponse(result.model_dump(mode="json"))

    @app.delete(f"{PLAYER_API_PREFIX}/session")
    async def revoke_session(request: Request) -> Response:
        session_token = request.state.player_session_token
        sessions.revoke(session_token)
        return Response(status_code=204)

    @app.get("/assets/{asset_path:path}")
    async def player_application_asset(asset_path: str) -> Response:
        return _player_public_asset_response(player_assets, "assets", asset_path)

    @app.get("/icons/{asset_path:path}")
    async def player_icon(asset_path: str) -> Response:
        return _player_public_asset_response(player_assets, "icons", asset_path)

    secured_app: ASGIApp = PlayerApiSessionMiddleware(app, sessions)
    secured_app = PlayerNetworkBoundaryMiddleware(
        secured_app,
        authority=authority,
        origin=origin,
    )
    secured_app = PlayerResponsePolicyMiddleware(secured_app)
    return PlayerRuntime(
        app=secured_app,
        api_application=app,
        sessions=sessions,
        workspace=workspace,
        origin=origin,
    )
