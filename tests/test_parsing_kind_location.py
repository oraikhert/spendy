"""Test parsing SMS messages with transaction kind and location detection"""
import sys
from pathlib import Path

# Ensure project root is on path so "app" can be imported when run as python tests/test_parsing_kind_location.py
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from decimal import Decimal

# Test cases for kind and location detection
test_cases = [
    {
        "name": "Purchase - Standard",
        "text": "Purchase of AED 980.00 with Credit Card ending 3278 at MASSIMO DUTTI, DUBAI. Avl Cr. Limit is AED 39,989.58",
        "expected": {
            "amount": Decimal("-980.00"),
            "currency": "AED",
            "description": "MASSIMO DUTTI",
            "location": "DUBAI",
            "card_number": "3278",
            "kind": "purchase"
        }
    },
    {
        "name": "Purchase - USD with location",
        "text": "Purchase of USD 21.00 with Credit Card ending 3278 at OPENAI *CHATGPT SUBSCR, SAN FRANCISCO. Avl Cr. Limit is AED 36,397.91. Pls refer stmt for exact amt",
        "expected": {
            "amount": Decimal("-21.00"),
            "currency": "USD",
            "description": "OPENAI *CHATGPT SUBSCR",
            "location": "SAN FRANCISCO",
            "card_number": "3278",
            "kind": "purchase"
        }
    },
    {
        "name": "Refund - Purchase refunded",
        "text": "Purchase amount of AED 1.00 at EMIRATES LEISURE RETAI on your Credit Card ending 3278 has been refunded to your card account. Avl Limit is AED 39,557.93.",
        "expected": {
            "amount": Decimal("1.00"),
            "currency": "AED",
            "description": "EMIRATES LEISURE RETAI",
            "card_number": "3278",
            "kind": "refund"
        }
    },
    {
        "name": "Refund - Amount credited from merchant",
        "text": "Amount of AED 149.00 from PAN EMIRATES FURNITURE has been credited to your card ending with 3278. Available limit is AED 39,959.58.",
        "expected": {
            "amount": Decimal("149.00"),
            "currency": "AED",
            "description": "PAN EMIRATES FURNITURE",
            "card_number": "3278",
            "kind": "refund"
        }
    },
    {
        "name": "Payment to merchant",
        "text": "Payment of AED 1,493.10 to AL FUTTAIM TRANSPORT with Credit Card ending 3278. Avl Cr. Limit is AED 34,681.05.",
        "expected": {
            "amount": Decimal("-1493.10"),
            "currency": "AED",
            "description": "AL FUTTAIM TRANSPORT",
            "card_number": "3278",
            "kind": "purchase"
        }
    },
    {
        "name": "Bill Payment - Top-up",
        "text": "AED 23,406.00 has been deducted from your account 101XXX20XXX01 towards payment of your Credit Card ending 3278.",
        "expected": {
            "amount": Decimal("23406.00"),
            "currency": "AED",
            "description": "Credit Card Bill Payment",
            "card_number": "3278",
            "kind": "topup"
        }
    },
    {
        "name": "Purchase - Domain in merchant name",
        "text": "Purchase of AED 87.20 with Credit Card ending 3278 at carrefouruae.com, Dubai. Avl Cr. Limit is AED 37,201.47",
        "expected": {
            "amount": Decimal("-87.20"),
            "currency": "AED",
            "description": "carrefouruae.com",
            "location": "Dubai",
            "card_number": "3278",
            "kind": "purchase"
        }
    },
    {
        "name": "Statement - Should be skipped",
        "text": "Emirates NBD Credit Card Mini Stmt for Card ending 3278: Statement date 25/12/25. Total Amt Due AED 12368.30, Due Date 19/01/26. Min Amt Due AED 1647.58",
        "expected": {
            "parse_status": "skipped"
        }
    },
    {
        "name": "Beneficiary - Should be skipped",
        "text": "Your newly added beneficiary: Vijay Shanmugam has been activated successfully. If you did not initiate this request, please call 600540000 within UAE or +971600540000 outside UAE and report Fraud.",
        "expected": {
            "parse_status": "skipped"
        }
    }
]

