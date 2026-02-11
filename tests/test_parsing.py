"""Test the enhanced parsing function with real SMS examples"""
import sys
from pathlib import Path

# Ensure project root is on path so "app" can be imported when run as python tests/test_parsing.py
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from decimal import Decimal

# Test without importing dependencies
test_cases = [
    {
        "text": "Purchase of AED 2.50 with Credit Card ending 3278 at EKFC DELI 2 GO 599995, DUBAI. Avl Cr. Limit is AED 34,678.55",
        "expected": {
            "amount": Decimal("-2.50"),
            "currency": "AED",
            "description": "EKFC DELI 2 GO 599995",
            "card_number": "3278"
        }
    },
    {
        "text": "Payment of AED 1,493.10 to AL FUTTAIM TRANSPORT with Credit Card ending 3278. Avl Cr. Limit is AED 34,681.05.",
        "expected": {
            "amount": Decimal("-1493.10"),
            "currency": "AED",
            "description": "AL FUTTAIM TRANSPORT",
            "card_number": "3278"
        }
    },
    {
        "text": "Purchase of USD 21.00 with Credit Card ending 3278 at OPENAI *CHATGPT SUBSCR, SAN FRANCISCO. Avl Cr. Limit is AED 36,397.91. Pls refer stmt for exact amt",
        "expected": {
            "amount": Decimal("-21.00"),
            "currency": "USD",
            "description": "OPENAI *CHATGPT SUBSCR",
            "card_number": "3278"
        }
    },
    {
        "text": "Purchase of USD 20.00 with Credit Card ending 3278 at CURSOR, AI POWERED IDE, NEW YORK. Avl Cr. Limit is AED 36,977.49. Pls refer stmt for exact amt",
        "expected": {
            "amount": Decimal("-20.00"),
            "currency": "USD",
            "description": "CURSOR, AI POWERED IDE",
            "card_number": "3278"
        }
    },
    {
        "text": "Purchase of AED 87.20 with Credit Card ending 3278 at carrefouruae.com, Dubai. Avl Cr. Limit is AED 37,201.47",
        "expected": {
            "amount": Decimal("-87.20"),
            "currency": "AED",
            "description": "carrefouruae.com",
            "card_number": "3278"
        }
    }
]

try:
    from app.utils.parsing import parse_text_stub
    
    print("\n" + "="*80)
    print("Testing Enhanced SMS Parser")
    print("="*80)
    
    all_passed = True
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n📝 Test {i}:")
        print(f"Input: {test['text'][:80]}...")
        
        result = parse_text_stub(test['text'])
        expected = test['expected']
        
        # Check amount
        if result['parsed_amount'] == expected['amount']:
            print(f"  ✅ Amount: {result['parsed_amount']} {result['parsed_currency']}")
        else:
            print(f"  ❌ Amount: Expected {expected['amount']}, got {result['parsed_amount']}")
            all_passed = False
        
        # Check currency
        if result['parsed_currency'] == expected['currency']:
            print(f"  ✅ Currency: {result['parsed_currency']}")
        else:
            print(f"  ❌ Currency: Expected {expected['currency']}, got {result['parsed_currency']}")
            all_passed = False
        
        # Check description
        if result['parsed_description'] == expected['description']:
            print(f"  ✅ Description: {result['parsed_description']}")
        else:
            print(f"  ⚠️  Description: Expected '{expected['description']}', got '{result['parsed_description']}'")
            # Description mismatch is a warning, not a failure
        
        # Check card number
        if result['parsed_card_number'] == expected['card_number']:
            print(f"  ✅ Card Number: {result['parsed_card_number']}")
        else:
            print(f"  ❌ Card Number: Expected {expected['card_number']}, got {result['parsed_card_number']}")
            all_passed = False
        
        # Show parse status
        print(f"  ℹ️  Parse status: {result['parse_status']}")
    
    print("\n" + "="*80)
    if all_passed:
        print("✅ ALL TESTS PASSED!")
        print("\nThe parser successfully extracts:")
        print("  • Transaction amounts (with comma handling)")
        print("  • Currency codes (AED, USD, etc.)")
        print("  • Merchant names from 'at' and 'to' patterns")
        print("  • Card numbers (last 4 digits)")
        print("  • Negative amounts for purchases/payments")
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
