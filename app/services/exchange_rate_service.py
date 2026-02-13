"""Exchange rate service - fetches rates from ExchangeRate-API Open Access with in-memory TTL cache."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
from fastapi import HTTPException

from app.config import settings


class ExchangeRateService:
    """Fetches currency exchange rates with in-memory TTL cache."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[dict[str, Decimal], datetime]] = {}
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def get_rate(self, from_currency: str, to_currency: str) -> Decimal:
        """
        Get exchange rate: 1 unit of from_currency = X units of to_currency.
        """
        from_curr = from_currency.upper().strip()
        to_curr = to_currency.upper().strip()

        if from_curr == to_curr:
            return Decimal("1")

        rates = await self._get_rates(from_curr)
        if to_curr not in rates:
            raise HTTPException(
                status_code=502,
                detail="Currency not supported",
            )
        return rates[to_curr]

    async def _get_rates(self, base_currency: str) -> dict[str, Decimal]:
        """Get all rates for a base currency (cached with TTL)."""
        now = datetime.now(timezone.utc)
        if base_currency in self._cache:
            rates, expires_at = self._cache[base_currency]
            if expires_at > now:
                return rates

        url = f"{settings.EXCHANGE_RATE_API_BASE_URL.rstrip('/')}/v6/latest/{base_currency}"
        try:
            response = await self._get_client().get(url)
            response.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(
                status_code=502,
                detail="Exchange rate service unavailable",
            )

        data: dict[str, Any] = response.json()
        if data.get("result") != "success":
            raise HTTPException(
                status_code=502,
                detail="Exchange rate service unavailable",
            )

        raw_rates = data.get("rates")
        if not isinstance(raw_rates, dict):
            raise HTTPException(
                status_code=502,
                detail="Exchange rate service unavailable",
            )

        rates = {k: Decimal(str(v)) for k, v in raw_rates.items()}
        expires_at = now.timestamp() + settings.EXCHANGE_RATE_CACHE_TTL_SECONDS
        self._cache[base_currency] = (rates, datetime.fromtimestamp(expires_at, tz=timezone.utc))
        return rates

    async def aclose(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


exchange_rate_service = ExchangeRateService()
