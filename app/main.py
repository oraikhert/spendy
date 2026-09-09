"""Main application entry point"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, Response

from app.config import settings
from app.core.web_session import renew_auth_cookie, same_browser_origin
from app.database import init_db
from app.api.v1 import api_router
from app.web import web_router
from app.services.exchange_rate_service import exchange_rate_service
from app.web.security import PRIVATE_HEADERS


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    print("Starting up...")
    await init_db()
    print("Database initialized")
    yield
    # Shutdown
    print("Shutting down...")
    await exchange_rate_service.aclose()


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="Family Budget Tracking Application",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def private_transaction_responses(request, call_next):
    private = any(request.url.path == prefix or request.url.path.startswith(prefix + "/") for prefix in ("/transactions", "/workspaces", "/workspace-invitations", "/dashboard"))
    invitation_private = request.url.path.startswith("/workspace-invitations/") or request.url.path.startswith(settings.API_V1_PREFIX + "/workspace-invitations/")
    private_api = request.url.path.startswith(settings.API_V1_PREFIX + "/") and any(segment in request.url.path.split("/") for segment in ("accounts", "cards", "transactions", "source-payloads", "transaction-observations", "dashboard", "workspaces", "workspace-invitations"))
    origin = request.headers.get("origin")
    if private and origin and not same_browser_origin(request, origin):
        # The legacy API CORS policy must not expose cookie-authenticated HTML/CSRF.
        response = Response("Cross-origin transaction requests are not allowed.", status_code=403)
    else:
        response = await call_next(request)
    if private:
        response.headers.update(PRIVATE_HEADERS)
        response.headers["Referrer-Policy"] = "no-referrer" if invitation_private else "same-origin"
        response.headers["Vary"] = "Cookie, HX-Request, HX-History-Restore-Request"
        response.headers["X-Content-Type-Options"] = "nosniff"
    if private_api:
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Vary"] = "Authorization, X-Workspace-ID"
    web_session = getattr(request.state, "web_session", None)
    if web_session is not None and not getattr(request.state, "suppress_session_refresh", False):
        renew_auth_cookie(response, request, web_session)
    # Token-bearing paths are required by the public API contract. Redact the
    # shared ASGI scope after routing so server access logs never receive tokens.
    if invitation_private:
        prefix = settings.API_V1_PREFIX if request.url.path.startswith(settings.API_V1_PREFIX) else ""
        redacted = f"{prefix}/workspace-invitations/[redacted]"
        request.scope["path"] = redacted
        request.scope["raw_path"] = redacted.encode("ascii")
    if b"workspace-invitations" in request.scope.get("query_string", b""):
        request.scope["query_string"] = b"next=[redacted]"
    return response

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене указать конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Configure Jinja2 templates
templates = Jinja2Templates(directory="app/templates")

# Include API routes
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# Include web routes
app.include_router(web_router)


@app.get("/")
async def root():
    """Root endpoint - redirect to login page"""
    return RedirectResponse(url="/auth/login", status_code=303)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}
