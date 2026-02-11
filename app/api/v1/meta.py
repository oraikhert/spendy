"""Meta API endpoints"""
from fastapi import APIRouter


router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/transaction-kinds")
async def get_transaction_kinds():
    """Get list of available transaction kinds"""
    return {
        "kinds": [
            {"value": "purchase", "label": "Purchase"},
            {"value": "topup", "label": "Top-up"},
            {"value": "refund", "label": "Refund"},
            {"value": "other", "label": "Other"}
        ]
    }
