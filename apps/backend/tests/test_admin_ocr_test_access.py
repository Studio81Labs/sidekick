import pytest

from app.application.admin_ocr_test import AdminOcrTestAccessPolicy

TOKEN = "administrative-ocr-test-token-0123456789abcdef"


def test_disabled_policy_reports_disabled_for_every_header() -> None:
    policy = AdminOcrTestAccessPolicy.disabled()

    assert policy.authorize(None) == "disabled"
    assert policy.authorize(f"Bearer {TOKEN}") == "disabled"


def test_for_token_rejects_empty_token() -> None:
    with pytest.raises(ValueError):
        AdminOcrTestAccessPolicy.for_token("")


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "Bearer",
        "Bearer ",
        f"Basic {TOKEN}",
        f"Bearer {TOKEN}x",
        f"Bearer {TOKEN[:-1]}",
        TOKEN,
    ],
)
def test_enabled_policy_rejects_missing_or_wrong_credentials(header: str | None) -> None:
    policy = AdminOcrTestAccessPolicy.for_token(TOKEN)

    assert policy.authorize(header) == "unauthorized"


@pytest.mark.parametrize(
    "header",
    [f"Bearer {TOKEN}", f"bearer {TOKEN}", f"  Bearer   {TOKEN}  "],
)
def test_enabled_policy_authorizes_matching_bearer(header: str) -> None:
    policy = AdminOcrTestAccessPolicy.for_token(TOKEN)

    assert policy.authorize(header) == "authorized"


def test_policy_does_not_retain_the_plaintext_token() -> None:
    policy = AdminOcrTestAccessPolicy.for_token(TOKEN)

    assert TOKEN.encode() not in repr(policy).encode()
    assert policy.token_digest is not None
    assert len(policy.token_digest) == 32
