"""Administrative OCR test session contract."""

from pydantic import BaseModel


class AdminOcrTestSession(BaseModel):
    """Server confirmation that a presented administrator credential is valid."""

    enabled: bool
    authorized: bool
