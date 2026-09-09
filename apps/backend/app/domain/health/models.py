"""Health endpoint contract."""

from typing import Literal

from pydantic import BaseModel

DeploymentEnvironment = Literal["local", "staging", "production"]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    environment: DeploymentEnvironment
    parser_provider: str
