import asyncio
import logging
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from core.branding import APP_METADATA_TITLE, APP_NAME, APP_SHORT_NAME
from core.config import get_settings as _get_log_settings
from core.logging_utils import configure_logging, log_startup_banner, sanitize_exception, sanitize_log_value
from core.scheduler import start_scheduler, stop_scheduler
from core.version import read_version
from db.database import init_db, DB_PATH
from services.aria2_runtime import runtime as aria2_runtime
from services.transfer_service import transfer_service

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
    log_startup_banner(
        logger,
        version=read_version(),
        mode="Docker / Unraid",
        database="SQLite",
        download_client=("aria2 builtin" if getattr(cfg, "aria2_mode", "builtin") == "builtin" else "aria2 external"),
        web_ui=f"http://0.0.0.0:{getattr(cfg, 'port', 8080)}",
        auth=("enabled" if getattr(cfg, "auth_username", "") and getattr(cfg, "auth_password", "") else "disabled"),
    )
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
                asyncio.create_task(transfer_service._start_download(
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
        await transfer_service.run_aria2_housekeeping()
    except Exception as exc:
        logger.warning("Startup aria2 housekeeping failed: %s", sanitize_exception(exc))

    await start_scheduler()
    yield
    logger.info("Shutting down %s...", APP_NAME)
    await stop_scheduler()
    try:
        await aria2_runtime.stop()
    except Exception as exc:
        logger.warning("Built-in aria2 shutdown failed: %s", sanitize_exception(exc))


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


@app.exception_handler(PermissionError)
async def permission_error_handler(_request: Request, _exc: PermissionError):
    """Do not turn service-layer authorization failures into HTTP 500 responses."""
    return Response(content="Forbidden", status_code=403)


_cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

# ── Request-ID Middleware ──────────────────────────────────────────────────────
# Adds X-Request-ID to every response for log correlation.
# Reuses the client-provided ID if present, otherwise generates a new UUID4.

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response

# ── Optional HTTP Basic Auth ───────────────────────────────────────────────────
# Enabled when auth_username AND auth_password are both set in config.
# Health/version/avatar remain public for health checks and UI metadata.
_AUTH_EXEMPT = {"/api/health", "/api/version", "/api/avatar"}

@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    from core.config import get_settings
    cfg = get_settings()
    username = str(getattr(cfg, "auth_username", "") or "").strip()
    password = str(getattr(cfg, "auth_password", "") or "").strip()

    # Auth disabled when either credential is empty
    if not username or not password:
        return await call_next(request)

    # Exempt health/version endpoints (e.g. Unraid health check)
    if request.url.path in _AUTH_EXEMPT:
        return await call_next(request)

    # Check Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        import base64
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8", errors="replace")
            provided_user, _, provided_pass = decoded.partition(":")
            user_ok = secrets.compare_digest(provided_user.encode(), username.encode())
            pass_ok = secrets.compare_digest(provided_pass.encode(), password.encode())
            if user_ok and pass_ok:
                if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
                    origin = str(request.headers.get("Origin", "") or "").strip()
                    if origin:
                        from urllib.parse import urlparse
                        origin_host = (urlparse(origin).netloc or "").casefold()
                        request_host = str(request.headers.get("Host", "") or "").casefold()
                        configured = {
                            urlparse(item).netloc.casefold()
                            for item in _cors_origins
                            if urlparse(item).netloc
                        }
                        if origin_host != request_host and origin_host not in configured:
                            return Response(content="Forbidden origin", status_code=403)
                return await call_next(request)
        except Exception:  # noqa: BLE001 — malformed auth header; fall through to 401
            pass

    return Response(
        content="Unauthorized",
        status_code=401,
        headers={"WWW-Authenticate": f'Basic realm="{APP_SHORT_NAME}"'},
    )

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
