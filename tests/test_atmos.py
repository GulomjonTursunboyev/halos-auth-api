"""
Comprehensive tests for Atmos Payment Integration
==================================================
Tests for:
- atmos.py (service layer) 
- routers/cards.py (card binding endpoints)
- routers/payments.py (payment endpoints)

Run: python -m pytest tests/test_atmos.py -v
"""

import asyncio
import hashlib
import json
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ==============================================
# Test 1: Import Tests
# ==============================================

def test_imports():
    """Test that all modules import correctly"""
    errors = []
    
    try:
        from api.atmos import (
            AtmosError,
            get_access_token,
            bind_card_init,
            bind_card_confirm,
            list_bound_cards,
            remove_bound_card,
            create_transaction,
            pre_apply_transaction,
            apply_transaction,
            get_transaction_info,
            reverse_transaction,
            verify_callback_sign,
            ATMOS_BASE_URL,
            TIMEOUT,
        )
        print("  ✅ api.atmos imports OK")
    except ImportError as e:
        errors.append(f"  ❌ api.atmos import error: {e}")

    try:
        from api.routers.cards import (
            router,
            CardBindInitRequest,
            CardBindConfirmRequest,
            CardRemoveRequest,
            UserCardsRequest,
            save_user_card,
            deactivate_user_card,
            get_user_cards_from_db,
        )
        print("  ✅ api.routers.cards imports OK")
    except ImportError as e:
        errors.append(f"  ❌ api.routers.cards import error: {e}")

    try:
        from api.routers.payments import (
            router,
            CreatePaymentRequest,
            PreApplyPaymentRequest,
            ApplyPaymentRequest,
            PaymentInfoRequest,
            ReversePaymentRequest,
            PayWithBoundCardRequest,
            save_payment_record,
            update_payment_status,
            get_user_payments,
        )
        print("  ✅ api.routers.payments imports OK")
    except ImportError as e:
        errors.append(f"  ❌ api.routers.payments import error: {e}")

    try:
        from api.main import app
        print("  ✅ api.main imports OK (app created)")
    except ImportError as e:
        errors.append(f"  ❌ api.main import error: {e}")

    if errors:
        for err in errors:
            print(err)
        return False
    return True


# ==============================================
# Test 2: AtmosError Class Tests
# ==============================================

def test_atmos_error():
    """Test AtmosError exception class"""
    from api.atmos import AtmosError

    # Test basic error
    err = AtmosError("TEST_CODE", "Test description")
    assert err.code == "TEST_CODE"
    assert err.description == "Test description"
    assert err.status_code == 400  # default
    assert "TEST_CODE" in str(err)
    assert "Test description" in str(err)
    print("  ✅ AtmosError basic creation OK")

    # Test with custom status code
    err2 = AtmosError("SERVER", "Internal error", 500)
    assert err2.status_code == 500
    print("  ✅ AtmosError custom status_code OK")

    # Test inheritance
    assert isinstance(err, Exception)
    print("  ✅ AtmosError inherits Exception OK")

    return True


# ==============================================
# Test 3: Callback Sign Verification
# ==============================================

def test_callback_sign_verification():
    """Test callback signature verification"""
    from api.atmos import verify_callback_sign, ATMOS_API_KEY

    # Test with no API key set (should return False)
    if not ATMOS_API_KEY:
        result = verify_callback_sign("1", "2", "3", "4", "abc")
        assert result == False
        print("  ✅ verify_callback_sign returns False when no API key set")

    # Test signature calculation manually
    os.environ["ATMOS_API_KEY"] = "test_api_key"
    
    # Reload module to pick up new env var
    import importlib
    import api.atmos
    importlib.reload(api.atmos)
    from api.atmos import verify_callback_sign as verify_sign_reloaded
    
    store_id = "1234"
    transaction_id = "5678"
    invoice = "INV001"
    amount = "5000000"
    api_key = "test_api_key"

    raw = f"{store_id}{transaction_id}{invoice}{amount}{api_key}"
    expected_sign = hashlib.sha256(raw.encode()).hexdigest()

    result = verify_sign_reloaded(store_id, transaction_id, invoice, amount, expected_sign)
    assert result == True
    print("  ✅ verify_callback_sign correct sign verification OK")

    # Test with wrong sign
    result2 = verify_sign_reloaded(store_id, transaction_id, invoice, amount, "wrong_sign")
    assert result2 == False
    print("  ✅ verify_callback_sign wrong sign rejection OK")

    # Clean up
    os.environ.pop("ATMOS_API_KEY", None)
    importlib.reload(api.atmos)

    return True


