"""Focused coverage for the MCP administration application boundary."""

import asyncio
from dataclasses import replace
from typing import cast

from app.api.dependencies import McpAdminRuntime
from app.application.mcp_admin import McpAdminService
from app.mcp_access import (
    CreateMcpPrincipalRequest,
    McpAccessConfig,
    McpIssuedPrincipal,
    McpPrincipalList,
    McpPrincipalSummary,
)


def test_mcp_admin_runtime_compatibility_export_preserves_object_identity() -> None:
    assert McpAdminRuntime is McpAdminService


def test_mcp_admin_service_preserves_callbacks_and_replacement() -> None:
    config = cast(McpAccessConfig, object())
    principals = cast(McpPrincipalList, object())
    issued = cast(McpIssuedPrincipal, object())
    summary = cast(McpPrincipalSummary, object())
    request = cast(CreateMcpPrincipalRequest, object())
    calls: list[tuple[str, object | None]] = []

    def get_config() -> McpAccessConfig:
        calls.append(("config", None))
        return config

    async def list_principals() -> McpPrincipalList:
        calls.append(("list", None))
        return principals

    async def create_principal(
        received: CreateMcpPrincipalRequest,
    ) -> McpIssuedPrincipal:
        calls.append(("create", received))
        return issued

    async def rotate_principal(principal_id: str) -> McpIssuedPrincipal:
        calls.append(("rotate", principal_id))
        return issued

    async def revoke_principal(principal_id: str) -> McpPrincipalSummary:
        calls.append(("revoke", principal_id))
        return summary

    service = McpAdminService(
        get_config=get_config,
        list_principals=list_principals,
        create_principal=create_principal,
        rotate_principal=rotate_principal,
        revoke_principal=revoke_principal,
    )

    async def exercise() -> None:
        assert await service.list_principals() is principals
        assert await service.create_principal(request) is issued
        assert await service.rotate_principal("mcp_1") is issued
        assert await service.revoke_principal("mcp_1") is summary

    assert service.get_config() is config
    asyncio.run(exercise())
    assert calls == [
        ("config", None),
        ("list", None),
        ("create", request),
        ("rotate", "mcp_1"),
        ("revoke", "mcp_1"),
    ]
    assert replace(service, get_config=lambda: config).get_config() is config
