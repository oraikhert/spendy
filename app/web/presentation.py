"""Shared server-rendered money presentation."""
from decimal import Decimal


def money(value, currency="", *, show_plus=True):
    if value is None:
        return "Not specified"
    amount = Decimal(value)
    sign = "−" if amount < 0 else "+" if amount > 0 and show_plus else ""
    return f"{sign}{abs(amount):,.2f} {currency or ''}".strip()
