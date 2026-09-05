"""Main application entry point"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, Response

from app.config import settings
from app.database import init_db
from app.api.v1 import api_router
from app.web import web_router
from app.services.exchange_rate_service import exchange_rate_service


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


def external_origin(request) -> str:
    """Return the browser-facing origin when the app is behind a TLS proxy."""
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    scheme = forwarded_proto if forwarded_proto in {"http", "https"} else request.url.scheme
    return f"{scheme}://{request.url.netloc}"


@app.middleware("http")
async def private_transaction_responses(request, call_next):
    private = request.url.path == "/transactions" or request.url.path.startswith("/transactions/")
    origin = request.headers.get("origin")
    if private and origin and origin != external_origin(request):
        # The legacy API CORS policy must not expose cookie-authenticated HTML/CSRF.
        response = Response("Cross-origin transaction requests are not allowed.", status_code=403)
    else:
        response = await call_next(request)
    if private:
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Vary"] = "Cookie, HX-Request, HX-History-Restore-Request"
        response.headers["X-Content-Type-Options"] = "nosniff"
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
