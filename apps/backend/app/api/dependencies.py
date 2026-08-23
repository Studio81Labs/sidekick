"""Explicit runtime dependencies for HTTP transport adapters.

The application factory wires concrete settings, stores, and plugins into this
container. Routers receive only the use-case callables they need.
"""

from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass

from app.domain.pipeline import PipelineCapabilities, PipelineSelection
from app.domain.poker import CanonicalState, Street
from app.domain.recommendations import RecommendationAction
from app.mcp_access import (
    CreateMcpPrincipalRequest,
    McpAccessConfig,
    McpIssuedPrincipal,
    McpPrincipalList,
    McpPrincipalSummary,
)
from app.models import (
    ArchiveJobsRequest,
    ApplicationBackupRestoreResult,
    BenchmarkDatasetImportReceipt,
    BenchmarkDatasetImportResult,
    BenchmarkOverview,
    BenchmarkReport,
    BenchmarkRunRequest,
    BenchmarkSelectionRequest,
    HealthResponse,
    JobHistory,
    JobQueue,
    JobRecord,
    ScreenshotMetadataRequest,
    TrainingDecisionRequest,
    TrainingProgress,
    TrainingReviewCertainty,
    TrainingReviewOrder,
    TrainingReviewRequest,
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
class HistoryRuntime:
    """Dependencies required by the history transport endpoints."""

    list_history: Callable[[int, int, str | None], JobHistory]
    archive_jobs: Callable[[ArchiveJobsRequest, int], JobHistory]


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


@dataclass(frozen=True)
class JobUploadPipelineRequest:
    """Pipeline selectors validated from an upload multipart request."""

    parser_provider: str | None
    parser_layout_profile: str | None
    recommendation_provider: str | None
    recommendation_engine: str | None


@dataclass(frozen=True)
class JobUploadRequest:
    """Bounded upload data passed to the synchronous processing use case."""

    original_filename: str
    image_bytes: bytes
    upload_request_id: str | None
    selection: PipelineSelection


@dataclass(frozen=True)
class JobsUploadRuntime:
    """Dependencies required by the processing job upload endpoint."""

    max_upload_bytes: int
    resolve_pipeline: Callable[[JobUploadPipelineRequest], PipelineSelection]
    process_upload: Callable[[JobUploadRequest], JobRecord]


@dataclass(frozen=True)
class BenchmarkDatasetExport:
    """A prepared parser dataset archive ready for an HTTP response."""

    content: Iterator[bytes]
    filename: str


@dataclass(frozen=True)
class BenchmarkImportStatus:
    """A persisted import receipt plus its recovery scheduling state."""

    receipt: BenchmarkDatasetImportReceipt
    should_resume: bool


@dataclass(frozen=True)
class BenchmarksRuntime:
    """Dependencies required by parser benchmark transport endpoints."""

    update_inclusion: Callable[[str, BenchmarkSelectionRequest], JobRecord]
    get_overview: Callable[[str | None, str | None], BenchmarkOverview]
    export_dataset: Callable[[str | None, str | None], BenchmarkDatasetExport]
    max_dataset_upload_bytes: int
    import_dataset: Callable[[bytes, str | None], BenchmarkDatasetImportResult]
    get_import: Callable[[str], BenchmarkImportStatus]
    resume_import: Callable[[str], None]
    get_report: Callable[[str], BenchmarkReport]
    run: Callable[[BenchmarkRunRequest | None], BenchmarkReport]


@dataclass(frozen=True)
class ApplicationBackupExport:
    """A prepared full application backup ready for an HTTP response."""

    content: Iterator[bytes]
    filename: str


@dataclass(frozen=True)
class BackupsRuntime:
    """Dependencies required by application backup transport endpoints."""

    max_upload_bytes: int
    export_backup: Callable[[], Awaitable[ApplicationBackupExport]]
    restore_backup: Callable[[bytes], ApplicationBackupRestoreResult]


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


@dataclass(frozen=True)
class TrainingProgressQuery:
    """Validated filters passed from HTTP transport to training aggregation."""

    review_order: TrainingReviewOrder
    review_street: Street | None
    review_certainty: TrainingReviewCertainty | None
    review_position: str | None
    review_unpositioned: bool
    review_action_difference: (
        tuple[RecommendationAction, RecommendationAction] | None
    )
    lesson_order: TrainingReviewOrder
    lesson_street: Street | None
    lesson_query: str | None
    solver_fallback_key: str | None
    solver_route_key: str | None
    solver_unattributed: bool
    recent_street: Street | None
    recent_position: str | None
    recent_unpositioned: bool
    recent_certainty: TrainingReviewCertainty | None


@dataclass(frozen=True)
class TrainingRuntime:
    """Dependencies required by the training transport endpoints."""

    complete_review: Callable[[str, TrainingReviewRequest | None], JobRecord]
    reopen_review: Callable[[str], JobRecord]
    get_progress: Callable[[TrainingProgressQuery], TrainingProgress]
    export_lessons: Callable[
        [TrainingReviewOrder, Street | None, str | None],
        tuple[str, str],
    ]
