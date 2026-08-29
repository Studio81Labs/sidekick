import pytest
from fastapi import HTTPException

from app.api.administrative_access import require_administrator


def test_authorized_decision_passes_silently() -> None:
    assert require_administrator("authorized") is None


def test_disabled_decision_is_forbidden() -> None:
    with pytest.raises(HTTPException) as raised:
        require_administrator("disabled")

    assert raised.value.status_code == 403
    assert raised.value.detail == "Administrative OCR test mode is disabled"


def test_unauthorized_decision_requires_bearer() -> None:
    with pytest.raises(HTTPException) as raised:
        require_administrator("unauthorized")

    assert raised.value.status_code == 401
    assert raised.value.detail == "Administrative OCR test authorization is required"
    assert raised.value.headers == {"WWW-Authenticate": "Bearer"}


def test_unknown_decision_fails_closed() -> None:
    with pytest.raises(HTTPException) as raised:
        require_administrator("expired")  # type: ignore[arg-type]

    assert raised.value.status_code == 403
    assert raised.value.detail == "Administrative OCR test authorization was refused"
