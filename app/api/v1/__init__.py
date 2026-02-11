"""API v1 routes"""
from fastapi import APIRouter
from app.api.v1 import (
    auth,
    accounts,
    cards,
    transactions,
    source_events,
    dashboard,
    meta
)

api_router = APIRouter()

# Include route modules
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(accounts.router)
api_router.include_router(cards.router)
api_router.include_router(transactions.router)
api_router.include_router(source_events.router)
api_router.include_router(dashboard.router)
api_router.include_router(meta.router)
