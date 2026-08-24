"""Application backup transport endpoints."""

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import ApplicationBackupTransportError
from app.api.response_contracts import ZIP_RESPONSE_CONTENT
from app.application.backups import BackupService
from app.domain.backups import ApplicationBackupRestoreResult


def create_backups_router(runtime: BackupService) -> APIRouter:
    """Build the application backup router with application-owned operations."""

    router = APIRouter()

    @router.get(
        "/api/backups/export",
        operation_id="backups_export",
        response_class=StreamingResponse,
        responses={"200": {"content": ZIP_RESPONSE_CONTENT}},
    )
    async def export_application_backup() -> StreamingResponse:
        try:
            export = await runtime.export_backup()
        except ApplicationBackupTransportError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=str(exc),
            ) from exc
        return StreamingResponse(
            export.content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{export.filename}"'
            },
        )

    @router.post(
        "/api/backups/restore",
        operation_id="backups_restore",
        response_model=ApplicationBackupRestoreResult,
    )
    async def restore_backup(
        file: UploadFile = File(...),
    ) -> ApplicationBackupRestoreResult:
        archive_bytes = await file.read(runtime.max_upload_bytes + 1)
        if len(archive_bytes) > runtime.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail="Application backup ZIP exceeds maximum size",
            )
        try:
            return await run_in_threadpool(runtime.restore_backup, archive_bytes)
        except ApplicationBackupTransportError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=str(exc),
            ) from exc

    return router