# ==============================================
# Test 4: Pydantic Model Validation (Cards)
# ==============================================

def test_card_models():
    """Test card binding Pydantic models"""
    from api.routers.cards import (
        CardBindInitRequest,
        CardBindConfirmRequest,
        CardRemoveRequest,
        UserCardsRequest,
    )

    # Test CardBindInitRequest - valid
    req = CardBindInitRequest(card_number="8600490744313347", expiry="2410", user_id=123456)
    assert req.card_number == "8600490744313347"
    assert req.expiry == "2410"
    assert req.user_id == 123456
    print("  ✅ CardBindInitRequest valid data OK")

    # Test CardBindInitRequest - invalid card number (too short)
    try:
        CardBindInitRequest(card_number="860049", expiry="2410", user_id=123)
        print("  ❌ CardBindInitRequest should reject short card number")
        return False
    except Exception:
        print("  ✅ CardBindInitRequest rejects short card number OK")

    # Test CardBindInitRequest - invalid expiry (too short)
    try:
        CardBindInitRequest(card_number="8600490744313347", expiry="24", user_id=123)
        print("  ❌ CardBindInitRequest should reject short expiry")
        return False
    except Exception:
        print("  ✅ CardBindInitRequest rejects short expiry OK")

    # Test CardBindConfirmRequest
    req2 = CardBindConfirmRequest(transaction_id=442, otp="123456", user_id=789)
    assert req2.transaction_id == 442
    assert req2.otp == "123456"
    print("  ✅ CardBindConfirmRequest valid data OK")

    # Test OTP too short
    try:
        CardBindConfirmRequest(transaction_id=442, otp="12", user_id=789)
        print("  ❌ Should reject short OTP")
        return False
    except Exception:
        print("  ✅ CardBindConfirmRequest rejects short OTP OK")

    # Test CardRemoveRequest
    req3 = CardRemoveRequest(card_id=111, card_token="token123", user_id=456)
    assert req3.card_id == 111
    print("  ✅ CardRemoveRequest valid data OK")

    # Test UserCardsRequest
    req4 = UserCardsRequest(user_id=12345)
    assert req4.user_id == 12345
    print("  ✅ UserCardsRequest valid data OK")

    return True


# ==============================================
# Test 5: Pydantic Model Validation (Payments)
# ==============================================

def test_payment_models():
    """Test payment Pydantic models"""
    from api.routers.payments import (
        CreatePaymentRequest,
        PreApplyPaymentRequest,
        ApplyPaymentRequest,
        PaymentInfoRequest,
        ReversePaymentRequest,
        PayWithBoundCardRequest,
    )

    # Test CreatePaymentRequest
    req = CreatePaymentRequest(user_id=123, amount=5000000, description="Test", payment_type="monthly")
    assert req.amount == 5000000
    assert req.payment_type == "monthly"
    print("  ✅ CreatePaymentRequest valid data OK")

    # Test amount must be > 0
    try:
        CreatePaymentRequest(user_id=123, amount=0)
        print("  ❌ Should reject zero amount")
        return False
    except Exception:
        print("  ✅ CreatePaymentRequest rejects zero amount OK")

    try:
        CreatePaymentRequest(user_id=123, amount=-100)
        print("  ❌ Should reject negative amount")
        return False
    except Exception:
        print("  ✅ CreatePaymentRequest rejects negative amount OK")

    # Test PreApplyPaymentRequest with card_token
    req2 = PreApplyPaymentRequest(transaction_id=111, card_token="token123")
    assert req2.card_token == "token123"
    assert req2.card_number is None
    print("  ✅ PreApplyPaymentRequest with card_token OK")

    # Test PreApplyPaymentRequest with card_number + expiry
    req3 = PreApplyPaymentRequest(transaction_id=111, card_number="8600111122223333", expiry="2510")
    assert req3.card_number == "8600111122223333"
    assert req3.expiry == "2510"
    print("  ✅ PreApplyPaymentRequest with card_number+expiry OK")

    # Test ApplyPaymentRequest
    req4 = ApplyPaymentRequest(transaction_id=111, otp="123456", user_id=789)
    assert req4.otp == "123456"
    print("  ✅ ApplyPaymentRequest valid data OK")

    # Test OTP validation
    try:
        ApplyPaymentRequest(transaction_id=111, otp="12", user_id=789)
        print("  ❌ Should reject short OTP")
        return False
    except Exception:
        print("  ✅ ApplyPaymentRequest rejects short OTP OK")

    # Test PaymentInfoRequest
    req5 = PaymentInfoRequest(transaction_id=111)
    assert req5.store_id is None
    print("  ✅ PaymentInfoRequest valid data OK")

    # Test ReversePaymentRequest
    req6 = ReversePaymentRequest(transaction_id=111, user_id=789)
    assert req6.reason == "Qaytarish / Возврат"
    print("  ✅ ReversePaymentRequest default reason OK")

    # Test PayWithBoundCardRequest
    req7 = PayWithBoundCardRequest(user_id=123, card_token="tok_abc", amount=1000)
    assert req7.payment_type == "subscription"
    print("  ✅ PayWithBoundCardRequest valid data OK")

    return True


