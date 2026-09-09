"""Web routes for Jinja2 + HTMX pages"""
from fastapi import APIRouter
from app.web import auth, dashboard, transactions, workspace_invitations, workspaces

web_router = APIRouter()

# Include web route modules
web_router.include_router(auth.router, prefix="/auth", tags=["web-auth"])
web_router.include_router(dashboard.router)
web_router.include_router(transactions.router)

web_router.include_router(workspaces.router)
web_router.include_router(workspace_invitations.router)
