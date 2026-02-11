"""Dashboard service"""
from datetime import datetime
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_

from app.models.transaction import Transaction
from app.models.card import Card


async def get_dashboard_summary(
    db: AsyncSession,
    date_from: datetime,
    date_to: datetime,
    account_id: int | None = None,
    card_id: int | None = None,
    base_currency: str | None = None
) -> dict:
    """
    Get dashboard summary with transaction statistics.
    
    Args:
        db: Database session
        date_from: Start date
        date_to: End date
        account_id: Optional account filter
        card_id: Optional card filter
        base_currency: Optional currency (FX conversion not implemented)
        
    Returns:
        Dictionary with summary data
    """
    # Build base query
    query = select(Transaction)
    
    filters = []
    
    if card_id:
        filters.append(Transaction.card_id == card_id)
    
    if account_id:
        query = query.join(Card, Transaction.card_id == Card.id)
        filters.append(Card.account_id == account_id)
    
    # Date filter (posting_datetime preferred, fallback to transaction_datetime)
    filters.append(
        or_(
            and_(
                Transaction.posting_datetime.isnot(None),
                Transaction.posting_datetime >= date_from,
                Transaction.posting_datetime <= date_to
            ),
            and_(
                Transaction.posting_datetime.is_(None),
                Transaction.transaction_datetime >= date_from,
                Transaction.transaction_datetime <= date_to
            )
        )
    )
    
    if filters:
        query = query.where(and_(*filters))
    
    # Execute query
    result = await db.execute(query)
    transactions = list(result.scalars().all())
    
    # Calculate statistics
    total_spent = Decimal(0)
    total_income = Decimal(0)
    by_kind = {}
    
    for transaction in transactions:
        # Simplistic categorization by amount sign
        if transaction.amount < 0:
            total_spent += abs(transaction.amount)
        else:
            total_income += transaction.amount
        
        # By kind
        kind = transaction.transaction_kind
        if kind not in by_kind:
            by_kind[kind] = {"total": Decimal(0), "count": 0}
        
        by_kind[kind]["total"] += transaction.amount
        by_kind[kind]["count"] += 1
    
    # Format by_kind for response
    by_kind_list = [
        {"kind": kind, "total": data["total"], "count": data["count"]}
        for kind, data in by_kind.items()
    ]
    
    # Get last updated transaction
    last_updated_at = None
    if transactions:
        last_updated_at = max(
            t.updated_at for t in transactions
        )
    
    return {
        "total_spent": total_spent,
        "total_income": total_income,
        "by_kind": by_kind_list,
        "count_transactions": len(transactions),
        "last_updated_at": last_updated_at
    }
