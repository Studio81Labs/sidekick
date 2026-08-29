from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from ipaddress import ip_address
import math
import re
from threading import Lock
from time import monotonic
from typing import Literal

from starlette.requests import Request


RateLimitCategory = Literal[
    "uploads",
    "recommendations",
    "benchmarks",
    "data_transfers",
]
RATE_LIMIT_CATEGORIES: frozenset[RateLimitCategory] = frozenset(
    {"uploads", "recommendations", "benchmarks", "data_transfers"}
)

RATE_LIMIT_WINDOW_SECONDS = 60.0
RATE_LIMIT_MAX_BUCKETS = 4096
CONNECTING_IP_HEADER = "CF-Connecting-IP"
_RECOMMENDATION_PATH = re.compile(r"^/api/jobs/[^/]+/recommend$")
_BENCHMARK_IMPORT_RECOVERY_PATH = re.compile(
    r"^/api/benchmarks/imports/[^/]+$"
)
_DATA_TRANSFER_ROUTES = frozenset(
    {
        ("GET", "/api/backups/export"),
        ("POST", "/api/backups/restore"),
        ("GET", "/api/benchmarks/export"),
        ("POST", "/api/benchmarks/import"),
    }
)


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


@dataclass
class _TokenBucket:
    tokens: float
    updated_at: float


class ApiRateLimiter:
    """Bounded per-client token buckets for resource-intensive API routes."""

    def __init__(
        self,
        limits: Mapping[RateLimitCategory, int],
        *,
        window_seconds: float = RATE_LIMIT_WINDOW_SECONDS,
        max_buckets: int = RATE_LIMIT_MAX_BUCKETS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if window_seconds <= 0 or not math.isfinite(window_seconds):
            raise ValueError("window_seconds must be a positive finite number")
        if max_buckets <= 0:
            raise ValueError("max_buckets must be positive")
        if set(limits) != RATE_LIMIT_CATEGORIES:
            raise ValueError("limits must define every rate-limit category")
        if any(limit <= 0 for limit in limits.values()):
            raise ValueError("rate limits must be positive")
        self._limits = dict(limits)
        self._window_seconds = window_seconds
        self._max_buckets = max_buckets
        self._clock = clock
        self._buckets: OrderedDict[
            tuple[RateLimitCategory, bytes], _TokenBucket
        ] = OrderedDict()
        self._lock = Lock()

    def check(
        self,
        category: RateLimitCategory,
        identity: str,
    ) -> RateLimitDecision:
        limit = self._limits[category]
        refill_per_second = limit / self._window_seconds
        key = (category, sha256(identity.encode("utf-8")).digest())

        with self._lock:
            now = self._clock()
            bucket = self._buckets.get(key)
            if bucket is None:
                self._discard_inactive_buckets(now)
                if len(self._buckets) >= self._max_buckets:
                    self._buckets.popitem(last=False)
                bucket = _TokenBucket(tokens=float(limit), updated_at=now)
                self._buckets[key] = bucket
            else:
                elapsed = max(0.0, now - bucket.updated_at)
                bucket.tokens = min(
                    float(limit),
                    bucket.tokens + elapsed * refill_per_second,
                )
                bucket.updated_at = now
                self._buckets.move_to_end(key)

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return RateLimitDecision(
                    allowed=True,
                    limit=limit,
                    remaining=max(0, math.floor(bucket.tokens)),
                    retry_after_seconds=0,
                )

            retry_after = max(
                1,
                math.ceil((1.0 - bucket.tokens) / refill_per_second),
            )
            return RateLimitDecision(
                allowed=False,
                limit=limit,
                remaining=0,
                retry_after_seconds=retry_after,
            )

    def _discard_inactive_buckets(self, now: float) -> None:
        stale_before = now - self._window_seconds
        while self._buckets:
            _, bucket = next(iter(self._buckets.items()))
            if bucket.updated_at > stale_before:
                break
            self._buckets.popitem(last=False)


def rate_limit_category(method: str, path: str) -> RateLimitCategory | None:
    normalized_method = method.upper()
    if normalized_method == "POST" and path == "/api/jobs":
        return "uploads"
    if normalized_method == "GET" and path == "/api/admin/ocr-test/session":
        # Credential probing shares the upload budget it guards.
        return "uploads"
    if normalized_method == "POST" and _RECOMMENDATION_PATH.fullmatch(path):
        return "recommendations"
    if normalized_method == "POST" and path == "/api/benchmarks/run":
        return "benchmarks"
    if (
        normalized_method == "GET"
        and _BENCHMARK_IMPORT_RECOVERY_PATH.fullmatch(path)
    ):
        return "data_transfers"
    if (normalized_method, path) in _DATA_TRANSFER_ROUTES:
        return "data_transfers"
    return None


def request_rate_limit_identity(
    request: Request,
    *,
    trust_proxy_headers: bool,
) -> str:
    if trust_proxy_headers:
        connecting_ip = request.headers.get(CONNECTING_IP_HEADER)
        if connecting_ip is not None:
            try:
                normalized_ip = ip_address(connecting_ip.strip()).compressed
            except ValueError:
                pass
            else:
                return _private_identity("proxy-ip", normalized_ip)
        return _private_identity("proxy", "shared")

    client_host = request.client.host if request.client is not None else "unknown"
    return _private_identity("direct", client_host[:255])


def _private_identity(kind: str, value: str) -> str:
    return sha256(f"{kind}:{value}".encode("utf-8")).hexdigest()
