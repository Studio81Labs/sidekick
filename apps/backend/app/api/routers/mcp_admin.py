"""MCP administration transport endpoints."""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.application.mcp_admin import McpAdminService
from app.mcp_access import (
    CreateMcpPrincipalRequest,
    McpAccessConfig,
    McpIssuedPrincipal,
    McpPrincipalList,
    McpPrincipalSummary,
)


def create_mcp_admin_router(runtime: McpAdminService) -> APIRouter:
    """Build the MCP administration router with application-owned operations."""

    router = APIRouter()

    @router.get(
        "/api/mcp/config",
        operation_id="mcp_config_get",
        response_model=McpAccessConfig,
    )
    def get_mcp_access_config() -> McpAccessConfig:
        return runtime.get_config()

    @router.get(
        "/api/mcp/principals",
        operation_id="mcp_principals_list",
        response_model=McpPrincipalList,
    )
    async def list_mcp_principals() -> McpPrincipalList:
        return await runtime.list_principals()

    @router.post(
        "/api/mcp/principals",
        operation_id="mcp_principals_create",
        response_model=McpIssuedPrincipal,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_mcp_principal(
        request: CreateMcpPrincipalRequest,
    ) -> JSONResponse:
        try:
            issued = await runtime.create_principal(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=issued.model_dump(mode="json"),
            headers={"Cache-Control": "no-store"},
        )

    @router.post(
        "/api/mcp/principals/{principal_id}/rotate",
        operation_id="mcp_principal_rotate",
        response_model=McpIssuedPrincipal,
        status_code=status.HTTP_201_CREATED,
    )
    async def rotate_mcp_principal(principal_id: str) -> JSONResponse:
        try:
            issued = await runtime.rotate_principal(principal_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=issued.model_dump(mode="json"),
            headers={"Cache-Control": "no-store"},
        )

    @router.delete(
        "/api/mcp/principals/{principal_id}",
        operation_id="mcp_principal_revoke",
        response_model=McpPrincipalSummary,
    )
    async def revoke_mcp_principal(principal_id: str) -> McpPrincipalSummary:
        try:
            return await runtime.revoke_principal(principal_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
