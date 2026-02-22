"""Web routes for Jinja2 + HTMX pages"""
from fastapi import APIRouter
from app.web import auth, pages, transactions

web_router = APIRouter()

# Include web route modules
web_router.include_router(auth.router, prefix="/auth", tags=["web-auth"])
web_router.include_router(pages.router, tags=["web-pages"])
web_router.include_router(transactions.router, prefix="/transactions", tags=["web-transactions"])
