"""Parsing utilities (stub implementation)"""
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime


def parse_text_stub(raw_text: str) -> dict:
    """
    Parse bank SMS notifications.
    
    Supported formats:
    - Purchase of AED 2.50 with Credit Card ending 3278 at MERCHANT, LOCATION...
    - Payment of AED 1,493.10 to MERCHANT with Credit Card ending 3278...
    
    Args:
        raw_text: Raw text input
        
    Returns:
        Dictionary with parsed fields
    """
    parsed = {
        "parsed_description": None,
        "parsed_amount": None,
        "parsed_currency": None,
        "parsed_transaction_datetime": None,
        "parsed_posting_datetime": None,
        "parsed_card_number": None,
        "parse_status": "parsed",
        "parse_error": None,
    }
    
    if not raw_text:
        return parsed
    
    text = raw_text.strip()
    
    # Pattern 1: Purchase of [CURRENCY] [AMOUNT] with Credit Card ending [XXXX] at [MERCHANT]
    # Pattern 2: Payment of [CURRENCY] [AMOUNT] to [MERCHANT] with Credit Card ending [XXXX]
    
    # Try to extract transaction type, amount, and currency
    # Handle amounts with commas: 1,493.10
    transaction_pattern = r'(Purchase|Payment)\s+of\s+([A-Z]{3})\s+([\d,]+(?:\.\d{2})?)'
    match = re.search(transaction_pattern, text, re.IGNORECASE)
    
    if match:
        transaction_type = match.group(1).lower()  # purchase or payment
        currency = match.group(2)
        amount_str = match.group(3).replace(',', '')  # Remove commas
        
        try:
            amount = Decimal(amount_str)
            # Purchases are negative (money spent), payments could be positive or negative
            if transaction_type == 'purchase':
                parsed["parsed_amount"] = -abs(amount)
            else:
                parsed["parsed_amount"] = -abs(amount)  # Payments to merchants are also expenses
            
            parsed["parsed_currency"] = currency
        except (InvalidOperation, ValueError) as e:
            parsed["parse_status"] = "failed"
            parsed["parse_error"] = f"Invalid amount format: {amount_str}"
            return parsed
    else:
        # Fallback: Try simple pattern matching
        amount_pattern = r'([A-Z]{3})\s+([\d,]+(?:\.\d{2})?)'
        match = re.search(amount_pattern, text)
        if match:
            try:
                currency = match.group(1)
                amount_str = match.group(2).replace(',', '')
                parsed["parsed_amount"] = -abs(Decimal(amount_str))  # Assume expense
                parsed["parsed_currency"] = currency
            except (InvalidOperation, ValueError):
                pass
    
    # Extract merchant name
    merchant = None
    
    # Pattern: "at [MERCHANT + LOCATION]" - capture everything until ". Avl" or end
    at_pattern = r'\s+at\s+(.+?)(?:\.\s*Avl|\s*$)'
    at_match = re.search(at_pattern, text, re.IGNORECASE)
    if at_match:
        merchant_raw = at_match.group(1).strip()
        # Remove trailing period if present
        merchant_raw = merchant_raw.rstrip('.')
        
        # Try to remove location suffix
        # Pattern: ", CITY" or ", CITY, COUNTRY" etc.
        # Look for the last comma followed by capitalized location name
        parts = merchant_raw.rsplit(',', 1)
        if len(parts) == 2:
            potential_location = parts[1].strip()
            # If it looks like a location (starts with capital, common location words)
            # or is all caps (like "NEW YORK", "SAN FRANCISCO", "DUBAI")
            if potential_location and (
                potential_location[0].isupper() or 
                potential_location.isupper() or
                potential_location.lower() in ['dubai', 'abu dhabi', 'sharjah']
            ):
                merchant = parts[0].strip()
            else:
                # Keep the whole thing (e.g., "CURSOR, AI POWERED IDE")
                merchant = merchant_raw
        else:
            merchant = merchant_raw
    
    # Pattern: "to [MERCHANT] with" (for payments)
    if not merchant:
        to_pattern = r'\s+to\s+([^\.]+?)\s+with\s+Credit\s+Card'
        to_match = re.search(to_pattern, text, re.IGNORECASE)
        if to_match:
            merchant = to_match.group(1).strip()
    
    # Clean up merchant name
    if merchant:
        # Remove extra spaces
        merchant = re.sub(r'\s+', ' ', merchant).strip()
        parsed["parsed_description"] = merchant
    else:
        # If no merchant found, use the whole text as description
        parsed["parsed_description"] = text
    
    # Extract card number (last 4 digits)
    # Pattern: "Credit Card ending XXXX" or "Card ending XXXX"
    card_pattern = r'(?:Credit\s+)?Card\s+ending\s+(\d{4})'
    card_match = re.search(card_pattern, text, re.IGNORECASE)
    if card_match:
        parsed["parsed_card_number"] = card_match.group(1)
    
    return parsed
