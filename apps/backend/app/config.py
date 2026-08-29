import re
from functools import lru_cache
from ipaddress import AddressValueError, IPv4Address, IPv6Address
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import SplitResult, urlsplit

import idna
from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ocr_layouts import OCR_CV_LAYOUT_PROFILE_IDS

Threshold = Annotated[float, Field(ge=0, le=1)]
PIPELINE_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")

KNOWN_PARSER_PROVIDERS = frozenset({"mock", "llm_vision", "ocr_cv", "auto"})
OCR_CV_LAYOUT_PROFILES = OCR_CV_LAYOUT_PROFILE_IDS
KNOWN_RECOMMENDATION_PROVIDERS = frozenset(
    {"rule_based", "mock", "local_solver", "external_solver", "llm_advice"}
)
KNOWN_LOCAL_SOLVER_ENGINES = frozenset({"local_ev", "postflop_solver"})

DEFAULT_POSTFLOP_OOP_RANGE = "66+,A8s+,A5s-A4s,AJo+,K9s+,KQo,QTs+,JTs,96s+,85s+,75s+,65s,54s"
DEFAULT_POSTFLOP_IP_RANGE = (
    "QQ-22,AQs-A2s,ATo+,K5s+,KJo+,Q8s+,J8s+,T7s+,96s+,86s+,75s+,64s+,53s+"
)


def _looks_like_browser_ipv4(hostname: str) -> bool:
    parts = hostname.split(".")
    if parts[-1] == "":
        parts.pop()
    if not parts:
        return False
    last_part = parts[-1].lower()
    if last_part.isascii() and last_part.isdigit():
        return True
    if last_part.startswith("0x"):
        digits = last_part[2:]
        return not digits or all(
            character in "0123456789abcdef" for character in digits
        )
    return False


