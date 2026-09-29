"""AccessRoute AI — FastAPI Application Entrypoint.

Exposes RESTful endpoints for accessible pedestrian routing, place geocoding,
health monitoring, and serves the Stage 6 development browser test interface.
"""

from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from accessroute.api.error_handlers import register_exception_handlers
from accessroute.api.routes.account import router as account_router
from accessroute.api.routes.auth import router as auth_router
from accessroute.api.routes.community import router as community_router
from accessroute.api.routes.destinations import (
    entrance_router,
    routes_to_entrance_router,
    router as destinations_router,
)
from accessroute.api.routes.geocoding import router as geocoding_router
from accessroute.api.routes.health import router as health_router
from accessroute.api.routes.intelligence import router as intelligence_router
from accessroute.api.routes.navigation import router as navigation_router
from accessroute.api.routes.offline import router as offline_router
from accessroute.api.routes.routing import router as routing_router
from accessroute.database.session import Base, engine
import accessroute.database.models  # noqa: F401

try:
    Base.metadata.create_all(bind=engine)
    if engine.url.drivername.startswith("sqlite"):
        with engine.connect() as conn:
            from sqlalchemy import text
            cur = conn.execute(text("PRAGMA table_info(saved_places)"))
            cols = [r[1] for r in cur.fetchall()]
            if cols and "preferred_entrance_id" not in cols:
                conn.execute(text("ALTER TABLE saved_places ADD COLUMN preferred_entrance_id VARCHAR(64)"))
            if cols and "preferred_entrance_name" not in cols:
                conn.execute(text("ALTER TABLE saved_places ADD COLUMN preferred_entrance_name VARCHAR(256)"))
            conn.commit()
except Exception:
    pass

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="AccessRoute AI API",
    version="1.0.0",
    description=(
        "Explainable wheelchair-accessible navigation system operating dynamically on "
        "OpenStreetMap pedestrian networks with DEM terrain enrichment and multi-criteria A*."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/api/v1/openapi.json",
)

# CORS configuration for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Exception handlers
register_exception_handlers(app)

# Register API v1 Routers
api_v1_prefix = "/api/v1"
app.include_router(health_router, prefix=api_v1_prefix)
app.include_router(routing_router, prefix=api_v1_prefix)
app.include_router(geocoding_router, prefix=api_v1_prefix)
app.include_router(community_router, prefix=api_v1_prefix)
app.include_router(intelligence_router, prefix=api_v1_prefix)
app.include_router(navigation_router, prefix=api_v1_prefix)
app.include_router(auth_router, prefix=api_v1_prefix)
app.include_router(account_router, prefix=api_v1_prefix)
app.include_router(destinations_router, prefix=api_v1_prefix)
app.include_router(entrance_router, prefix=api_v1_prefix)
app.include_router(routes_to_entrance_router, prefix=api_v1_prefix)
app.include_router(offline_router, prefix=api_v1_prefix)

# Mount static directory for development test interface
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/manifest.webmanifest", include_in_schema=False)
def serve_manifest():
    """Serve the Web App Manifest for PWA installation."""
    manifest_file = STATIC_DIR / "manifest.webmanifest"
    if manifest_file.exists():
        return FileResponse(manifest_file, media_type="application/manifest+json")
    raise HTTPException(status_code=404, detail="Manifest not found")


@app.get("/sw.js", include_in_schema=False)
def serve_service_worker():
    """Serve the Service Worker with root scope."""
    sw_file = STATIC_DIR / "sw.js"
    if sw_file.exists():
        return FileResponse(
            sw_file,
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/"},
        )
    raise HTTPException(status_code=404, detail="Service worker not found")


@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
def serve_index():
    """Serve the Stage 6 Development Browser Interface."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {
        "service": "AccessRoute AI API",
        "status": "running",
        "docs": "/docs",
    }
