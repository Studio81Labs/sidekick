"""Application backup transport contracts."""

from pydantic import BaseModel, Field


class ApplicationBackupRestoreResult(BaseModel):
    imported_jobs: int = Field(ge=0)
    reused_jobs: int = Field(ge=0)
    imported_benchmark_reports: int = Field(ge=0)
    reused_benchmark_reports: int = Field(ge=0)
    total_jobs: int = Field(ge=0)
    total_benchmark_reports: int = Field(ge=0)
