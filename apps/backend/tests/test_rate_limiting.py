import base64
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import app.bootstrap as bootstrap_module
from app.bootstrap import PROXY_SHARED_SECRET_HEADER, create_app
from app.config import Settings
from app.rate_limiting import (
    CONNECTING_IP_HEADER,
    ApiRateLimiter,
    RateLimitCategory,
    rate_limit_category,
    request_rate_limit_identity,
)
from app.storage.file_benchmark_store import FileBenchmarkStore
from api_test_support import ADMIN_OCR_TEST_HEADERS, ADMIN_OCR_TEST_TOKEN


VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg=="
)
PROXY_SECRET = "worker-to-backend-secret-value-123"


def make_client(tmp_path: Path, **overrides: object) -> TestClient:
    values: dict[str, object] = {
        "data_dir": tmp_path,
        "parser_provider": "mock",
        "recommendation_provider": "mock",
        "api_rate_limit_uploads_per_minute": 1,
        "admin_ocr_test_enabled": True,
        "admin_ocr_test_token": ADMIN_OCR_TEST_TOKEN,
    }
    values.update(overrides)
    return TestClient(create_app(Settings(**values)))


def upload(client: TestClient, *, headers: dict[str, str] | None = None):
    return client.post(
        "/api/jobs",
        files={"file": ("table.png", VALID_PNG, "image/png")},
        headers={**ADMIN_OCR_TEST_HEADERS, **(headers or {})},
    )


def identities_for_headers(
    headers: dict[str, str],
    *,
    client_host: str = "127.0.0.1",
) -> tuple[str, str]:
    app = FastAPI()

    @app.get("/")
    def read_identity(request: Request) -> dict[str, str]:
        return {
            "proxy": request_rate_limit_identity(
                request,
                trust_proxy_headers=True,
            ),
            "direct": request_rate_limit_identity(
                request,
                trust_proxy_headers=False,
            ),
        }

    client = TestClient(app, client=(client_host, 50000))
    response = client.get("/", headers=headers)
    response.raise_for_status()
    payload = response.json()
    return payload["proxy"], payload["direct"]


def test_token_bucket_rejects_until_a_token_is_replenished() -> None:
    now = [100.0]
    limiter = ApiRateLimiter(
        {
            "uploads": 2,
            "benchmarks": 2,
            "data_transfers": 2,
        },
        clock=lambda: now[0],
    )

    first = limiter.check("uploads", "client-a")
    second = limiter.check("uploads", "client-a")
    rejected = limiter.check("uploads", "client-a")

    assert (first.allowed, first.remaining) == (True, 1)
    assert (second.allowed, second.remaining) == (True, 0)
    assert rejected.allowed is False
    assert rejected.retry_after_seconds == 30

    now[0] += 30
    replenished = limiter.check("uploads", "client-a")
    assert replenished.allowed is True
    assert replenished.remaining == 0


def test_token_buckets_are_independent_by_category_and_identity() -> None:
    limiter = ApiRateLimiter(
        {
            "uploads": 1,
            "benchmarks": 1,
            "data_transfers": 1,
        }
    )

    assert limiter.check("uploads", "client-a").allowed is True
    assert limiter.check("uploads", "client-a").allowed is False
    assert limiter.check("benchmarks", "client-a").allowed is True
    assert limiter.check("uploads", "client-b").allowed is True


def test_bounded_storage_does_not_alias_distinct_client_budgets() -> None:
    limiter = ApiRateLimiter(
        {
            "uploads": 1,
            "benchmarks": 1,
            "data_transfers": 1,
        },
        max_buckets=1,
    )

    assert limiter.check("uploads", "client-a").allowed is True
    assert limiter.check("uploads", "client-a").allowed is False
    assert limiter.check("uploads", "client-b").allowed is True
    assert len(limiter._buckets) == 1


def test_limiter_discards_inactive_buckets_before_lru_eviction() -> None:
    now = [100.0]
    limiter = ApiRateLimiter(
        {
            "uploads": 1,
            "benchmarks": 1,
            "data_transfers": 1,
        },
        window_seconds=60,
        max_buckets=2,
        clock=lambda: now[0],
    )

    limiter.check("uploads", "client-a")
    limiter.check("uploads", "client-b")
    now[0] += 60
    limiter.check("uploads", "client-c")

    assert len(limiter._buckets) == 1


def test_limiter_evicts_the_least_recently_used_active_bucket() -> None:
    now = [100.0]
    limiter = ApiRateLimiter(
        {
            "uploads": 1,
            "benchmarks": 1,
            "data_transfers": 1,
        },
        max_buckets=2,
        clock=lambda: now[0],
    )

    assert limiter.check("uploads", "client-a").allowed is True
    assert limiter.check("uploads", "client-b").allowed is True
    now[0] += 1
    assert limiter.check("uploads", "client-a").allowed is False
    assert limiter.check("uploads", "client-c").allowed is True
    assert limiter.check("uploads", "client-c").allowed is False
    assert limiter.check("uploads", "client-b").allowed is True


