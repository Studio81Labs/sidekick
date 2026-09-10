from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from secrets import compare_digest, token_urlsafe
import tempfile
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


McpEnvironment = Literal["staging", "production"]
MCP_TOKEN_PATTERN = re.compile(
    r"^phmcp_([A-Za-z0-9_-]{12})\.([A-Za-z0-9_-]{43})$"
)
MCP_PRINCIPAL_ID_PATTERN = re.compile(r"^mcp_[0-9a-f]{32}$")


class McpPrincipalRecord(BaseModel):
    id: str = Field(pattern=MCP_PRINCIPAL_ID_PATTERN.pattern)
    name: str = Field(min_length=3, max_length=100)
    environment: McpEnvironment
    token_prefix: str = Field(min_length=12, max_length=12)
    token_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scopes: list[Literal["read"]] = Field(min_length=1, max_length=1)
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


class McpPrincipalSummary(BaseModel):
    id: str
    name: str
    environment: McpEnvironment
    token_prefix: str
    status: Literal["active", "expired", "revoked"]
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


class McpIssuedPrincipal(BaseModel):
    principal: McpPrincipalSummary
    token: str


class McpPrincipalList(BaseModel):
    principals: list[McpPrincipalSummary]


class McpAccessConfig(BaseModel):
    enabled: bool
    environment: Literal["local", "staging", "production"]
    endpoint: str | None


class CreateMcpPrincipalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3, max_length=100)
    expires_at: datetime | None = None


class McpAuthenticatedPrincipal(BaseModel):
    id: str
    name: str
    environment: McpEnvironment


class _McpPrincipalFile(BaseModel):
    schema_version: Literal[1] = 1
    principals: list[McpPrincipalRecord] = Field(default_factory=list)


MCP_PRINCIPAL_CONTEXT: ContextVar[McpAuthenticatedPrincipal | None] = ContextVar(
    "poker_mcp_principal",
    default=None,
)


