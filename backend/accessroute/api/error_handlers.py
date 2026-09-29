"""FastAPI custom exception handlers mapping domain errors to structured HTTP responses."""

import logging
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from accessroute.api.schemas.errors import APIErrorResponse, ErrorDetail
from accessroute.graph.errors import (
    AccessRouteError,
    CoordinateValidationError,
    GraphAcquisitionError,
    NetworkDownloadError,
    NoPedestrianNetworkError,
    RouteRegionTooLargeError,
)

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """Register domain and validation exception handlers on the FastAPI application."""

    @app.exception_handler(CoordinateValidationError)
    async def coordinate_validation_handler(request: Request, exc: CoordinateValidationError):
        logger.warning("Coordinate validation error on %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=APIErrorResponse(
                error_code="INVALID_COORDINATES",
                message=str(exc),
            ).model_dump(),
        )

    @app.exception_handler(RouteRegionTooLargeError)
    async def region_too_large_handler(request: Request, exc: RouteRegionTooLargeError):
        logger.warning("Region too large error on %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=APIErrorResponse(
                error_code="REGION_TOO_LARGE",
                message=str(exc),
            ).model_dump(),
        )

    @app.exception_handler(NoPedestrianNetworkError)
    async def no_network_handler(request: Request, exc: NoPedestrianNetworkError):
        logger.warning("No pedestrian network found on %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=APIErrorResponse(
                error_code="NO_PEDESTRIAN_NETWORK",
                message=str(exc),
            ).model_dump(),
        )

    @app.exception_handler(NetworkDownloadError)
    async def network_download_handler(request: Request, exc: NetworkDownloadError):
        logger.error("External OSM download error on %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=APIErrorResponse(
                error_code="EXTERNAL_PROVIDER_UNAVAILABLE",
                message="OpenStreetMap network acquisition service timed out or was temporarily unavailable. Please retry.",
            ).model_dump(),
        )

    @app.exception_handler(GraphAcquisitionError)
    async def acquisition_handler(request: Request, exc: GraphAcquisitionError):
        logger.error("Graph acquisition error on %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=APIErrorResponse(
                error_code="GRAPH_ACQUISITION_FAILED",
                message=str(exc),
            ).model_dump(),
        )

    @app.exception_handler(AccessRouteError)
    async def domain_error_handler(request: Request, exc: AccessRouteError):
        logger.warning("Domain error on %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=APIErrorResponse(
                error_code="DOMAIN_ERROR",
                message=str(exc),
            ).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning("Request validation failed on %s: %s", request.url.path, exc)
        details = [
            ErrorDetail(
                field=" -> ".join(str(loc) for loc in err.get("loc", [])),
                message=err.get("msg", "Invalid value"),
            )
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=APIErrorResponse(
                error_code="VALIDATION_ERROR",
                message="The request body or query parameters failed schema validation.",
                details=details,
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled server error on %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=APIErrorResponse(
                error_code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred while processing the request.",
            ).model_dump(),
        )