# ==============================================
# Test 6: FastAPI App Routes Registration
# ==============================================

def test_app_routes():
    """Test that all routes are properly registered"""
    from api.main import app

    routes = [route.path for route in app.routes]

    expected_routes = [
        "/api/cards/bind/init",
        "/api/cards/bind/confirm",
        "/api/cards/list",
        "/api/cards/remove",
        "/api/cards/bound",
        "/api/payments/create",
        "/api/payments/pre-apply",
        "/api/payments/apply",
        "/api/payments/info",
        "/api/payments/reverse",
        "/api/payments/pay-with-card",
        "/api/payments/history/{user_id}",
        "/api/payments/callback",
    ]

    missing = []
    for route in expected_routes:
        if route not in routes:
            missing.append(route)

    if missing:
        print(f"  ❌ Missing routes: {missing}")
        print(f"  Available routes: {[r for r in routes if '/api/' in r]}")
        return False

    print(f"  ✅ All {len(expected_routes)} Atmos routes registered OK")
    return True


# ==============================================
# Test 7: Configuration Constants
# ==============================================

def test_configuration():
    """Test configuration constants are properly set"""
    from api.atmos import (
        ATMOS_BASE_URL,
        TIMEOUT,
    )

    assert ATMOS_BASE_URL == "https://apigw.atmos.uz" or ATMOS_BASE_URL != ""
    print(f"  ✅ ATMOS_BASE_URL = {ATMOS_BASE_URL}")

    assert TIMEOUT.connect == 10.0
    assert TIMEOUT.read == 30.0
    print(f"  ✅ TIMEOUT connect={TIMEOUT.connect}s, read={TIMEOUT.read}s")

    return True


# ==============================================
# Test 8: Token Cache Structure
# ==============================================

def test_token_cache():
    """Test token cache structure"""
    from api.atmos import _token_cache

    assert "access_token" in _token_cache
    assert "expires_at" in _token_cache
    assert _token_cache["access_token"] is None  # Not initialized yet
    assert _token_cache["expires_at"] == 0
    print("  ✅ Token cache structure OK")

    return True


# ==============================================
# Run all tests
# ==============================================

def run_all_tests():
    """Run all tests and report results"""
    print("=" * 60)
    print("ATMOS PAYMENT INTEGRATION - TEST SUITE")
    print("=" * 60)

    tests = [
        ("1. Import Tests", test_imports),
        ("2. AtmosError Class", test_atmos_error),
        ("3. Callback Sign Verification", test_callback_sign_verification),
        ("4. Card Model Validation", test_card_models),
        ("5. Payment Model Validation", test_payment_models),
        ("6. App Routes Registration", test_app_routes),
        ("7. Configuration Constants", test_configuration),
        ("8. Token Cache Structure", test_token_cache),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        print(f"\n{'─' * 40}")
        print(f"Test {name}")
        print(f"{'─' * 40}")
        try:
            result = test_func()
            if result:
                passed += 1
                print(f"  ✅ PASSED")
            else:
                failed += 1
                print(f"  ❌ FAILED")
        except Exception as e:
            failed += 1
            print(f"  ❌ FAILED with error: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(tests)} tests")
    print(f"{'=' * 60}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