def normalize_https_authority(parsed_url: SplitResult) -> str:
    if parsed_url.scheme.lower() != "https" or not parsed_url.hostname:
        raise ValueError("URL must include an HTTPS hostname")
    try:
        port = parsed_url.port
    except ValueError as exc:
        raise ValueError("URL port is invalid") from exc
    hostname = parsed_url.hostname
    if ":" in hostname:
        try:
            authority = f"[{IPv6Address(hostname).compressed}]"
        except AddressValueError as exc:
            raise ValueError("URL hostname is invalid") from exc
    else:
        try:
            authority = str(IPv4Address(hostname))
        except AddressValueError:
            if _looks_like_browser_ipv4(hostname):
                raise ValueError("URL hostname is invalid")
            try:
                authority = idna.encode(
                    hostname,
                    uts46=True,
                    transitional=False,
                ).decode("ascii")
            except idna.IDNAError as exc:
                raise ValueError("URL hostname is invalid") from exc
    if port not in {None, 443}:
        authority = f"{authority}:{port}"
    return authority


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="POKER_",
        env_nested_delimiter="__",
        extra="ignore",
        hide_input_in_errors=True,
    )

    data_dir: Path = Field(default=Path("data"))
    deployment_environment: Literal["local", "staging", "production"] = "local"
    data_volume_id: str | None = Field(
        default=None,
        min_length=16,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    access_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    parser_provider: str = Field(default="mock")
    parser_layout_profile: str = Field(
        default="generic",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    parser_enabled_providers: list[str] = Field(default_factory=list, max_length=16)
    parser_enabled_layout_profiles: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    parser_auto_approve_enabled: bool = Field(default=False)
    parser_auto_approve_thresholds: dict[str, Threshold] = Field(
        default_factory=lambda: {
            "hero_cards": 0.98,
            "board_cards": 0.98,
            "pot_size": 0.95,
            "street": 0.99,
        }
    )
    recommendation_provider: str = Field(default="rule_based")
    recommendation_enabled_providers: list[str] = Field(
        default_factory=list,
        max_length=16,
    )
    external_parser_url: str | None = Field(default=None)
    external_parser_bearer_token: SecretStr | None = Field(default=None)
    external_provider_url: str | None = Field(default=None)
    external_provider_bearer_token: SecretStr | None = Field(default=None)
    llm_advice_url: str | None = Field(default=None)
    llm_advice_bearer_token: SecretStr | None = Field(default=None)
    external_request_timeout_seconds: float = Field(default=60.0, gt=0)
    local_solver_command: str | None = Field(default=None)
    local_solver_engine: str = Field(default="postflop_solver")
    local_solver_enabled_engines: list[str] = Field(
        default_factory=list,
        max_length=16,
    )
    local_solver_timeout_seconds: float = Field(default=120.0, gt=0)
    postflop_solver_command: str = Field(default="poker-postflop-solver")
    postflop_solver_fallback_enabled: bool = Field(default=True)
    postflop_solver_max_iterations: int = Field(default=400, gt=0)
    postflop_solver_target_exploitability: float = Field(default=0.01, gt=0, le=1)
    postflop_solver_max_memory_mb: int = Field(default=768, gt=0)
    postflop_solver_bet_sizes: str = Field(default="70%")
    postflop_solver_raise_sizes: str = Field(default="2.5x")
    postflop_solver_rake_rate: float = Field(default=0, ge=0, le=1)
    postflop_solver_rake_cap: float = Field(default=0, ge=0)
    postflop_solver_range_mode: Literal["contextual", "configured"] = "contextual"
    postflop_solver_oop_range: str = Field(default=DEFAULT_POSTFLOP_OOP_RANGE)
    postflop_solver_ip_range: str = Field(default=DEFAULT_POSTFLOP_IP_RANGE)
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_dataset_upload_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    max_backup_upload_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    api_rate_limit_enabled: bool = Field(default=True)
    api_rate_limit_uploads_per_minute: int = Field(default=120, gt=0, le=10_000)
    api_rate_limit_benchmarks_per_minute: int = Field(default=6, gt=0, le=10_000)
    api_rate_limit_data_transfers_per_minute: int = Field(default=6, gt=0, le=10_000)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    proxy_shared_secret: SecretStr | None = Field(default=None)
    admin_ocr_test_enabled: bool = Field(default=False)
    admin_ocr_test_token: SecretStr | None = Field(default=None)
    mcp_enabled: bool = Field(default=False)
    mcp_public_url: str | None = Field(default=None)
    mcp_allowed_origins: list[str] = Field(default_factory=list)
    mcp_allow_writes: bool = Field(default=False)
    mcp_read_calls_per_minute: int = Field(default=60, gt=0, le=10_000)
    mcp_write_calls_per_minute: int = Field(default=10, gt=0, le=10_000)
    sentry_dsn: SecretStr | None = Field(default=None)
    sentry_environment: str = Field(
        default="local",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    sentry_release: str | None = Field(default=None, min_length=1, max_length=128)
    sentry_error_sample_rate: Threshold = 1.0

    @field_validator("access_log_level", mode="before")
    @classmethod
    def normalize_access_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("parser_layout_profile", mode="before")
    @classmethod
    def normalize_parser_layout_profile(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator(
        "parser_enabled_providers",
        "parser_enabled_layout_profiles",
        "recommendation_enabled_providers",
        "local_solver_enabled_engines",
    )
    @classmethod
    def validate_enabled_pipeline_values(
        cls,
        value: list[str],
        info: ValidationInfo,
    ) -> list[str]:
        known_values = {
            "parser_enabled_providers": KNOWN_PARSER_PROVIDERS,
            "recommendation_enabled_providers": KNOWN_RECOMMENDATION_PROVIDERS,
            "local_solver_enabled_engines": KNOWN_LOCAL_SOLVER_ENGINES,
        }.get(info.field_name)
        normalized: list[str] = []
        for item in value:
            candidate = item.strip().lower()
            if known_values is not None and candidate not in known_values:
                raise ValueError(
                    f"{info.field_name} contains unknown plugin ID: {item}"
                )
            if (
                info.field_name == "parser_enabled_layout_profiles"
                and (
                    len(candidate) > 64
                    or PIPELINE_ID_PATTERN.fullmatch(candidate) is None
                )
            ):
                raise ValueError(
                    f"{info.field_name} contains invalid layout profile ID: {item}"
                )
            if candidate not in normalized:
                normalized.append(candidate)
        return normalized

    @field_validator(
        "external_parser_bearer_token",
        "external_provider_bearer_token",
        "llm_advice_bearer_token",
        "proxy_shared_secret",
        "admin_ocr_test_token",
        "sentry_dsn",
        mode="before",
    )
    @classmethod
    def normalize_optional_secret(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator(
        "external_parser_bearer_token",
        "external_provider_bearer_token",
        "llm_advice_bearer_token",
        "admin_ocr_test_token",
    )
    @classmethod
    def validate_bearer_token(
        cls,
        value: SecretStr | None,
    ) -> SecretStr | None:
        if value is None:
            return value
        token = value.get_secret_value()
        if not token.isascii():
            raise ValueError("bearer tokens must contain ASCII characters only")
        if any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in token
        ):
            raise ValueError("bearer tokens must not contain whitespace or control characters")
        return value

    @field_validator("proxy_shared_secret")
    @classmethod
    def validate_proxy_shared_secret(
        cls,
        value: SecretStr | None,
    ) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("proxy_shared_secret must contain at least 32 characters")
        return value

    @field_validator("admin_ocr_test_token")
    @classmethod
    def validate_admin_ocr_test_token(
        cls,
        value: SecretStr | None,
    ) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("admin_ocr_test_token must contain at least 32 characters")
        return value

    @field_validator("sentry_release", mode="before")
    @classmethod
    def validate_sentry_release(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized:
            return None
        if not normalized.isascii() or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in normalized
        ):
            raise ValueError(
                "sentry_release must contain printable ASCII without whitespace"
            )
        return normalized

    @model_validator(mode="after")
    def validate_authenticated_external_urls(self) -> Self:
        if self.admin_ocr_test_enabled and self.admin_ocr_test_token is None:
            raise ValueError(
                "POKER_ADMIN_OCR_TEST_TOKEN is required when "
                "POKER_ADMIN_OCR_TEST_ENABLED is true"
            )
        if (
            self.admin_ocr_test_token is not None
            and self.proxy_shared_secret is not None
            and self.admin_ocr_test_token.get_secret_value()
            == self.proxy_shared_secret.get_secret_value()
        ):
            raise ValueError(
                "POKER_ADMIN_OCR_TEST_TOKEN must differ from POKER_PROXY_SHARED_SECRET"
            )
        authenticated_urls = (
            (
                "POKER_EXTERNAL_PARSER_URL",
                self.external_parser_url,
                self.external_parser_bearer_token,
            ),
            (
                "POKER_EXTERNAL_PROVIDER_URL",
                self.external_provider_url,
                self.external_provider_bearer_token,
            ),
            (
                "POKER_LLM_ADVICE_URL",
                self.llm_advice_url,
                self.llm_advice_bearer_token,
            ),
        )
        for field_name, url, token in authenticated_urls:
            if token is not None and url is not None and urlsplit(url).scheme.lower() != "https":
                raise ValueError(f"{field_name} must use HTTPS when its bearer token is configured")
        if self.sentry_dsn is not None:
            dsn = urlsplit(self.sentry_dsn.get_secret_value())
            if (
                dsn.scheme.lower() != "https"
                or not dsn.hostname
                or not dsn.username
                or not dsn.path.strip("/")
                or dsn.query
                or dsn.fragment
            ):
                raise ValueError(
                    "POKER_SENTRY_DSN must be a complete HTTPS Sentry DSN"
                )
        if self.mcp_allow_writes and self.deployment_environment != "staging":
            raise ValueError("POKER_MCP_ALLOW_WRITES is supported only in staging")
        if self.mcp_enabled:
            if self.deployment_environment not in {"staging", "production"}:
                raise ValueError(
                    "POKER_MCP_ENABLED requires a staging or production deployment"
                )
            if self.mcp_public_url is None:
                raise ValueError("POKER_MCP_PUBLIC_URL is required when MCP is enabled")
            parsed_mcp_url = urlsplit(self.mcp_public_url)
            try:
                mcp_authority = normalize_https_authority(parsed_mcp_url)
            except ValueError as exc:
                raise ValueError(
                    "POKER_MCP_PUBLIC_URL must be a credential-free HTTPS URL "
                    "with the exact path /mcp"
                ) from exc
            if (
                "*" in parsed_mcp_url.netloc
                or parsed_mcp_url.username
                or parsed_mcp_url.password
                or parsed_mcp_url.path != "/mcp"
                or parsed_mcp_url.query
                or parsed_mcp_url.fragment
            ):
                raise ValueError(
                    "POKER_MCP_PUBLIC_URL must be a credential-free HTTPS URL "
                    "with the exact path /mcp"
                )
            self.mcp_public_url = f"https://{mcp_authority}/mcp"
        normalized_mcp_origins: list[str] = []
        for origin in self.mcp_allowed_origins:
            parsed_origin = urlsplit(origin)
            try:
                origin_authority = normalize_https_authority(parsed_origin)
            except ValueError as exc:
                raise ValueError(
                    "POKER_MCP_ALLOWED_ORIGINS must contain exact HTTPS origins"
                ) from exc
            if (
                "*" in parsed_origin.netloc
                or parsed_origin.username
                or parsed_origin.password
                or parsed_origin.path not in {"", "/"}
                or parsed_origin.query
                or parsed_origin.fragment
            ):
                raise ValueError(
                    "POKER_MCP_ALLOWED_ORIGINS must contain exact HTTPS origins"
                )
            normalized_mcp_origins.append(f"https://{origin_authority}")
        if len(set(normalized_mcp_origins)) != len(normalized_mcp_origins):
            raise ValueError("POKER_MCP_ALLOWED_ORIGINS must not contain duplicates")
        self.mcp_allowed_origins = normalized_mcp_origins
        return self


@lru_cache
def get_settings() -> Settings:
    # Keep direct Settings(...) construction deterministic for tests and tools;
    # only the application-level loader reads the working-directory .env file.
    return Settings(_env_file=".env")
