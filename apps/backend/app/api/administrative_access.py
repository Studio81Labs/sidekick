"""Shared fail-closed HTTP mapping for the administrative OCR test gate.

Every route that ingests screenshots or confirms the administrator credential
maps the access policy's decision the same way: only an explicit
``"authorized"`` decision proceeds, a disabled deployment answers 403, a
missing or rejected bearer answers 401, and any decision this transport does
not recognize denies with 403 instead of opening the surface.
"""

from fastapi import HTTPException

from app.application.admin_ocr_test import AdminOcrTestAccessDecision


def require_administrator(decision: AdminOcrTestAccessDecision) -> None:
    """Raise the fixed HTTP denial unless ``decision`` is ``"authorized"``."""

    if decision == "authorized":
        return
    if decision == "disabled":
        raise HTTPException(
            status_code=403,
            detail="Administrative OCR test mode is disabled",
        )
    if decision == "unauthorized":
        raise HTTPException(
            status_code=401,
            detail="Administrative OCR test authorization is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    raise HTTPException(
        status_code=403,
        detail="Administrative OCR test authorization was refused",
    )


__all__ = ["require_administrator"]
