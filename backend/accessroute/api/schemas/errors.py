"""Structured API error response schemas."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Specific field or parameter validation failure."""

    field: Optional[str] = Field(None, description="Request parameter or field that triggered the error.")
    message: str = Field(..., description="Human-readable reason for the failure.")


class APIErrorResponse(BaseModel):
    """Standardized error envelope returned by AccessRoute AI API."""

    error_code: str = Field(..., description="Machine-readable domain error code.", examples=["INVALID_COORDINATES", "REGION_TOO_LARGE"])
    message: str = Field(..., description="High-level human-readable description of the error.")
    details: Optional[List[ErrorDetail]] = Field(default=None, description="Optional granular field-level diagnostics.")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Safe diagnostics, bounds, or operational limit telemetry.")
