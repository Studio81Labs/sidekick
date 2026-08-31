from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import hmac
from ipaddress import ip_address
import json
import os
from pathlib import Path
import secrets
from stat import S_ISREG
from threading import Lock
from time import monotonic
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
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
PLAYER_SESSION_STORAGE_KEY = "poker-hero-player-session-v1"
PLAYER_CSRF_STORAGE_KEY = "poker-hero-player-csrf-v1"


PLAYER_SHELL = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="theme-color" content="#1f2937" />
    <meta name="application-name" content="Poker Hero Player" />
    <title>Poker Hero · Local Player Runtime</title>
  </head>
  <body>
    <main>
      <h1>Poker Hero</h1>
      <p id="runtime-status" role="status">Starting the local player runtime…</p>
      <p>Player data location: <code id="data-location">authentication required</code></p>
      <p>The V2 hand-import workflow is not enabled in this foundation release.</p>
    </main>
    <script type="module" src="/player-bootstrap.js"></script>
  </body>
</html>
"""

PLAYER_BOOTSTRAP_SCRIPT = f"""const sessionKey = {json.dumps(PLAYER_SESSION_STORAGE_KEY)};
const csrfKey = {json.dumps(PLAYER_CSRF_STORAGE_KEY)};
const status = document.getElementById("runtime-status");

function setStatus(message) {{
  status.textContent = message;
}}

async function exchangeTicket(ticket) {{
  const response = await fetch("/api/player/session", {{
    method: "POST",
    credentials: "same-origin",
    headers: {{ Authorization: `Bearer ${{ticket}}` }},
  }});
  if (!response.ok) throw new Error("The one-use launch ticket was rejected.");
  const session = await response.json();
  sessionStorage.setItem(sessionKey, session.session_token);
  sessionStorage.setItem(csrfKey, session.csrf_token);
  return session.session_token;
}}

async function verifySession(token) {{
  const response = await fetch("/api/player/health", {{
    cache: "no-store",
    credentials: "same-origin",
    headers: {{ Authorization: `Bearer ${{token}}` }},
  }});
  if (!response.ok) throw new Error("The local player session is unavailable.");
}}

async function loadStorageStatus(token) {{
  const response = await fetch("/api/player/storage", {{
    cache: "no-store",
    credentials: "same-origin",
    headers: {{ Authorization: `Bearer ${{token}}` }},
  }});
  if (!response.ok) throw new Error("The local player store is unavailable.");
  return response.json();
}}

async function bootstrap() {{
  const fragment = new URLSearchParams(location.hash.slice(1));
  const ticket = fragment.get("ticket");
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  let token = sessionStorage.getItem(sessionKey);
  if (ticket) token = await exchangeTicket(ticket);
  if (!token) throw new Error("Start the player runtime again to create a session.");
  await verifySession(token);
  const storage = await loadStorageStatus(token);
  document.getElementById("data-location").textContent = storage.data_directory;
  setStatus(storage.status === "ready"
    ? "The authenticated loopback runtime and player store are ready."
    : "The player store needs recovery attention before import is enabled.");
}}

bootstrap().catch((error) => {{
  sessionStorage.removeItem(sessionKey);
  sessionStorage.removeItem(csrfKey);
  setStatus(error instanceof Error ? error.message : "Player runtime startup failed.");
}});
"""


class PlayerCredentialError(RuntimeError):
    pass


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


def create_player_runtime(
    data_dir: Path,
    *,
    authority: str = PLAYER_AUTHORITY,
    origin: str = PLAYER_ORIGIN,
    clock: Callable[[], float] = monotonic,
    recovery_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_TIMEOUT_SECONDS,
    startup_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_SHARED_TIMEOUT_SECONDS,
    write_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS,
    backup_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_EXPORT_TIMEOUT_SECONDS,
    max_player_backup_bytes: int = DEFAULT_MAX_PLAYER_BACKUP_BYTES,
) -> PlayerRuntime:
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
    app = FastAPI(
        title="Poker Hero Local Player Runtime",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/", response_class=HTMLResponse)
    async def player_shell() -> str:
        return PLAYER_SHELL

    @app.get("/player-bootstrap.js")
    async def player_bootstrap_script() -> Response:
        return Response(PLAYER_BOOTSTRAP_SCRIPT, media_type="text/javascript")

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
        return JSONResponse(await run_in_threadpool(workspace.status_payload))

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
        return JSONResponse(result.model_dump(mode="json"))

    @app.delete(f"{PLAYER_API_PREFIX}/session")
    async def revoke_session(request: Request) -> Response:
        session_token = request.state.player_session_token
        sessions.revoke(session_token)
        return Response(status_code=204)

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
