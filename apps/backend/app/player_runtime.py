from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
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
import sys
from threading import Lock
from time import monotonic
from types import MappingProxyType
from typing import Callable

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.application.imported_hand_lifecycle import LifecycleCascadeError
from app.data_lock import (
    DEFAULT_DATA_LOCK_EXPORT_TIMEOUT_SECONDS,
    DEFAULT_DATA_LOCK_SHARED_TIMEOUT_SECONDS,
    DEFAULT_DATA_LOCK_TIMEOUT_SECONDS,
    DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS,
    DataLockError,
    DataLockTimeoutError,
)
from app.domain.remote_references import RemoteReferenceProviderPolicy
from app.player_backup import (
    DEFAULT_MAX_PLAYER_BACKUP_BYTES,
    PlayerBackupError,
    PlayerBackupStorageError,
    build_player_backup_archive,
    restore_player_backup,
    stream_player_backup,
)
from app.player_hands import (
    DEFAULT_PLAYER_HAND_PAGE_SIZE,
    MAX_PLAYER_HAND_PAGE_SIZE,
    PlayerHandApprovalRequest,
    PlayerHandCloseAction,
    PlayerHandCloseRequest,
    PlayerHandConflictResolutionRequest,
    PlayerHandDeleteRequest,
    PlayerHandReimportRequest,
    PlayerRequestId,
)
from app.player_imports import (
    MAX_PLAYER_IMPORT_BATCH_BYTES,
    MAX_PLAYER_IMPORT_FILE_BYTES,
    MAX_PLAYER_IMPORT_FILES,
    PlayerImportFile,
    PlayerImportFileOutcome,
    import_pokerstars_files,
    rejected_player_import_file,
)
from app.player_namespace import (
    PLAYER_API_PREFIX,
    is_player_api_scope,
)
from app.player_remote_references import (
    PlayerRemoteReferenceConsentConflict,
    PlayerRemoteReferenceConsentRequest,
    PlayerRemoteReferenceRevokeRequest,
)
from app.player_reimports import reimport_pokerstars_hand
from app.player_workspace import (
    PlayerDataDirectoryError,
    PlayerHandApprovalInvalid,
    PlayerHandConflictResolutionInvalid,
    PlayerHandDecisionsUnavailable,
    PlayerHandRecoveryRequired,
    PlayerHandReimportInvalid,
    PlayerHandTransitionConflict,
    PlayerStorageRecoveryRequired,
    PlayerWorkspace,
)
from app.storage.cascade_journal import PendingCascadeError
from app.storage.imported_hand_store import (
    DecisionArtifactIntegrityError,
    ImportedHandNotFoundError,
)
from app.storage.remote_reference_consent_store import (
    RemoteReferenceConsentStorageError,
)


PLAYER_HOST = "127.0.0.1"
PLAYER_PORT = 8765
PLAYER_AUTHORITY = f"{PLAYER_HOST}:{PLAYER_PORT}"
PLAYER_ORIGIN = f"http://{PLAYER_AUTHORITY}"
PLAYER_SECRET_FILENAME = ".player-runtime-key"
PLAYER_IMPORT_MULTIPART_OVERHEAD_BYTES = 256 * 1024


def default_player_assets_dir() -> Path:
    """Locate verified player assets in a source tree or frozen runtime bundle."""

    frozen_root = getattr(sys, "_MEIPASS", None)
    if isinstance(frozen_root, (str, os.PathLike)):
        return Path(frozen_root) / "player-assets"
    return Path(__file__).resolve().parents[2] / "pwa" / "dist-player"


DEFAULT_PLAYER_ASSETS_DIR = default_player_assets_dir()
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