try:
    from app.utils.parsing import parse_text
    
    print("\n" + "="*80)
    print("Testing SMS Parser with Kind and Location Detection")
    print("="*80)
    
    all_passed = True
    passed_count = 0
    failed_count = 0
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n📝 Test {i}: {test['name']}")
        print(f"Input: {test['text'][:80]}...")
        
        result = parse_text(test['text'])
        expected = test['expected']
        
        test_passed = True
        
        # Check if should be skipped
        if 'parse_status' in expected and expected['parse_status'] == 'skipped':
            if result['parse_status'] == 'skipped':
                print(f"  ✅ Correctly skipped non-transaction message")
                passed_count += 1
            else:
                print(f"  ❌ Should have been skipped, got status: {result['parse_status']}")
                test_passed = False
                all_passed = False
                failed_count += 1
            continue
        
        # Check amount
        if 'amount' in expected:
            if result['parsed_amount'] == expected['amount']:
                print(f"  ✅ Amount: {result['parsed_amount']}")
            else:
                print(f"  ❌ Amount: Expected {expected['amount']}, got {result['parsed_amount']}")
                test_passed = False
                all_passed = False
        
        # Check currency
        if 'currency' in expected:
            if result['parsed_currency'] == expected['currency']:
                print(f"  ✅ Currency: {result['parsed_currency']}")
            else:
                print(f"  ❌ Currency: Expected {expected['currency']}, got {result['parsed_currency']}")
                test_passed = False
                all_passed = False
        
        # Check description
        if 'description' in expected:
            if result['parsed_description'] == expected['description']:
                print(f"  ✅ Description: {result['parsed_description']}")
            else:
                print(f"  ❌ Description: Expected '{expected['description']}', got '{result['parsed_description']}'")
                test_passed = False
                all_passed = False
        
        # Check location
        if 'location' in expected:
            if result['parsed_location'] == expected['location']:
                print(f"  ✅ Location: {result['parsed_location']}")
            else:
                print(f"  ❌ Location: Expected '{expected['location']}', got '{result['parsed_location']}'")
                test_passed = False
                all_passed = False
        
        # Check card number
        if 'card_number' in expected:
            if result['parsed_card_number'] == expected['card_number']:
                print(f"  ✅ Card Number: {result['parsed_card_number']}")
            else:
                print(f"  ❌ Card Number: Expected {expected['card_number']}, got {result['parsed_card_number']}")
                test_passed = False
                all_passed = False
        
        # Check transaction kind
        if 'kind' in expected:
            if result['parsed_transaction_kind'] == expected['kind']:
                print(f"  ✅ Transaction Kind: {result['parsed_transaction_kind']}")
            else:
                print(f"  ❌ Transaction Kind: Expected {expected['kind']}, got {result['parsed_transaction_kind']}")
                test_passed = False
                all_passed = False
        
        # Show parse status
        print(f"  ℹ️  Parse status: {result['parse_status']}")
        
        if test_passed:
            passed_count += 1
        else:
            failed_count += 1
    
    print("\n" + "="*80)
    print(f"Results: {passed_count} passed, {failed_count} failed out of {passed_count + failed_count} tests")
    
    if all_passed:
        print("✅ ALL TESTS PASSED!")
        print("\nThe parser successfully extracts:")
        print("  • Transaction amounts (with comma handling)")
        print("  • Currency codes (AED, USD, etc.)")
        print("  • Merchant names from various patterns")
        print("  • Card numbers (last 4 digits)")
        print("  • Transaction kind (purchase, refund, topup, other)")
        print("  • Location information")
        print("  • Negative amounts for purchases/payments")
        print("  • Positive amounts for refunds/top-ups")
        print("  • Skips non-transaction messages")
    else:
        print("❌ SOME TESTS FAILED")
        sys.exit(1)
    print("="*80 + "\n")
    
except ImportError as e:
    print(f"⚠️  Could not import dependencies: {e}")
    print("Run: pip install -r requirements.txt")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
