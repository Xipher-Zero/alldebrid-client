import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.auth_routes import router as auth_router
from api.routes import router
from auth.middleware import enforce_authentication, enforce_general_web_security
from auth.policy import password_auth_enabled, password_auth_ready
from auth.sessions import CSRF_HEADER, session_store
from core.branding import APP_METADATA_TITLE, APP_NAME, APP_SHORT_NAME
from core.config import get_settings as _get_log_settings
from core.logging_utils import configure_logging, log_startup_banner, sanitize_exception, sanitize_log_value
from core.scheduler import start_scheduler, stop_scheduler
from core.version import read_version
from db.database import DatabaseMaintenanceActive, init_db, DB_PATH
from services.aria2_runtime import runtime as aria2_runtime
from services.transfer_service import transfer_service
from services.maintenance_gate import ApplicationMaintenanceActive

_log_cfg = _get_log_settings()
configure_logging(
    getattr(_log_cfg, "log_level", "INFO"),
    bool(getattr(_log_cfg, "log_pretty", False)),
    getattr(_log_cfg, "log_format", "plain"),
)
logger = logging.getLogger("alldebrid.main")

# persistence initialization on startup

async def _reset_stuck_downloads_sqlite():
    """Resets torrents that were stuck in 'downloading' state when the app last stopped."""
    import aiosqlite as _aiosqlite
    async with _aiosqlite.connect(DB_PATH, timeout=30) as _db:
        _db.row_factory = _aiosqlite.Row
        stuck = await (await _db.execute(
            """SELECT id, alldebrid_id, name FROM torrents
               WHERE status='downloading'
                 AND id NOT IN (SELECT DISTINCT torrent_id FROM download_files)"""
        )).fetchall()
        for row in stuck:
            await _db.execute(
                "UPDATE torrents SET status='ready', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (row["id"],),
            )
            await _db.execute(
                "INSERT INTO events (torrent_id, level, message) VALUES (?, 'warn', ?)",
                (row["id"], "Recovered stuck download on startup — re-queuing"),
            )
            logger.info("Startup: reset stuck torrent %s (%s)", row["id"], row["name"])
        await _db.commit()
    return list(stuck)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.config import get_settings as _gs
    cfg = _gs()
    password_enabled = password_auth_enabled(cfg)
    log_startup_banner(
        logger,
        version=read_version(),
        mode="Docker / Unraid",
        database="SQLite",
        download_client=("aria2 builtin" if getattr(cfg, "aria2_mode", "builtin") == "builtin" else "aria2 external"),
        web_ui=f"http://0.0.0.0:{getattr(cfg, 'port', 8080)}",
        auth=("enabled" if password_enabled else "disabled"),
    )
    if not password_enabled:
        logger.warning("HTTP authentication is disabled; restrict DebridPulse to a trusted network or authenticated reverse proxy")
    elif not password_auth_ready(cfg):
        logger.error("Username & Password authentication is enabled but not fully configured; protected access is fail-closed")

    try:
        from core.config import get_settings, apply_settings, save_settings
        from core.config_validator import validate_and_sanitise
        raw = get_settings()
        clean = validate_and_sanitise(raw)
        if clean is not raw:
            save_settings(clean)
            apply_settings(clean)
    except Exception as exc:
        logger.warning("Config validation skipped due to error: %s", sanitize_exception(exc))

    await init_db()
    try:
        stuck = await _reset_stuck_downloads_sqlite()
        for row in stuck:
            if row["alldebrid_id"]:
                asyncio.create_task(transfer_service.control.start_download(
                    row["id"], str(row["alldebrid_id"]), str(row["name"] or "")
                ))
    except Exception as exc:
        logger.warning("Startup stuck-download cleanup failed: %s", sanitize_exception(exc))

    try:
        await transfer_service.provider.import_existing()
    except Exception as exc:
        logger.warning("Initial provider import skipped: %s", sanitize_exception(exc))
    try:
        await aria2_runtime.ensure_started()
    except Exception as exc:
        logger.warning("Built-in aria2 startup skipped: %s", sanitize_exception(exc))
    try:
        await transfer_service.reconciliation.startup()
    except Exception as exc:
        logger.warning("Startup reconciliation failed: %s", sanitize_exception(exc))
    try:
        await transfer_service.aria2.housekeeping()
    except Exception as exc:
        logger.warning("Startup aria2 housekeeping failed: %s", sanitize_exception(exc))

    await start_scheduler()
    session_store.start_cleanup()
    try:
        yield
    finally:
        logger.info("Shutting down %s...", APP_NAME)
        try:
            await session_store.stop_cleanup()
        finally:
            try:
                await stop_scheduler()
            finally:
                try:
                    await aria2_runtime.stop()
                except Exception as exc:
                    logger.warning("Built-in aria2 shutdown failed: %s", sanitize_exception(exc))


