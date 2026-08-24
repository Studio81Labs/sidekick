"""Application-owned MCP administration service contracts."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.mcp_access import (
    CreateMcpPrincipalRequest,
    McpAccessConfig,
    McpIssuedPrincipal,
    McpPrincipalList,
    McpPrincipalSummary,
)


@dataclass(frozen=True)
class McpAdminService:
    """Application operations required by MCP administration transports."""

    get_config: Callable[[], McpAccessConfig]
    list_principals: Callable[[], Awaitable[McpPrincipalList]]
    create_principal: Callable[
        [CreateMcpPrincipalRequest],
        Awaitable[McpIssuedPrincipal],
    ]
    rotate_principal: Callable[[str], Awaitable[McpIssuedPrincipal]]
    revoke_principal: Callable[[str], Awaitable[McpPrincipalSummary]]


__all__ = ["McpAdminService"]