class _RestoreAccessGate:
    """Exclude restores without serializing ordinary player operations."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._active_operations = 0
        self._active_restore = False
        self._waiting_restores = 0

    @asynccontextmanager
    async def operation(self) -> AsyncIterator[None]:
        async with self._condition:
            await self._condition.wait_for(
                lambda: not self._active_restore and self._waiting_restores == 0
            )
            self._active_operations += 1
        try:
            yield
        finally:
            async with self._condition:
                self._active_operations -= 1
                if self._active_operations == 0:
                    self._condition.notify_all()

    @asynccontextmanager
    async def restore(self) -> AsyncIterator[None]:
        acquired = False
        async with self._condition:
            self._waiting_restores += 1
            try:
                await self._condition.wait_for(
                    lambda: not self._active_restore
                    and self._active_operations == 0
                )
                self._active_restore = True
                acquired = True
            finally:
                self._waiting_restores -= 1
                if not acquired:
                    self._condition.notify_all()
        try:
            yield
        finally:
            async with self._condition:
                self._active_restore = False
                self._condition.notify_all()


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
        self._disabled_until_restart = False
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
            if self._disabled_until_restart:
                raise PlayerCredentialError(
                    "Player recovery requires a local runtime restart"
                )
            self._bootstrap_tickets[self._digest("bootstrap", ticket)] = (
                self._clock() + self._bootstrap_ttl_seconds
            )
        return ticket

    def exchange_bootstrap_ticket(self, ticket: str) -> PlayerSession | None:
        now = self._clock()
        with self._lock:
            if self._disabled_until_restart:
                return None
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
            if self._disabled_until_restart:
                return False
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
            if self._disabled_until_restart:
                return False
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

    def disable_until_restart(self) -> None:
        with self._lock:
            self._disabled_until_restart = True
            self._bootstrap_tickets.clear()
            self._sessions.clear()


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


def _valid_player_import_filename(filename: str) -> bool:
    return (
        bool(filename)
        and filename == filename.strip()
        and len(filename) <= 255
        and filename.lower().endswith(".txt")
        and "/" not in filename
        and "\\" not in filename
        and "\x00" not in filename
        and not (len(filename) >= 2 and filename[1] == ":")
    )


def _is_player_import_upload_path(path: str) -> bool:
    if path == f"{PLAYER_API_PREFIX}/imports":
        return True
    prefix = f"{PLAYER_API_PREFIX}/hands/"
    return path.startswith(prefix) and path.endswith("/reimport")


class PlayerImportBodyLimitMiddleware:
    """Bound the raw multipart body before Starlette can spool file parts."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limit: int,
        reimport_limit: int | None = None,
    ) -> None:
        self.app = app
        self.limit = limit
        self.reimport_limit = reimport_limit if reimport_limit is not None else limit

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if not (
            scope["type"] == "http"
            and scope.get("method", "").upper() == "POST"
            and _is_player_import_upload_path(scope.get("path", ""))
        ):
            await self.app(scope, receive, send)
            return

        body_limit = (
            self.reimport_limit
            if scope.get("path", "").endswith("/reimport")
            else self.limit
        )
        content_lengths = _header_values(scope, b"content-length")
        if len(content_lengths) > 1:
            await _json_denial(400, "Content-Length must be unambiguous")(
                scope,
                receive,
                send,
            )
            return
        if content_lengths:
            try:
                declared_length = int(content_lengths[0])
            except ValueError:
                declared_length = -1
            if declared_length < 0:
                await _json_denial(400, "Content-Length must be a decimal integer")(
                    scope,
                    receive,
                    send,
                )
                return
            if declared_length > body_limit:
                await _json_denial(413, "The player import body is too large")(
                    scope,
                    receive,
                    send,
                )
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            if len(chunk) > body_limit - len(body):
                await _json_denial(413, "The player import body is too large")(
                    scope,
                    receive,
                    send,
                )
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay_receive() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {
                "type": "http.request",
                "body": bytes(body),
                "more_body": False,
            }

        await self.app(scope, replay_receive, send)


