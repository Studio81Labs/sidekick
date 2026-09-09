from pathlib import Path

from app.bootstrap import create_openapi_document
from app.config import Settings


EXPECTED_OPERATION_IDS = {
    ("DELETE", "/api/admin/ocr/jobs/{job_id}"): "admin_ocr_job_delete",
    ("DELETE", "/api/mcp/principals/{principal_id}"): "mcp_principal_revoke",
    ("GET", "/api/admin/ocr/backups/export"): "admin_ocr_backups_export",
    ("GET", "/api/admin/ocr/benchmarks"): "admin_ocr_benchmarks_get",
    ("GET", "/api/admin/ocr/benchmarks/export"): "admin_ocr_benchmarks_export",
    ("GET", "/api/admin/ocr/benchmarks/imports/{request_id}"): (
        "admin_ocr_benchmark_import_get"
    ),
    ("GET", "/api/admin/ocr/benchmarks/{report_id}"): (
        "admin_ocr_benchmark_report_get"
    ),
    ("GET", "/api/admin/ocr/history"): "admin_ocr_history_get",
    ("GET", "/api/admin/ocr/jobs"): "admin_ocr_jobs_list",
    ("GET", "/api/admin/ocr/jobs/{job_id}"): "admin_ocr_job_get",
    ("GET", "/api/admin/ocr/jobs/{job_id}/image"): "admin_ocr_job_image_get",
    ("GET", "/api/admin/ocr/session"): "admin_ocr_session_get",
    ("GET", "/api/health"): "health_get",
    ("GET", "/api/mcp/config"): "mcp_config_get",
    ("GET", "/api/mcp/principals"): "mcp_principals_list",
    ("GET", "/api/pipeline"): "pipeline_get",
    ("POST", "/api/admin/ocr/backups/restore"): "admin_ocr_backups_restore",
    ("POST", "/api/admin/ocr/benchmarks/import"): "admin_ocr_benchmarks_import",
    ("POST", "/api/admin/ocr/benchmarks/run"): "admin_ocr_benchmarks_run",
    ("POST", "/api/admin/ocr/jobs"): "admin_ocr_jobs_create",
    ("POST", "/api/admin/ocr/jobs/{job_id}/approve"): "admin_ocr_job_approve",
    ("POST", "/api/mcp/principals"): "mcp_principals_create",
    ("POST", "/api/mcp/principals/{principal_id}/rotate"): "mcp_principal_rotate",
    ("PUT", "/api/admin/ocr/history"): "admin_ocr_history_archive",
    ("PUT", "/api/admin/ocr/jobs/{job_id}/benchmark"): (
        "admin_ocr_job_benchmark_update"
    ),
    ("PUT", "/api/admin/ocr/jobs/{job_id}/metadata"): (
        "admin_ocr_job_metadata_update"
    ),
}


def openapi_document(tmp_path: Path) -> dict:
    return create_openapi_document(Settings(data_dir=tmp_path))


def test_public_operation_ids_are_unique_and_stable(tmp_path: Path) -> None:
    document = openapi_document(tmp_path)
    operation_ids = {
        (method.upper(), path): operation["operationId"]
        for path, path_item in document["paths"].items()
        for method, operation in path_item.items()
    }

    assert operation_ids == EXPECTED_OPERATION_IDS
    assert len(set(operation_ids.values())) == len(operation_ids)


def test_health_response_schema_is_explicit(tmp_path: Path) -> None:
    document = openapi_document(tmp_path)
    response_schema = document["paths"]["/api/health"]["get"]["responses"]["200"]
    health_schema = document["components"]["schemas"]["HealthResponse"]

    assert response_schema["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthResponse"
    }
    assert health_schema["required"] == [
        "status",
        "environment",
        "parser_provider",
    ]
    assert health_schema["properties"]["status"] == {
        "const": "ok",
        "title": "Status",
        "type": "string",
    }
    assert health_schema["properties"]["environment"] == {
        "enum": ["local", "staging", "production"],
        "title": "Environment",
        "type": "string",
    }


def test_binary_and_markdown_response_contracts_are_explicit(tmp_path: Path) -> None:
    document = openapi_document(tmp_path)

    binary_schema = {"schema": {"type": "string", "format": "binary"}}
    expected_content = {
        ("/api/admin/ocr/jobs/{job_id}/image", "image/gif"): binary_schema,
        ("/api/admin/ocr/jobs/{job_id}/image", "image/jpeg"): binary_schema,
        ("/api/admin/ocr/jobs/{job_id}/image", "image/png"): binary_schema,
        ("/api/admin/ocr/jobs/{job_id}/image", "image/webp"): binary_schema,
        ("/api/admin/ocr/backups/export", "application/zip"): binary_schema,
        ("/api/admin/ocr/benchmarks/export", "application/zip"): binary_schema,
    }

    actual_content = {
        (path, content_type): schema
        for path, content_type, schema in (
            (path, content_type, schema)
            for path in (
                "/api/admin/ocr/jobs/{job_id}/image",
                "/api/admin/ocr/backups/export",
                "/api/admin/ocr/benchmarks/export",
            )
            for content_type, schema in document["paths"][path]["get"]["responses"][
                "200"
            ]["content"].items()
        )
    }

    assert actual_content == expected_content
