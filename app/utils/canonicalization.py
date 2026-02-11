"""Canonicalization utilities"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.transaction import Transaction
from app.models.source_event import SourceEvent
from app.models.transaction_source_link import TransactionSourceLink


async def canonicalize_transaction(
    db: AsyncSession,
    transaction: Transaction
) -> Transaction:
    """
    Update canonical fields based on linked SourceEvents priority rules.
    
    Priority:
    1. PDF statement (posting_datetime, amount, currency)
    2. SMS/screenshot (transaction_datetime)
    3. Description: statement description > longest non-empty from other sources
    
    Args:
        db: Database session
        transaction: Transaction to canonicalize
        
    Returns:
        Updated transaction
    """
    # Load linked source events
    query = (
        select(TransactionSourceLink)
        .where(TransactionSourceLink.transaction_id == transaction.id)
        .options(selectinload(TransactionSourceLink.source_event))
    )
    result = await db.execute(query)
    links = result.scalars().all()
    
    if not links:
        return transaction
    
    # Separate sources by type
    pdf_sources = []
    sms_screenshot_sources = []
    other_sources = []
    
    for link in links:
        source = link.source_event
        if source.source_type == "pdf_statement":
            pdf_sources.append(source)
        elif source.source_type in {"sms_text", "sms_screenshot", "bank_screenshot", "telegram_text"}:
            sms_screenshot_sources.append(source)
        else:
            other_sources.append(source)
    
    # Apply canonicalization rules
    
    # Rule 1: PDF statement for posting_datetime, amount, currency
    if pdf_sources:
        pdf_source = pdf_sources[0]  # Take first if multiple
        if pdf_source.parsed_posting_datetime:
            transaction.posting_datetime = pdf_source.parsed_posting_datetime
        if pdf_source.parsed_amount is not None:
            transaction.amount = pdf_source.parsed_amount
        if pdf_source.parsed_currency:
            transaction.currency = pdf_source.parsed_currency
    
    # Rule 2: SMS/screenshot for transaction_datetime
    if sms_screenshot_sources:
        for source in sms_screenshot_sources:
            if source.parsed_transaction_datetime:
                transaction.transaction_datetime = source.parsed_transaction_datetime
                break
    
    # Rule 3: Description - prefer statement, else longest
    description_sources = []
    
    # Check PDF for description
    if pdf_sources and pdf_sources[0].parsed_description:
        transaction.description = pdf_sources[0].parsed_description
    else:
        # Collect all descriptions from other sources
        for link in links:
            source = link.source_event
            if source.parsed_description:
                description_sources.append(source.parsed_description)
            elif source.raw_text:
                description_sources.append(source.raw_text)
        
        # Choose longest
        if description_sources:
            transaction.description = max(description_sources, key=len)
    
    return transaction