class _RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max(1, int(max_bytes))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or str(scope.get("method") or "").upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
            await self.app(scope, receive, send)
            return
        # Login credentials are tiny; give the pre-auth parser a much smaller
        # ceiling than general torrent/form application requests.
        limit = min(self.max_bytes, 64 * 1024) if scope.get("path") == "/login" else self.max_bytes
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length", b"")
        try:
            if raw_length and int(raw_length) > limit:
                response = Response(content="Request body too large", status_code=413)
                await response(scope, receive, send)
                return
        except ValueError:
            pass
        seen = 0
        async def limited_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message.get("type") == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise _RequestBodyTooLarge
            return message
        try:
            await self.app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            response = Response(content="Request body too large", status_code=413)
            await response(scope, receive, send)


try:
    _MAX_REQUEST_BODY_BYTES = max(1024 * 1024, min(100 * 1024 * 1024, int(os.getenv("DEBRIDPULSE_MAX_REQUEST_BYTES", str(20 * 1024 * 1024)))))
except ValueError:
    _MAX_REQUEST_BODY_BYTES = 20 * 1024 * 1024


app = FastAPI(
    title=APP_METADATA_TITLE,
    description=(
        "Self-hosted debrid transfer manager for direct links, magnets, and torrent files. "
        "V1 includes the AllDebrid provider backend.\n\n"
        "## API structure\n\n"
        "| Prefix | Description |\n"
        "|--------|-------------|\n"
        f"| `/api/` | Native {APP_SHORT_NAME} REST API |\n\n"
        "Interactive docs: `/docs` (Swagger UI) · `/redoc` (ReDoc) · `/openapi.json`"
    ),
    version=read_version(),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


_MUTATING_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_DATABASE_WIPE_PATH = "/api/admin/database/wipe"
_AUTH_MUTATION_PATHS = {"/login", "/api/auth/logout"}


@app.middleware("http")
async def application_mutation_admission_middleware(request: Request, call_next):
    """Serialize application state changes against destructive maintenance."""
    if (
        request.method.upper() in _MUTATING_HTTP_METHODS
        and request.url.path != _DATABASE_WIPE_PATH
        and request.url.path not in _AUTH_MUTATION_PATHS
    ):
        try:
            async with transfer_service.application_operation():
                return await call_next(request)
        except ApplicationMaintenanceActive:
            return Response(
                content="Application maintenance in progress",
                status_code=503,
                headers={"Retry-After": "2"},
            )
    return await call_next(request)


@app.exception_handler(PermissionError)
async def permission_error_handler(_request: Request, _exc: PermissionError):
    """Do not turn service-layer authorization failures into HTTP 500 responses."""
    return Response(content="Forbidden", status_code=403)


@app.exception_handler(DatabaseMaintenanceActive)
async def database_maintenance_handler(_request: Request, _exc: DatabaseMaintenanceActive):
    """Fail closed rather than queue stale request work behind a destructive wipe."""
    return Response(
        content="Database maintenance in progress",
        status_code=503,
        headers={"Retry-After": "2"},
    )


@app.exception_handler(ApplicationMaintenanceActive)
async def application_maintenance_handler(_request: Request, _exc: ApplicationMaintenanceActive):
    """Reject new mutation/execution work while destructive maintenance owns admission."""
    return Response(
        content="Application maintenance in progress",
        status_code=503,
        headers={"Retry-After": "2"},
    )


app.add_middleware(RequestBodyLimitMiddleware, max_bytes=_MAX_REQUEST_BODY_BYTES)


_cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", CSRF_HEADER],
    )

# ── Request-ID Middleware ──────────────────────────────────────────────────────
# Adds X-Request-ID to every response for log correlation.
# Reuses the client-provided ID if present, otherwise generates a new UUID4.

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    req_id = str(request.headers.get("X-Request-ID") or "").strip()
    if not req_id or len(req_id) > 128:
        req_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response

# ── Authentication / Browser Security ─────────────────────────────────────────
# Authentication is an outer request boundary. Browser cross-site mutation
# protection is general security and remains active even when authentication is
# intentionally disabled.

@app.middleware("http")
async def authentication_boundary_middleware(request: Request, call_next):
    return await enforce_authentication(request, call_next)


@app.middleware("http")
async def general_web_security_middleware(request: Request, call_next):
    return await enforce_general_web_security(
        request,
        call_next,
        allowed_origins=_cors_origins,
    )

app.include_router(auth_router)
app.include_router(router, prefix="/api")

# ── Static files ──────────────────────────────────────────────────────────────
_here = Path(__file__).parent
_candidates = []

_env = os.getenv("STATIC_DIR", "").strip()
if _env:
    _candidates.append(Path(_env))

_candidates.append(_here.parent / "frontend" / "static")
_candidates.append(Path("/app/frontend/static"))
_candidates.append(Path("/app/static"))


def _is_valid(p: Path) -> bool:
    return p.is_dir() and (p / "index.html").exists()


_static = next((p for p in _candidates if _is_valid(p)), None)

if _static is None:
    tried = ", ".join(str(p) for p in _candidates)
    raise RuntimeError(
        f"Frontend index.html not found. Tried: [{tried}]. "
        "Fix your Docker build or set STATIC_DIR."
    )

logger.info("Serving static files from: %s", sanitize_log_value(_static))
app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")