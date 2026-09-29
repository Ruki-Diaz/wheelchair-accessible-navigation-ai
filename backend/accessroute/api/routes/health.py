"""Health check endpoint for service observability."""

from typing import Any, Dict
from fastapi import APIRouter, Depends

from accessroute.api.dependencies import get_regional_cache
from accessroute.graph.regional_cache import RegionalGraphCache

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=Dict[str, Any], summary="Service Health & Diagnostic Status")
def get_health_status(cache: RegionalGraphCache = Depends(get_regional_cache)) -> Dict[str, Any]:
    """Return high-level service status without triggering expensive external API calls."""
    cached_regions = cache.list_regions()
    return {
        "status": "healthy",
        "service": "accessroute-ai",
        "version": "1.0.0",
        "stage": "Stage 6 — FastAPI Routing Service & Test Interface",
        "routing_engine": {
            "status": "operational",
            "cached_regions_count": len(cached_regions),
        },
    }
