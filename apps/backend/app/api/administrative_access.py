"""Shared fail-closed HTTP mapping for the administrative OCR test gate.

Every route that ingests screenshots or confirms the administrator credential
maps the access policy's decision the same way: only an explicit
``"authorized"`` decision proceeds, a disabled deployment answers 403, a
missing or rejected bearer answers 401, and any decision this transport does
not recognize denies with 403 instead of opening the surface.
"""

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request, Response, Security
from fastapi.security import HTTPBearer
from fastapi.routing import APIRoute

from app.application.admin_ocr_test import (
    AdminOcrTestAccessDecision,
    AuthorizeAdministrator,
)

# Denials answer a presented credential, so no shared cache may replay them.
_NO_STORE = {"Cache-Control": "no-store"}

# This dependency is documentation-only. AdministratorAccessRoute still
# evaluates the supplied credential before FastAPI parses a request body,
# preserving the fail-closed boundary for screenshot and backup uploads.
_administrator_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="AdministratorBearer",
)
_ADMINISTRATOR_ACCESS_RESPONSES = {
    401: {"description": "Administrative OCR test authorization is required"},
    403: {"description": "Administrative OCR test mode is disabled or authorization was refused"},
}


def require_administrator(decision: AdminOcrTestAccessDecision) -> None:
    """Raise the fixed HTTP denial unless ``decision`` is ``"authorized"``."""

    if decision == "authorized":
        return
    if decision == "disabled":
        raise HTTPException(
            status_code=403,
            detail="Administrative OCR test mode is disabled",
            headers=_NO_STORE,
        )
    if decision == "unauthorized":
        raise HTTPException(
            status_code=401,
            detail="Administrative OCR test authorization is required",
            headers={"WWW-Authenticate": "Bearer", **_NO_STORE},
        )
    raise HTTPException(
        status_code=403,
        detail="Administrative OCR test authorization was refused",
        headers=_NO_STORE,
    )


def administrator_access_route(
    authorize_administrator: AuthorizeAdministrator,
) -> type[APIRoute]:
    """Build routes that check the administrator gate before request parsing."""

    class AdministratorAccessRoute(APIRoute):
        def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
            handle_request = super().get_route_handler()

            async def handle_administrator_request(request: Request) -> Response:
                require_administrator(
                    authorize_administrator(request.headers.get("Authorization"))
                )
                return await handle_request(request)

            return handle_administrator_request

    return AdministratorAccessRoute


def administrator_access_router(
    authorize_administrator: AuthorizeAdministrator,
) -> APIRouter:
    """Build an administrative router with runtime and OpenAPI authorization."""

    return APIRouter(
        dependencies=[Security(_administrator_bearer)],
        responses=_ADMINISTRATOR_ACCESS_RESPONSES,
        route_class=administrator_access_route(authorize_administrator),
    )


__all__ = [
    "administrator_access_route",
    "administrator_access_router",
    "require_administrator",
]