async def _read_player_import_files(
    files: list[UploadFile],
    *,
    max_player_import_file_bytes: int,
    max_player_import_batch_bytes: int,
) -> list[PlayerImportFile | PlayerImportFileOutcome] | JSONResponse:
    if not files:
        return _json_denial(400, "Select at least one PokerStars text file")
    declared_batch_size = sum(
        upload.size for upload in files if upload.size is not None
    )
    if declared_batch_size > max_player_import_batch_bytes:
        return _json_denial(
            413,
            "The selected PokerStars files exceed the import batch limit",
        )

    sources: list[PlayerImportFile | PlayerImportFileOutcome] = []
    batch_size = 0
    for slot, upload in enumerate(files, start=1):
        raw_filename = upload.filename or ""
        filename = (
            raw_filename
            if _valid_player_import_filename(raw_filename)
            else f"file-{slot}.txt"
        )
        media_type = (
            (upload.content_type or "").partition(";")[0].strip().lower()
        )
        payload = await upload.read(max_player_import_file_bytes + 1)
        batch_size += len(payload)
        if batch_size > max_player_import_batch_bytes:
            return _json_denial(
                413,
                "The selected PokerStars files exceed the import batch limit",
            )
        if not _valid_player_import_filename(raw_filename):
            sources.append(
                rejected_player_import_file(
                    slot,
                    filename,
                    code="invalid_filename",
                    message=(
                        "PokerStars imports require a plain .txt filename"
                        " without a directory path."
                    ),
                )
            )
            continue
        if media_type not in {
            "",
            "application/octet-stream",
            "text/plain",
        }:
            sources.append(
                rejected_player_import_file(
                    slot,
                    filename,
                    code="unsupported_media_type",
                    message="PokerStars imports must be plain text files.",
                )
            )
            continue
        if len(payload) > max_player_import_file_bytes:
            sources.append(
                rejected_player_import_file(
                    slot,
                    filename,
                    code="file_too_large",
                    message=(
                        "This PokerStars file exceeds the local import size limit."
                    ),
                )
            )
            continue
        try:
            raw_text = payload.decode("utf-8")
        except UnicodeDecodeError:
            sources.append(
                rejected_player_import_file(
                    slot,
                    filename,
                    code="invalid_encoding",
                    message="PokerStars imports must use UTF-8 text.",
                )
            )
            continue
        sources.append(
            PlayerImportFile(
                slot=slot,
                filename=filename,
                content_sha256=sha256(payload).hexdigest(),
                raw_text=raw_text,
            )
        )
    return sources


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
    max_player_import_file_bytes: int = MAX_PLAYER_IMPORT_FILE_BYTES,
    max_player_import_batch_bytes: int = MAX_PLAYER_IMPORT_BATCH_BYTES,
    max_player_import_files: int = MAX_PLAYER_IMPORT_FILES,
    remote_reference_provider_policy: RemoteReferenceProviderPolicy | None = None,
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
    restore_access_gate = _RestoreAccessGate()
    restore_in_progress = False
    provider_policy = (
        None
        if remote_reference_provider_policy is None
        else RemoteReferenceProviderPolicy.model_validate(
            remote_reference_provider_policy.model_dump(mode="python")
        )
    )
    app = FastAPI(
        title="Poker Hero Local Player Runtime",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(PlayerDataDirectoryError)
    async def incompatible_player_workspace(
        _request: Request,
        exc: PlayerDataDirectoryError,
    ) -> JSONResponse:
        return _json_denial(503, str(exc))

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
    async def player_storage(request: Request) -> JSONResponse:
        # Wait without occupying the shared AnyIO thread pool: the restore
        # needs a worker after it finishes reading and parsing the upload.
        async with restore_access_gate.operation():
            if not sessions.authorize(request.state.player_session_token):
                return _json_denial(401, "Unauthorized")
            try:
                payload = await run_in_threadpool(
                    workspace.status_payload,
                    lock_timeout_seconds=status_lock_timeout_seconds,
                )
            except DataLockTimeoutError as exc:
                return _json_denial(409, str(exc))
            except PlayerStorageRecoveryRequired as exc:
                return _json_denial(503, str(exc))
        return JSONResponse(payload)

    @app.get(f"{PLAYER_API_PREFIX}/remote-reference/consent")
    async def player_remote_reference_consent(request: Request) -> JSONResponse:
        async with restore_access_gate.operation():
            if not sessions.authorize(request.state.player_session_token):
                return _json_denial(401, "Unauthorized")
            try:
                payload = await run_in_threadpool(
                    workspace.remote_reference_consent_status,
                    policy=provider_policy,
                    at=datetime.now(timezone.utc),
                    lock_timeout_seconds=status_lock_timeout_seconds,
                )
            except DataLockTimeoutError as exc:
                return _json_denial(409, str(exc))
            except (DataLockError, RemoteReferenceConsentStorageError):
                return _json_denial(
                    500,
                    "Remote-reference consent state could not be read safely",
                )
        return JSONResponse(payload.model_dump(mode="json", by_alias=True))

    @app.post(f"{PLAYER_API_PREFIX}/remote-reference/consent")
    async def accept_player_remote_reference_consent_route(
        request: Request,
        body: PlayerRemoteReferenceConsentRequest,
    ) -> JSONResponse:
        async with restore_access_gate.operation():
            if not sessions.authorize(request.state.player_session_token):
                return _json_denial(401, "Unauthorized")
            try:
                payload = await run_in_threadpool(
                    workspace.accept_remote_reference_consent,
                    policy=provider_policy,
                    request=body,
                    at=datetime.now(timezone.utc),
                    lock_timeout_seconds=write_lock_timeout_seconds,
                )
            except (PlayerRemoteReferenceConsentConflict, DataLockTimeoutError) as exc:
                return _json_denial(409, str(exc))
            except (DataLockError, RemoteReferenceConsentStorageError):
                return _json_denial(
                    500,
                    "Remote-reference consent could not be saved safely",
                )
        return JSONResponse(
            payload.model_dump(mode="json", by_alias=True),
            status_code=201,
        )

    @app.post(f"{PLAYER_API_PREFIX}/remote-reference/consent/revoke")
    async def revoke_player_remote_reference_consent_route(
        request: Request,
        body: PlayerRemoteReferenceRevokeRequest,
    ) -> JSONResponse:
        async with restore_access_gate.operation():
            if not sessions.authorize(request.state.player_session_token):
                return _json_denial(401, "Unauthorized")
            try:
                payload = await run_in_threadpool(
                    workspace.revoke_remote_reference_consent,
                    policy=provider_policy,
                    request=body,
                    at=datetime.now(timezone.utc),
                    lock_timeout_seconds=write_lock_timeout_seconds,
                )
            except (PlayerRemoteReferenceConsentConflict, DataLockTimeoutError) as exc:
                return _json_denial(409, str(exc))
            except (DataLockError, RemoteReferenceConsentStorageError):
                return _json_denial(
                    500,
                    "Remote-reference consent could not be revoked safely",
                )
        return JSONResponse(payload.model_dump(mode="json", by_alias=True))

    @app.get(f"{PLAYER_API_PREFIX}/hands")
    async def player_hands(
        request: Request,
        limit: int = Query(
            default=DEFAULT_PLAYER_HAND_PAGE_SIZE,
            ge=1,
            le=MAX_PLAYER_HAND_PAGE_SIZE,
        ),
        cursor: str | None = Query(default=None, pattern=r"^[0-9a-f]{64}$"),
    ) -> JSONResponse:
        async with restore_access_gate.operation():
            if not sessions.authorize(request.state.player_session_token):
                return _json_denial(401, "Unauthorized")
            try:
                payload = await run_in_threadpool(
                    workspace.list_hand_records,
                    limit=limit,
                    cursor=cursor,
                    lock_timeout_seconds=status_lock_timeout_seconds,
                )
            except DataLockTimeoutError as exc:
                return _json_denial(409, str(exc))
            except (DataLockError, OSError, ValidationError):
                return _json_denial(
                    500,
                    "Stored imported hand records could not be read safely",
                )
        return JSONResponse(payload.model_dump(mode="json"))

    @app.get(f"{PLAYER_API_PREFIX}/hands/{{record_key}}")
    async def player_hand_detail(request: Request, record_key: str) -> JSONResponse:
        async with restore_access_gate.operation():
            if not sessions.authorize(request.state.player_session_token):
                return _json_denial(401, "Unauthorized")
            try:
                payload = await run_in_threadpool(
                    workspace.get_hand_record,
                    record_key,
                    lock_timeout_seconds=status_lock_timeout_seconds,
                )
            except ImportedHandNotFoundError:
                return _json_denial(404, "Imported hand record not found")
            except PlayerHandRecoveryRequired as exc:
                return _json_denial(503, str(exc))
            except DataLockTimeoutError as exc:
                return _json_denial(409, str(exc))
            except (DataLockError, OSError, ValidationError):
                return _json_denial(
                    500,
                    "Stored imported hand record could not be read safely",
                )
        return JSONResponse(payload.model_dump(mode="json"))

    @app.get(f"{PLAYER_API_PREFIX}/hands/{{record_key}}/decisions")
    async def player_hand_decisions(
        request: Request,
        record_key: str,
    ) -> JSONResponse:
        async with restore_access_gate.operation():
            if not sessions.authorize(request.state.player_session_token):
                return _json_denial(401, "Unauthorized")
            try:
                payload = await run_in_threadpool(
                    workspace.get_active_hand_decisions,
                    record_key,
                    lock_timeout_seconds=status_lock_timeout_seconds,
                )
            except ImportedHandNotFoundError:
                return _json_denial(404, "Imported hand record not found")
            except PlayerHandDecisionsUnavailable as exc:
                return _json_denial(409, str(exc))
            except PlayerHandRecoveryRequired as exc:
                return _json_denial(503, str(exc))
            except DataLockTimeoutError as exc:
                return _json_denial(409, str(exc))
            except DecisionArtifactIntegrityError:
                return _json_denial(
                    500,
                    "Active decision extraction could not be read safely",
                )
            except (DataLockError, OSError, ValidationError):
                return _json_denial(
                    500,
                    "Stored active decision extraction could not be read safely",
                )
        return JSONResponse(payload.model_dump(mode="json"))

    @app.get(f"{PLAYER_API_PREFIX}/hands/{{record_key}}/evaluations")
    async def player_hand_decision_evaluations(
        request: Request,
        record_key: str,
    ) -> JSONResponse:
        async with restore_access_gate.operation():
            if not sessions.authorize(request.state.player_session_token):
                return _json_denial(401, "Unauthorized")
            try:
                payload = await run_in_threadpool(
                    workspace.get_active_hand_decision_evaluations,
                    record_key,
                    at=datetime.now(timezone.utc),
                    lock_timeout_seconds=status_lock_timeout_seconds,
                )
            except ImportedHandNotFoundError:
                return _json_denial(404, "Imported hand record not found")
            except PlayerHandDecisionsUnavailable as exc:
                return _json_denial(409, str(exc))
            except PlayerHandRecoveryRequired as exc:
                return _json_denial(503, str(exc))
            except DataLockTimeoutError as exc:
                return _json_denial(409, str(exc))
            except DecisionArtifactIntegrityError:
                return _json_denial(
                    500,
                    "Active decision evaluation could not be read safely",
                )
            except (DataLockError, OSError, ValidationError):
                return _json_denial(
                    500,
                    "Stored active decision evaluation could not be read safely",
                )
        return JSONResponse(payload.model_dump(mode="json", by_alias=True))

    async def close_player_hand(
        request: Request,
        record_key: str,
        body: PlayerHandCloseRequest,
        *,
        action: PlayerHandCloseAction,
    ) -> JSONResponse:
        async with restore_access_gate.operation():
            if not sessions.authorize(request.state.player_session_token):
                return _json_denial(401, "Unauthorized")
            try:
                payload = await run_in_threadpool(
                    workspace.close_hand_record,
                    record_key,
                    action=action,
                    request=body,
                    at=datetime.now(timezone.utc),
                    lock_timeout_seconds=write_lock_timeout_seconds,
                )
            except ImportedHandNotFoundError:
                return _json_denial(404, "Imported hand record not found")
            except (PlayerHandTransitionConflict, LifecycleCascadeError) as exc:
                return _json_denial(409, str(exc))
            except DataLockTimeoutError as exc:
                return _json_denial(409, str(exc))
            except (PendingCascadeError, PlayerHandRecoveryRequired):
                return _json_denial(
                    503,
                    "This hand has an interrupted lifecycle write; restart the "
                    "local player runtime so recovery can finish",
                )
            except (DataLockError, OSError, ValidationError):
                return _json_denial(
                    500,
                    "The hand approval state could not be changed safely",
                )
        return JSONResponse(payload.model_dump(mode="json"))

    @app.post(f"{PLAYER_API_PREFIX}/hands/{{record_key}}/withdraw")
    async def withdraw_player_hand(
        request: Request,
        record_key: str,
        body: PlayerHandCloseRequest,
    ) -> JSONResponse:
        return await close_player_hand(
            request,
            record_key,
            body,
            action="withdraw",
        )

    @app.post(f"{PLAYER_API_PREFIX}/hands/{{record_key}}/reject")
    async def reject_player_hand(
        request: Request,
        record_key: str,
        body: PlayerHandCloseRequest,
    ) -> JSONResponse:
        return await close_player_hand(
            request,
            record_key,
            body,
            action="reject",
        )

    @app.post(f"{PLAYER_API_PREFIX}/hands/{{record_key}}/approve")
    async def approve_player_hand(
        request: Request,
        record_key: str,
        body: PlayerHandApprovalRequest,
    ) -> JSONResponse:
        async with restore_access_gate.operation():
            if not sessions.authorize(request.state.player_session_token):
                return _json_denial(401, "Unauthorized")
            try:
                payload = await run_in_threadpool(
                    workspace.approve_hand_record,
                    record_key,
                    request=body,
                    at=datetime.now(timezone.utc),
                    lock_timeout_seconds=write_lock_timeout_seconds,
                )
            except ImportedHandNotFoundError:
                return _json_denial(404, "Imported hand record not found")
            except PlayerHandApprovalInvalid as exc:
                return _json_denial(422, str(exc))
            except ValidationError:
                return _json_denial(422, "Reviewed canonical state is invalid")
            except (PlayerHandTransitionConflict, LifecycleCascadeError) as exc:
                return _json_denial(409, str(exc))
            except DataLockTimeoutError as exc:
                return _json_denial(409, str(exc))
            except (PendingCascadeError, PlayerHandRecoveryRequired):
                return _json_denial(
                    503,
                    "This hand has an interrupted approval write; restart the "
                    "local player runtime so recovery can finish",
                )
            except (DataLockError, OSError):
                return _json_denial(
                    500,
                    "Approval did not finish safely; refresh the hand before retrying",
                )
        return JSONResponse(payload.model_dump(mode="json"))

    @app.post(
        f"{PLAYER_API_PREFIX}/hands/{{record_key}}/conflicts/"
        "{conflict_id}/resolve"
    )
    async def resolve_player_hand_conflict(
        request: Request,
        record_key: str,
        conflict_id: str,
        body: PlayerHandConflictResolutionRequest,
    ) -> JSONResponse:
        async with restore_access_gate.operation():
            if not sessions.authorize(request.state.player_session_token):
                return _json_denial(401, "Unauthorized")
            try:
                payload = await run_in_threadpool(
                    workspace.resolve_hand_conflict,
                    record_key,
                    conflict_id=conflict_id,
                    request=body,
                    at=datetime.now(timezone.utc),
                    lock_timeout_seconds=write_lock_timeout_seconds,
                )
            except ImportedHandNotFoundError:
                return _json_denial(404, "Imported hand record not found")
            except PlayerHandConflictResolutionInvalid as exc:
                return _json_denial(422, str(exc))
            except ValidationError:
                return _json_denial(422, "The conflict source choice is invalid")
            except (PlayerHandTransitionConflict, LifecycleCascadeError) as exc:
                return _json_denial(409, str(exc))
            except DataLockTimeoutError as exc:
                return _json_denial(409, str(exc))
            except (PendingCascadeError, PlayerHandRecoveryRequired):
                return _json_denial(
                    503,
                    "This hand has an interrupted conflict-resolution write;"
                    " restart the local player runtime so recovery can finish",
                )
            except (DataLockError, OSError):
                return _json_denial(
                    500,
                    "Conflict resolution did not finish safely; refresh the hand"
                    " before retrying",
                )
        return JSONResponse(payload.model_dump(mode="json"))

    @app.post(f"{PLAYER_API_PREFIX}/hands/{{record_key}}/delete")
    async def delete_player_hand(
        request: Request,
        record_key: str,
        body: PlayerHandDeleteRequest,
    ) -> JSONResponse:
        async with restore_access_gate.operation():
            if not sessions.authorize(request.state.player_session_token):
                return _json_denial(401, "Unauthorized")
            try:
                payload = await run_in_threadpool(
                    workspace.delete_hand_record,
                    record_key,
                    request=body,
                    at=datetime.now(timezone.utc),
                    lock_timeout_seconds=write_lock_timeout_seconds,
                )
            except ImportedHandNotFoundError:
                return _json_denial(404, "Imported hand record not found")
            except (PlayerHandTransitionConflict, LifecycleCascadeError) as exc:
                return _json_denial(409, str(exc))
            except DataLockTimeoutError as exc:
                return _json_denial(409, str(exc))
            except (PendingCascadeError, PlayerHandRecoveryRequired):
                return _json_denial(
                    503,
                    "This hand has an interrupted deletion write; restart the "
                    "local player runtime so recovery can finish",
                )
            except (DataLockError, OSError, ValidationError):
                return _json_denial(
                    500,
                    "Permanent deletion did not finish safely; refresh the hand "
                    "to inspect whether cleanup is pending before retrying",
                )
        return JSONResponse(payload.model_dump(mode="json"))

    @app.post(f"{PLAYER_API_PREFIX}/hands/{{record_key}}/reimport")
    async def reimport_deleted_player_hand(
        request: Request,
        record_key: str,
    ) -> JSONResponse:
        media_type = request.headers.get("content-type", "").partition(";")[0]
        if media_type.strip().lower() != "multipart/form-data":
            return _json_denial(
                415,
                "Authorized hand reimports require multipart form data",
            )
        try:
            async with request.form(
                max_files=1,
                max_fields=5,
                max_part_size=4096,
            ) as form:
                allowed_fields = {
                    "request_id",
                    "expected_record_version",
                    "expected_lifecycle_status",
                    "expected_deletion_generation",
                    "expected_lifecycle_changed_at",
                    "file",
                }
                if any(
                    key not in allowed_fields
                    for key, _value in form.multi_items()
                ):
                    return _json_denial(
                        400,
                        "Authorized hand reimport form contains an unsupported field",
                    )
                raw_fields: dict[str, str] = {}
                for field_name in allowed_fields - {"file"}:
                    values = form.getlist(field_name)
                    if len(values) != 1 or not isinstance(values[0], str):
                        return _json_denial(
                            400,
                            f"Authorized hand reimport requires one {field_name} field",
                        )
                    raw_fields[field_name] = values[0]
                try:
                    deletion_generation = int(
                        raw_fields["expected_deletion_generation"]
                    )
                    reimport_request = PlayerHandReimportRequest.model_validate(
                        {
                            **raw_fields,
                            "expected_deletion_generation": deletion_generation,
                        }
                    )
                except (ValidationError, ValueError):
                    return _json_denial(
                        400,
                        "Authorized hand reimport preconditions are invalid",
                    )
                file_values = form.getlist("file")
                if len(file_values) != 1 or not isinstance(
                    file_values[0],
                    UploadFile,
                ):
                    return _json_denial(
                        400,
                        "Authorized hand reimport requires one PokerStars text file",
                    )
                sources_or_error = await _read_player_import_files(
                    [file_values[0]],
                    max_player_import_file_bytes=max_player_import_file_bytes,
                    max_player_import_batch_bytes=max_player_import_file_bytes,
                )
        except StarletteHTTPException:
            return _json_denial(
                413,
                "Authorized hand reimport multipart limits exceeded",
            )
        if isinstance(sources_or_error, JSONResponse):
            return sources_or_error
        source_or_rejection = sources_or_error[0]
        if isinstance(source_or_rejection, PlayerImportFileOutcome):
            diagnostic = source_or_rejection.diagnostics[0]
            status_code = (
                413
                if diagnostic.code == "file_too_large"
                else 415
                if diagnostic.code == "unsupported_media_type"
                else 422
            )
            return _json_denial(status_code, diagnostic.message)

        async with restore_access_gate.operation():
            if not sessions.authorize(request.state.player_session_token):
                return _json_denial(401, "Unauthorized")
            try:
                outcome = await run_in_threadpool(
                    reimport_pokerstars_hand,
                    workspace,
                    record_key,
                    request=reimport_request,
                    imported_at=datetime.now(timezone.utc),
                    source=source_or_rejection,
                    lock_timeout_seconds=write_lock_timeout_seconds,
                )
            except ImportedHandNotFoundError:
                return _json_denial(404, "Imported hand record not found")
            except PlayerHandReimportInvalid as exc:
                return _json_denial(422, str(exc))
            except (PlayerHandTransitionConflict, LifecycleCascadeError) as exc:
                return _json_denial(409, str(exc))
            except DataLockTimeoutError as exc:
                return _json_denial(409, str(exc))
            except (PendingCascadeError, PlayerHandRecoveryRequired):
                return _json_denial(
                    503,
                    "This hand has an interrupted authorized reimport; restart"
                    " the local player runtime so recovery can finish",
                )
            except (DataLockError, OSError, ValidationError):
                return _json_denial(
                    500,
                    "Authorized reimport did not finish safely; retry the exact"
                    " request before selecting another file",
                )
        return JSONResponse(outcome.model_dump(mode="json"))

    @app.post(f"{PLAYER_API_PREFIX}/imports")
    async def import_player_pokerstars_files(
        request: Request,
    ) -> JSONResponse:
        media_type = request.headers.get("content-type", "").partition(";")[0]
        if media_type.strip().lower() != "multipart/form-data":
            return _json_denial(
                415,
                "Player imports require multipart form data",
            )
        try:
            async with request.form(
                max_files=max_player_import_files,
                max_fields=1,
                max_part_size=4096,
            ) as form:
                if any(
                    key not in {"request_id", "files"}
                    for key, _value in form.multi_items()
                ):
                    return _json_denial(
                        400,
                        "Player import form contains an unsupported field",
                    )
                request_values = form.getlist("request_id")
                if len(request_values) != 1 or not isinstance(
                    request_values[0],
                    str,
                ):
                    return _json_denial(
                        400,
                        "Player import requires one UUID request_id field",
                    )
                try:
                    request_id = TypeAdapter(PlayerRequestId).validate_python(
                        request_values[0]
                    )
                except ValidationError:
                    return _json_denial(
                        400,
                        "Player import request_id must be a valid UUID",
                    )
                file_values = form.getlist("files")
                if not all(
                    isinstance(file_value, UploadFile)
                    for file_value in file_values
                ):
                    return _json_denial(
                        400,
                        "Every player import files field must contain a file",
                    )
                files = [
                    file_value
                    for file_value in file_values
                    if isinstance(file_value, UploadFile)
                ]
                sources_or_error = await _read_player_import_files(
                    files,
                    max_player_import_file_bytes=max_player_import_file_bytes,
                    max_player_import_batch_bytes=max_player_import_batch_bytes,
                )
        except StarletteHTTPException as exc:
            status_code = 413 if "files" in str(exc.detail).lower() else 400
            return _json_denial(status_code, "Player import multipart limits exceeded")
        if isinstance(sources_or_error, JSONResponse):
            return sources_or_error
        sources = sources_or_error

        async with restore_access_gate.operation():
            if not sessions.authorize(request.state.player_session_token):
                return _json_denial(401, "Unauthorized")
            try:
                status = await run_in_threadpool(
                    workspace.status_payload,
                    lock_timeout_seconds=status_lock_timeout_seconds,
                )
                if status["status"] != "ready":
                    return _json_denial(
                        503,
                        "Player storage recovery needs attention before import",
                    )
                outcome = await run_in_threadpool(
                    import_pokerstars_files,
                    workspace,
                    request_id=request_id,
                    imported_at=datetime.now(timezone.utc),
                    files=sources,
                    lock_timeout_seconds=write_lock_timeout_seconds,
                )
            except DataLockTimeoutError as exc:
                return _json_denial(409, str(exc))
            except PlayerStorageRecoveryRequired as exc:
                return _json_denial(503, str(exc))
        return JSONResponse(outcome.model_dump(mode="json"))

    @app.get(f"{PLAYER_API_PREFIX}/backups/export")
    async def export_player_backup(request: Request) -> Response:
        async with restore_access_gate.operation():
            if not sessions.authorize(request.state.player_session_token):
                return _json_denial(401, "Unauthorized")
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
        nonlocal restore_in_progress
        # Claim the restore slot before the first await. A status request that
        # follows a lost response will then wait from the start of body
        # handling until the restore has either committed or failed.
        if restore_in_progress:
            return _json_denial(409, "Another player restore is already in progress")
        restore_in_progress = True
        try:
            async with restore_access_gate.restore():
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
                except PlayerBackupStorageError as exc:
                    # Storage failures can follow durable journal intent or
                    # partial publication. Disable every session and ticket so
                    # no browser can resume ordinary work before process-start
                    # recovery has run.
                    sessions.disable_until_restart()
                    return _json_denial(exc.status_code, str(exc))
                except PlayerBackupError as exc:
                    return _json_denial(exc.status_code, str(exc))
                except DataLockTimeoutError as exc:
                    return _json_denial(409, str(exc))
                return JSONResponse(result.model_dump(mode="json"))
        finally:
            restore_in_progress = False

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

    bounded_app: ASGIApp = PlayerImportBodyLimitMiddleware(
        app,
        limit=(
            max_player_import_batch_bytes
            + PLAYER_IMPORT_MULTIPART_OVERHEAD_BYTES
        ),
        reimport_limit=(
            max_player_import_file_bytes
            + PLAYER_IMPORT_MULTIPART_OVERHEAD_BYTES
        ),
    )
    secured_app: ASGIApp = PlayerApiSessionMiddleware(bounded_app, sessions)
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
