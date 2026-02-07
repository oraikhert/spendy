"""API v1 routes"""
from fastapi import APIRouter
from app.api.v1 import auth

api_router = APIRouter()

# Include route modules
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
