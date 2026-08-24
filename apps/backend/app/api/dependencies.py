"""Explicit runtime dependencies for HTTP transport adapters.

The application factory wires concrete settings, stores, and plugins into this
container. Routers receive only the use-case callables they need.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.application.benchmarks import (
    BenchmarkDatasetExport,
    BenchmarkImportStatus,
    BenchmarkService as BenchmarksRuntime,
)
from app.application.jobs import (
    JobHistoryService as HistoryRuntime,
    JobUploadPipelineRequest,
    JobUploadRequest,
    JobUploadService as JobsUploadRuntime,
)
from app.application.training import (
    TrainingProgressQuery,
    TrainingService as TrainingRuntime,
)
from app.domain.pipeline import PipelineCapabilities, PipelineSelection
from app.domain.poker import CanonicalState
from app.domain.health import HealthResponse
from app.domain.hands import (
    JobQueue,
    JobRecord,
    ScreenshotMetadataRequest,
)
from app.application.backups import ApplicationBackupExport, BackupService
from app.domain.training import TrainingDecisionRequest
from app.mcp_access import (
    CreateMcpPrincipalRequest,
    McpAccessConfig,
    McpIssuedPrincipal,
    McpPrincipalList,
    McpPrincipalSummary,
)

BACKGROUND_TASK_STATE_KEY = "poker_response_background_task_scheduled"


class PipelineCapabilitiesUnavailableError(Exception):
    """The configured pipeline cannot describe its available capabilities."""


class JobTransportNotFoundError(Exception):
    """A job resource requested through the transport is not available."""


class JobMutationConflictError(Exception):
    """A requested job mutation conflicts with its current persisted state."""


class JobUploadInputError(Exception):
    """An uploaded image or pipeline selection is not valid for processing."""


class JobUploadConflictError(Exception):
    """An upload changed state while its parser work was in progress."""


class JobUploadParserConfigurationError(Exception):
    """The selected parser cannot be configured for an uploaded image."""


class JobUploadParserProviderError(Exception):
    """The selected parser failed while processing an uploaded image."""


class JobUploadUnexpectedParserError(Exception):
    """An unexpected parser failure was recorded for an uploaded image."""


class JobRecommendationInputError(Exception):
    """A recommendation request needs more user-correctable state."""

    def __init__(self, detail: str | dict[str, list[str]]) -> None:
        super().__init__(str(detail))
        self.detail = detail


class JobRecommendationConfigurationError(Exception):
    """The configured recommendation route cannot be initialized."""


class JobRecommendationProviderError(Exception):
    """The configured recommendation provider failed while serving a request."""


class BenchmarkInputError(Exception):
    """A benchmark request contains an unsupported pipeline selection."""


class BenchmarkTransportNotFoundError(Exception):
    """A benchmark resource requested through the transport is unavailable."""


class BenchmarkConflictError(Exception):
    """A benchmark operation conflicts with the current persisted state."""


class BenchmarkDatasetInputError(Exception):
    """A benchmark dataset cannot be imported with the submitted content."""

    def __init__(self, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.status_code = status_code


class BenchmarkConfigurationError(Exception):
    """The selected benchmark parser cannot be configured."""


class ApplicationBackupTransportError(Exception):
    """A backup operation failed with a client-safe HTTP response."""

    def __init__(self, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.status_code = status_code


@dataclass(frozen=True)
class ApiRuntime:
    """Read-only dependencies shared by the first extracted API routers."""

    get_health: Callable[[], HealthResponse]
    get_pipeline_capabilities: Callable[[], PipelineCapabilities]


@dataclass(frozen=True)
class JobImage:
    """An image payload prepared by the job-read application boundary."""

    content: bytes
    media_type: str


@dataclass(frozen=True)
class JobsReadRuntime:
    """Dependencies required by read-only processing job endpoints."""

    list_jobs: Callable[[int, int], JobQueue]
    get_job: Callable[[str], JobRecord]
    get_image: Callable[[str], JobImage]


@dataclass(frozen=True)
class JobsMutationRuntime:
    """Dependencies required by processing job mutation endpoints."""

    update_metadata: Callable[[str, ScreenshotMetadataRequest], JobRecord]
    delete_job: Callable[[str], None]
    approve_job: Callable[[str, CanonicalState], JobRecord]
    record_training_decision: Callable[[str, TrainingDecisionRequest], JobRecord]


@dataclass(frozen=True)
class JobsRecommendationRuntime:
    """Dependencies required by the processing job recommendation endpoint."""

    recommend: Callable[[str, str | None], JobRecord]


BackupsRuntime = BackupService


@dataclass(frozen=True)
class McpAdminRuntime:
    """Dependencies required by the MCP administration transport endpoints."""

    get_config: Callable[[], McpAccessConfig]
    list_principals: Callable[[], Awaitable[McpPrincipalList]]
    create_principal: Callable[
        [CreateMcpPrincipalRequest],
        Awaitable[McpIssuedPrincipal],
    ]
    rotate_principal: Callable[[str], Awaitable[McpIssuedPrincipal]]
    revoke_principal: Callable[[str], Awaitable[McpPrincipalSummary]]
