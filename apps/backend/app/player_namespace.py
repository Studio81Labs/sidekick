from __future__ import annotations

from urllib.parse import unquote

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


PLAYER_API_PREFIX = "/api/player"
MAX_PATH_DECODE_DEPTH = 8


def is_player_api_path(path: str) -> bool:
    """Recognize the reserved player namespace through encoded path layers."""

    candidate = path
    for _depth in range(MAX_PATH_DECODE_DEPTH):
        if candidate == PLAYER_API_PREFIX or candidate.startswith(
            f"{PLAYER_API_PREFIX}/"
        ):
            return True
        try:
            decoded = unquote(candidate, errors="strict")
        except UnicodeDecodeError:
            return False
        if decoded == candidate:
            return False
        candidate = decoded
    return (
        "%" in candidate
        or candidate == PLAYER_API_PREFIX
        or candidate.startswith(f"{PLAYER_API_PREFIX}/")
    )


def scope_request_path(scope: Scope) -> str:
    raw_path = scope.get("raw_path")
    if isinstance(raw_path, bytes):
        return raw_path.decode("latin-1")
    return str(scope.get("path", ""))


class DenyHostedPlayerNamespaceMiddleware:
    """Keep player-only routes outside the broad hosted V1 application."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        api_application: ASGIApp | None = None,
    ) -> None:
        self.app = app
        self.api_application = api_application

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] not in {"http", "websocket"} or not is_player_api_path(
            scope_request_path(scope)
        ):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] == "http":
            response = JSONResponse(
                {"detail": "Not Found"},
                status_code=404,
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
