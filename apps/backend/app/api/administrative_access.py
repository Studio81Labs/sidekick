"""Shared fail-closed HTTP mapping for the administrative OCR test gate.

Every route that ingests screenshots or confirms the administrator credential
maps the access policy's decision the same way: only an explicit
``"authorized"`` decision proceeds, a disabled deployment answers 403, a
missing or rejected bearer answers 401, and any decision this transport does
not recognize denies with 403 instead of opening the surface.
"""

from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute

from app.application.admin_ocr_test import (
    AdminOcrTestAccessDecision,
    AuthorizeAdministrator,
)

# Denials answer a presented credential, so no shared cache may replay them.
_NO_STORE = {"Cache-Control": "no-store"}


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


__all__ = ["administrator_access_route", "require_administrator"]
