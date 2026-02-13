"""Exchange rates API endpoints"""
from fastapi import APIRouter, Query

from app.services.exchange_rate_service import exchange_rate_service


router = APIRouter(prefix="/exchange-rates", tags=["exchange-rates"])


@router.get("/rate")
async def get_exchange_rate(
    from_currency: str = Query(..., min_length=3, max_length=3),
    to_currency: str = Query(..., min_length=3, max_length=3),
) -> dict:
    """Get exchange rate for a currency pair (e.g., 1 USD = X AED)."""
    rate = await exchange_rate_service.get_rate(from_currency, to_currency)
    return {"from": from_currency.upper(), "to": to_currency.upper(), "rate": str(rate)}