def test_limiter_requires_a_complete_positive_policy() -> None:
    partial_policy: dict[RateLimitCategory, int] = {"uploads": 1}
    with pytest.raises(ValueError, match="every rate-limit category"):
        ApiRateLimiter(partial_policy)
    with pytest.raises(ValueError, match="must be positive"):
        ApiRateLimiter(
            {
                "uploads": 0,
                "benchmarks": 1,
                "data_transfers": 1,
            }
        )
    with pytest.raises(ValueError, match="max_buckets must be positive"):
        ApiRateLimiter(
            {
                "uploads": 1,
                "benchmarks": 1,
                "data_transfers": 1,
            },
            max_buckets=0,
        )


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("POST", "/api/jobs", "uploads"),
        ("GET", "/api/admin/ocr-test/session", "uploads"),
        ("POST", "/api/benchmarks/run", "benchmarks"),
        ("GET", "/api/backups/export", "data_transfers"),
        ("POST", "/api/backups/restore", "data_transfers"),
        ("GET", "/api/benchmarks/export", "data_transfers"),
        ("POST", "/api/benchmarks/import", "data_transfers"),
        ("GET", "/api/benchmarks/imports/import-1", "data_transfers"),
        ("GET", "/api/health", None),
        ("POST", "/api/jobs/job-1/approve", None),
        ("POST", "/api/jobs/job-1/approve/extra", None),
    ],
)
def test_rate_limit_category_matches_only_expensive_routes(
    method: str,
    path: str,
    expected: str | None,
) -> None:
    assert rate_limit_category(method, path) == expected


def test_proxy_identity_uses_validated_ip_then_a_shared_fallback() -> None:
    valid_proxy, _ = identities_for_headers(
        {CONNECTING_IP_HEADER: "2001:db8::1"}
    )
    invalid_proxy, _ = identities_for_headers(
        {CONNECTING_IP_HEADER: "not-an-ip"}
    )
    missing_proxy, _ = identities_for_headers({})

    assert valid_proxy != missing_proxy
    assert invalid_proxy == missing_proxy


def test_upload_rate_limit_returns_retry_metadata_and_cors_headers(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    first = upload(client)
    rejected = client.post(
        "/api/jobs",
        files={"file": ("table.png", VALID_PNG, "image/png")},
        headers={**ADMIN_OCR_TEST_HEADERS, "Origin": "http://localhost:5173"},
    )

    assert first.status_code == 201
    assert first.headers["x-ratelimit-limit"] == "1"
    assert first.headers["x-ratelimit-remaining"] == "0"
    assert rejected.status_code == 429
    assert rejected.json() == {
        "detail": "Rate limit exceeded for uploads",
        "retry_after_seconds": 60,
    }
    assert rejected.headers["retry-after"] == "60"
    exposed = rejected.headers["access-control-expose-headers"].lower()
    assert "retry-after" in exposed
    assert "x-ratelimit-remaining" in exposed


def test_unauthorized_request_does_not_consume_authenticated_budget(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, proxy_shared_secret=PROXY_SECRET)

    unauthorized = upload(client)
    authorized = upload(
        client,
        headers={PROXY_SHARED_SECRET_HEADER: PROXY_SECRET},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 201


def test_proxy_client_ips_receive_independent_budgets(tmp_path: Path) -> None:
    client = make_client(tmp_path, proxy_shared_secret=PROXY_SECRET)
    first_client = {
        PROXY_SHARED_SECRET_HEADER: PROXY_SECRET,
        CONNECTING_IP_HEADER: "203.0.113.10",
    }
    second_client = {
        PROXY_SHARED_SECRET_HEADER: PROXY_SECRET,
        CONNECTING_IP_HEADER: "203.0.113.11",
    }

    assert upload(client, headers=first_client).status_code == 201
    assert upload(client, headers=first_client).status_code == 429
    assert upload(client, headers=second_client).status_code == 201


def test_import_recovery_get_consumes_the_data_transfer_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(
        tmp_path,
        api_rate_limit_data_transfers_per_minute=1,
    )

    missing = client.get("/api/benchmarks/imports/missing-import")
    request_id = "pending-import"
    benchmark_store = FileBenchmarkStore(tmp_path)
    benchmark_store.begin_import(request_id, b"pending archive")
    parse_calls = 0

    def track_parse(*_args: object, **_kwargs: object) -> None:
        nonlocal parse_calls
        parse_calls += 1

    monkeypatch.setattr(
        bootstrap_module,
        "parse_parser_dataset_archive",
        track_parse,
    )

    limited = client.get(f"/api/benchmarks/imports/{request_id}")

    assert missing.status_code == 404
    assert limited.status_code == 429
    assert limited.json()["detail"] == "Rate limit exceeded for data transfers"
    assert parse_calls == 0
    assert benchmark_store.get_import(request_id).status == "pending"


def test_rate_limiting_can_be_disabled_for_trusted_local_workflows(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, api_rate_limit_enabled=False)

    assert upload(client).status_code == 201
    assert upload(client).status_code == 201
