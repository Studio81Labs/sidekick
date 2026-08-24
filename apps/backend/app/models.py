from typing import Literal

from pydantic import (
    BaseModel,
    Field,
)

from app.domain.pipeline import (
    PipelineCapabilities,
    PipelineOption,
    PipelineSelection,
)
from app.domain.poker import (
    Card,
    CompletedPostflopAction,
    CompletedPostflopActionType,
    CanonicalState,
    ParserConfidence,
    CompletedPostflopStreet,
    CompletedPostflopStreetHistory,
    DetectedState,
    FacingAction,
    NonNegativeFiniteNumber,
    PositiveFiniteNumber,
    PositiveInteger,
    ParserResult,
    PostflopAction,
    PostflopActionType,
    PostflopActor,
    PreflopAction,
    PreflopActionType,
    PreflopPosition,
    Rank,
    Street,
    Suit,
)
from app.domain.poker.models import CODE_BY_SUIT, RANKS, SUIT_BY_CODE
from app.domain.recommendations import (
    RecommendationAction,
    RecommendationRequest,
    RecommendationResult,
)
from app.domain.benchmarks import (
    BENCHMARK_FIELDS,
    BENCHMARK_IMPORT_REQUEST_ID_PATTERN,
    BENCHMARK_POSITION_ALIASES,
    BenchmarkCaseResult,
    BenchmarkDatasetImportReceipt,
    BenchmarkDatasetImportResult,
    BenchmarkFieldComparison,
    BenchmarkFieldMetric,
    BenchmarkFieldName,
    BenchmarkOverview,
    BenchmarkParserPipelineSummary,
    BenchmarkParserRouting,
    BenchmarkReport,
    BenchmarkReportSummary,
    BenchmarkRunRequest,
    BenchmarkSelectionRequest,
    NonNegativeInteger,
    UnitIntervalNumber,
    benchmark_values_match,
    normalize_benchmark_value,
)
from app.domain.training import (
    TrainingActionDifference,
    TrainingCertainty,
    TrainingCertaintySummary,
    TrainingDecision,
    TrainingDecisionRequest,
    TrainingOutcome,
    TrainingPositionSummary,
    TrainingProgress,
    TrainingRecentHand,
    TrainingReviewCertainty,
    TrainingReviewOrder,
    TrainingReviewRequest,
    TrainingSolverCoverage,
    TrainingSolverCoverageTrend,
    TrainingSolverFallbackSummary,
    TrainingSolverRouteSummary,
    TrainingStreetSummary,
    TrainingTrend,
)
from app.domain.hands import (
    ArchiveJobsRequest,
    JobHistory,
    JobQueue,
    JobRecord,
    ScreenshotMetadataRequest,
)


DeploymentEnvironment = Literal["local", "staging", "production"]
class HealthResponse(BaseModel):
    status: Literal["ok"]
    environment: DeploymentEnvironment
    parser_provider: str
    recommendation_provider: str
    recommendation_engine: str


class ApplicationBackupRestoreResult(BaseModel):
    imported_jobs: int = Field(ge=0)
    reused_jobs: int = Field(ge=0)
    imported_benchmark_reports: int = Field(ge=0)
    reused_benchmark_reports: int = Field(ge=0)
    total_jobs: int = Field(ge=0)
    total_benchmark_reports: int = Field(ge=0)
