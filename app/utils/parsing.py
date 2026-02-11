"""Parsing utilities (stub implementation)"""
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime


def parse_text(raw_text: str) -> dict:
    """
    Parse bank SMS notifications.
    
    Supported formats:
    - Purchase of AED 2.50 with Credit Card ending 3278 at MERCHANT, LOCATION...
    - Payment of AED 1,493.10 to MERCHANT with Credit Card ending 3278...
    - Purchase amount of AED 1.00 at MERCHANT has been refunded to your card account...
    - Amount of AED 149.00 from MERCHANT has been credited to your card ending with 3278...
    - AED X.XX has been deducted from your account ... towards payment of your Credit Card ending 3278
    
    Args:
        raw_text: Raw text input
        
    Returns:
        Dictionary with parsed fields including parsed_transaction_kind and parsed_location
    """
    parsed = {
        "parsed_description": None,
        "parsed_amount": None,
        "parsed_currency": None,
        "parsed_transaction_datetime": None,
        "parsed_posting_datetime": None,
        "parsed_card_number": None,
        "parsed_transaction_kind": None,
        "parsed_location": None,
        "parse_status": "parsed",
        "parse_error": None,
    }
    
    if not raw_text:
        return parsed
    
    text = raw_text.strip()
    
    # Check if this is a card-related transaction message
    # Skip non-transaction messages (statements, reminders, beneficiary notifications)
    if "Mini Stmt" in text or "Statement date" in text:
        parsed["parse_status"] = "skipped"
        parsed["parse_error"] = "Non-transaction message (statement)"
        return parsed
    if "this is to remind you" in text.lower() or "upcoming payment" in text.lower():
        parsed["parse_status"] = "skipped"
        parsed["parse_error"] = "Non-transaction message (reminder)"
        return parsed
    if "beneficiary" in text.lower():
        parsed["parse_status"] = "skipped"
        parsed["parse_error"] = "Non-transaction message (beneficiary)"
        return parsed
    
    # Variables to track transaction type for kind detection
    transaction_type = None
    is_refund = False
    is_credit = False
    is_bill_payment = False
    
    # Pattern 1: Purchase amount refunded
    # "Purchase amount of AED 1.00 at MERCHANT ... has been refunded to your card account"
    refund_pattern = r'Purchase\s+amount\s+of\s+([A-Z]{3})\s+([\d,]+(?:\.\d{2})?)\s+at\s+(.+?)\s+on\s+your\s+Credit\s+Card.*?has\s+been\s+refunded'
    refund_match = re.search(refund_pattern, text, re.IGNORECASE)
    if refund_match:
        is_refund = True
        transaction_type = 'refund'
        currency = refund_match.group(1)
        amount_str = refund_match.group(2).replace(',', '')
        merchant_raw = refund_match.group(3).strip()
        
        try:
            amount = Decimal(amount_str)
            parsed["parsed_amount"] = abs(amount)  # Refunds are positive
            parsed["parsed_currency"] = currency
            parsed["parsed_description"] = merchant_raw
        except (InvalidOperation, ValueError) as e:
            parsed["parse_status"] = "failed"
            parsed["parse_error"] = f"Invalid amount format: {amount_str}"
            return parsed
    
    # Pattern 2: Amount credited to card (merchant refund)
    # "Amount of AED 149.00 from MERCHANT has been credited to your card ending with 3278"
    if not is_refund:
        credit_pattern = r'Amount\s+of\s+([A-Z]{3})\s+([\d,]+(?:\.\d{2})?)\s+from\s+(.+?)\s+has\s+been\s+credited\s+to\s+your\s+card'
        credit_match = re.search(credit_pattern, text, re.IGNORECASE)
        if credit_match:
            is_credit = True
            transaction_type = 'refund'  # Merchant credits are refunds
            currency = credit_match.group(1)
            amount_str = credit_match.group(2).replace(',', '')
            merchant_raw = credit_match.group(3).strip()
            
            try:
                amount = Decimal(amount_str)
                parsed["parsed_amount"] = abs(amount)  # Credits are positive
                parsed["parsed_currency"] = currency
                parsed["parsed_description"] = merchant_raw
            except (InvalidOperation, ValueError) as e:
                parsed["parse_status"] = "failed"
                parsed["parse_error"] = f"Invalid amount format: {amount_str}"
                return parsed
    
    # Pattern 3: Bill payment to credit card
    # "AED X.XX has been deducted from your account ... towards payment of your Credit Card ending 3278"
    if not is_refund and not is_credit:
        bill_payment_pattern = r'([A-Z]{3})\s+([\d,]+(?:\.\d{2})?)\s+has\s+been\s+deducted\s+from\s+your\s+account.*?towards\s+payment\s+of\s+your\s+Credit\s+Card'
        bill_payment_match = re.search(bill_payment_pattern, text, re.IGNORECASE)
        if bill_payment_match:
            is_bill_payment = True
            transaction_type = 'topup'  # Bill payments are top-ups (money in)
            currency = bill_payment_match.group(1)
            amount_str = bill_payment_match.group(2).replace(',', '')
            
            try:
                amount = Decimal(amount_str)
                parsed["parsed_amount"] = abs(amount)  # Top-ups are positive
                parsed["parsed_currency"] = currency
                parsed["parsed_description"] = "Credit Card Bill Payment"
            except (InvalidOperation, ValueError) as e:
                parsed["parse_status"] = "failed"
                parsed["parse_error"] = f"Invalid amount format: {amount_str}"
                return parsed
    
    # Pattern 4: Standard purchase/payment
    # "Purchase of AED 2.50 with Credit Card ending 3278 at MERCHANT"
    # "Payment of AED 1,493.10 to MERCHANT with Credit Card ending 3278"
    if not is_refund and not is_credit and not is_bill_payment:
        transaction_pattern = r'(Purchase|Payment)\s+of\s+([A-Z]{3})\s+([\d,]+(?:\.\d{2})?)'
        match = re.search(transaction_pattern, text, re.IGNORECASE)
        
        if match:
            transaction_type = match.group(1).lower()  # purchase or payment
            currency = match.group(2)
            amount_str = match.group(3).replace(',', '')  # Remove commas
            
            try:
                amount = Decimal(amount_str)
                # Purchases and payments to merchants are expenses (negative)
                parsed["parsed_amount"] = -abs(amount)
                parsed["parsed_currency"] = currency
            except (InvalidOperation, ValueError) as e:
                parsed["parse_status"] = "failed"
                parsed["parse_error"] = f"Invalid amount format: {amount_str}"
                return parsed
    
    # Fallback: Try simple pattern matching if nothing matched yet
    if parsed["parsed_amount"] is None:
        amount_pattern = r'([A-Z]{3})\s+([\d,]+(?:\.\d{2})?)'
        match = re.search(amount_pattern, text)
        if match:
            try:
                currency = match.group(1)
                amount_str = match.group(2).replace(',', '')
                parsed["parsed_amount"] = -abs(Decimal(amount_str))  # Assume expense
                parsed["parsed_currency"] = currency
                transaction_type = 'other'
            except (InvalidOperation, ValueError):
                pass
    
    # Extract merchant name (if not already set)
    if parsed["parsed_description"] is None:
        merchant = None
        location = None
        
        # Pattern: "at [MERCHANT, LOCATION]" - capture everything until ". Avl" or " on your Credit Card" or end
        at_pattern = r'\s+at\s+(.+?)(?:\.\s*Avl|\s+on\s+your\s+Credit\s+Card|\s*$)'
        at_match = re.search(at_pattern, text, re.IGNORECASE)
        if at_match:
            merchant_raw = at_match.group(1).strip()
            # Remove trailing period if present
            merchant_raw = merchant_raw.rstrip('.')
            
            # Try to extract location from merchant string
            # Pattern: ", CITY" or ", CITY." at the end
            parts = merchant_raw.rsplit(',', 1)
            if len(parts) == 2:
                potential_location = parts[1].strip().rstrip('.')
                # If it looks like a location (starts with capital, common location words, or all caps)
                if potential_location and (
                    potential_location[0].isupper() or 
                    potential_location.isupper() or
                    potential_location.lower() in ['dubai', 'abu dhabi', 'sharjah', 'dxb', 'uae', 
                                                     'new york', 'san francisco', 'ae']
                ):
                    merchant = parts[0].strip()
                    location = potential_location
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
            if location:
                parsed["parsed_location"] = location
        else:
            # If no merchant found, use the whole text as description
            parsed["parsed_description"] = text
    
    # Extract card number (last 4 digits)
    # Pattern: "Credit Card ending XXXX" or "card ending with XXXX"
    card_pattern = r'(?:Credit\s+)?[Cc]ard\s+ending\s+(?:with\s+)?(\d{4})'
    card_match = re.search(card_pattern, text, re.IGNORECASE)
    if card_match:
        parsed["parsed_card_number"] = card_match.group(1)
    
    # Determine transaction_kind based on the patterns matched
    if is_refund or is_credit:
        parsed["parsed_transaction_kind"] = "refund"
    elif is_bill_payment:
        parsed["parsed_transaction_kind"] = "topup"
    elif transaction_type in ['purchase', 'payment']:
        parsed["parsed_transaction_kind"] = "purchase"
    elif transaction_type:
        parsed["parsed_transaction_kind"] = transaction_type
    else:
        parsed["parsed_transaction_kind"] = "other"
    
    return parsed