class McpPrincipalStore:
    def __init__(self, data_dir: Path, environment: McpEnvironment) -> None:
        self.environment = environment
        self.directory = data_dir / "mcp"
        self.path = self.directory / "principals.json"
        self.lock_path = self.directory / ".principals.lock"

    def list(self) -> list[McpPrincipalSummary]:
        with self._locked(exclusive=False):
            records = self._read().principals
        now = _now()
        return [
            _summary(record, now)
            for record in reversed(records)
            if record.environment == self.environment
        ]

    def create(
        self,
        *,
        name: str,
        expires_at: datetime | None,
    ) -> McpIssuedPrincipal:
        normalized_name = name.strip()
        if len(normalized_name) < 3 or len(normalized_name) > 100:
            raise ValueError("MCP principal name must be 3-100 characters")
        now = _now()
        normalized_expiry = _validate_expiry(expires_at, now)
        with self._locked(exclusive=True):
            payload = self._read()
            generated = _generate_token()
            record = McpPrincipalRecord(
                id=f"mcp_{uuid4().hex}",
                name=normalized_name,
                environment=self.environment,
                token_prefix=generated[1],
                token_hash=_hash_token(generated[0]),
                scopes=["read"],
                created_at=now,
                updated_at=now,
                expires_at=normalized_expiry,
            )
            payload.principals.append(record)
            self._write(payload)
        return McpIssuedPrincipal(
            principal=_summary(record, now),
            token=generated[0],
        )

    def rotate(self, principal_id: str) -> McpIssuedPrincipal:
        _validate_principal_id(principal_id)
        now = _now()
        with self._locked(exclusive=True):
            payload = self._read()
            record = self._find(payload, principal_id)
            if _summary(record, now).status != "active":
                raise ValueError("MCP principal is not active")
            if record.scopes != ["read"]:
                raise ValueError(
                    "MCP principal does not use the current read-only scope"
                )
            generated = _generate_token()
            record.token_prefix = generated[1]
            record.token_hash = _hash_token(generated[0])
            record.last_used_at = None
            record.updated_at = now
            self._write(payload)
        return McpIssuedPrincipal(
            principal=_summary(record, now),
            token=generated[0],
        )

    def revoke(self, principal_id: str) -> McpPrincipalSummary:
        _validate_principal_id(principal_id)
        now = _now()
        with self._locked(exclusive=True):
            payload = self._read()
            record = self._find(payload, principal_id)
            if record.revoked_at is None:
                record.revoked_at = now
                record.updated_at = now
                self._write(payload)
        return _summary(record, now)

    def authenticate(self, token: str) -> McpAuthenticatedPrincipal | None:
        match = MCP_TOKEN_PATTERN.fullmatch(token)
        if match is None:
            return None
        prefix = match.group(1)
        now = _now()
        with self._locked(exclusive=False):
            payload = self._read()
            record = next(
                (
                    candidate
                    for candidate in payload.principals
                    if candidate.environment == self.environment
                    and candidate.token_prefix == prefix
                ),
                None,
            )
            if (
                record is None
                or _summary(record, now).status != "active"
                or not compare_digest(_hash_token(token), record.token_hash)
            ):
                return None
            if record.scopes != ["read"]:
                return None
        return McpAuthenticatedPrincipal(
            id=record.id,
            name=record.name,
            environment=record.environment,
        )

    def record_usage(self, token: str) -> bool:
        match = MCP_TOKEN_PATTERN.fullmatch(token)
        if match is None:
            return False
        prefix = match.group(1)
        now = _now()
        with self._locked(exclusive=True):
            payload = self._read()
            record = next(
                (
                    candidate
                    for candidate in payload.principals
                    if candidate.environment == self.environment
                    and candidate.token_prefix == prefix
                ),
                None,
            )
            if (
                record is None
                or _summary(record, now).status != "active"
                or not compare_digest(_hash_token(token), record.token_hash)
            ):
                return False
            if record.scopes != ["read"]:
                return False
            record.last_used_at = now
            record.updated_at = now
            self._write(payload)
        return True

    def _find(
        self,
        payload: _McpPrincipalFile,
        principal_id: str,
    ) -> McpPrincipalRecord:
        principal = next(
            (
                candidate
                for candidate in payload.principals
                if candidate.id == principal_id
                and candidate.environment == self.environment
            ),
            None,
        )
        if principal is None:
            raise KeyError("MCP principal not found")
        return principal

    def _read(self) -> _McpPrincipalFile:
        try:
            return _McpPrincipalFile.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return _McpPrincipalFile()

    def _write(self, payload: _McpPrincipalFile) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                dir=self.directory,
                encoding="utf-8",
                prefix=".principals.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(
                    payload.model_dump(mode="json"),
                    temporary,
                    separators=(",", ":"),
                )
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.chmod(0o600)
            os.replace(temporary_path, self.path)
            directory_descriptor = os.open(
                self.directory,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _locked(self, *, exclusive: bool):
        return _FileLock(self.lock_path, exclusive=exclusive)


class _FileLock:
    def __init__(self, path: Path, *, exclusive: bool) -> None:
        self.path = path
        self.exclusive = exclusive
        self.descriptor: int | None = None

    def __enter__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.descriptor = os.open(self.path, os.O_RDONLY | os.O_CREAT, 0o600)
        fcntl.flock(
            self.descriptor,
            fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH,
        )

    def __exit__(self, *_args: object) -> None:
        assert self.descriptor is not None
        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self.descriptor)


def _generate_token() -> tuple[str, str]:
    prefix = token_urlsafe(9)
    secret = token_urlsafe(32)
    return f"phmcp_{prefix}.{secret}", prefix


def _hash_token(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def _validate_expiry(
    expires_at: datetime | None,
    now: datetime,
) -> datetime | None:
    if expires_at is None:
        return None
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise ValueError("MCP principal expiry must include a timezone")
    normalized = expires_at.astimezone(timezone.utc)
    if normalized <= now:
        raise ValueError("MCP principal expiry must be in the future")
    return normalized


def _validate_principal_id(principal_id: str) -> None:
    if MCP_PRINCIPAL_ID_PATTERN.fullmatch(principal_id) is None:
        raise ValueError("Invalid MCP principal id")


def _summary(
    record: McpPrincipalRecord,
    now: datetime,
) -> McpPrincipalSummary:
    if record.revoked_at is not None:
        status = "revoked"
    elif record.expires_at is not None and record.expires_at <= now:
        status = "expired"
    else:
        status = "active"
    return McpPrincipalSummary(
        **record.model_dump(exclude={"token_hash", "scopes"}),
        status=status,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)
