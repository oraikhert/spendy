"""Main application entry point"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

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

# Store templates in app state for web routes
app.state.templates = templates

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
