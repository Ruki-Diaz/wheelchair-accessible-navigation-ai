"""API routers export."""

from accessroute.api.routes.geocoding import router as geocoding_router
from accessroute.api.routes.health import router as health_router
from accessroute.api.routes.routing import router as routing_router

__all__ = [
    "geocoding_router",
    "health_router",
    "routing_router",
]
