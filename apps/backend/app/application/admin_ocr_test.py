"""Administrative OCR test access policy for the capture/upload boundary.

ADR 0046 keeps screenshot upload and live capture only as an administrator
parser-testing capability. The policy is disabled unless deployment enables it
explicitly, and the presented credential is compared in constant time against a
digest so the plaintext token is never retained by the application.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

AdminOcrTestAccessDecision = Literal["authorized", "disabled", "unauthorized"]
AuthorizeAdministrator = Callable[[str | None], AdminOcrTestAccessDecision]


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


@dataclass(frozen=True)
class AdminOcrTestAccessPolicy:
    """Decide whether a request may use the administrative OCR test surface."""

    enabled: bool
    token_digest: bytes | None

    @classmethod
    def disabled(cls) -> "AdminOcrTestAccessPolicy":
        return cls(enabled=False, token_digest=None)

    @classmethod
    def for_token(cls, token: str) -> "AdminOcrTestAccessPolicy":
        if not token:
            raise ValueError("administrative OCR test mode requires a non-empty token")
        return cls(enabled=True, token_digest=_digest(token))

    def authorize(
        self,
        authorization_header: str | None,
    ) -> AdminOcrTestAccessDecision:
        if not self.enabled or self.token_digest is None:
            return "disabled"
        if authorization_header is None:
            return "unauthorized"
        scheme, _, credential = authorization_header.strip().partition(" ")
        credential = credential.strip()
        if scheme.lower() != "bearer" or not credential:
            return "unauthorized"
        if hmac.compare_digest(_digest(credential), self.token_digest):
            return "authorized"
        return "unauthorized"


@dataclass(frozen=True)
class AdminOcrTestService:
    """Application operations required by the administrative session transport."""

    enabled: bool
    authorize_administrator: AuthorizeAdministrator


__all__ = [
    "AdminOcrTestAccessDecision",
    "AdminOcrTestAccessPolicy",
    "AdminOcrTestService",
    "AuthorizeAdministrator",
]
