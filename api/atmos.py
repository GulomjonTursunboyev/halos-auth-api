"""
Atmos Payment Gateway Integration Service
==========================================
Handles all communication with Atmos API:
- Token management (get, refresh, revoke)
- Card binding (init, confirm, list, remove)
- Payment transactions (create, pre-apply, apply, reverse, get)

All Atmos API requests are proxied through this server.
The consumer_key and consumer_secret are stored as environment variables.
"""

import httpx
import base64
import time
import hashlib
import logging
import os
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# ==============================================
# Configuration - loaded from environment
# ==============================================
ATMOS_BASE_URL = os.getenv("ATMOS_BASE_URL", "https://apigw.atmos.uz")
ATMOS_CONSUMER_KEY = os.getenv("ATMOS_CONSUMER_KEY", "")
ATMOS_CONSUMER_SECRET = os.getenv("ATMOS_CONSUMER_SECRET", "")
ATMOS_STORE_ID = os.getenv("ATMOS_STORE_ID", "")
ATMOS_TERMINAL_ID = os.getenv("ATMOS_TERMINAL_ID", "")
ATMOS_API_KEY = os.getenv("ATMOS_API_KEY", "")  # For callback sign verification

# Token cache
_token_cache: Dict[str, Any] = {
    "access_token": None,
    "expires_at": 0,
}

# HTTP client timeout
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class AtmosError(Exception):
    """Custom exception for Atmos API errors"""
    def __init__(self, code: str, description: str, status_code: int = 400):
        self.code = code
        self.description = description
        self.status_code = status_code
        super().__init__(f"Atmos Error [{code}]: {description}")


# ==============================================
# Token Management
# ==============================================

async def get_access_token() -> str:
    """
    Get a valid Atmos access token.
    Uses cached token if not expired, otherwise fetches a new one.
    Token is valid for 3600 seconds (1 hour).
    """
    global _token_cache

    # Check if we have a valid cached token (with 60s buffer)
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]

    # Need to get a new token
    if not ATMOS_CONSUMER_KEY or not ATMOS_CONSUMER_SECRET:
        raise AtmosError("CONFIG_ERROR", "ATMOS_CONSUMER_KEY and ATMOS_CONSUMER_SECRET must be set", 500)

    # Create Basic auth header: Base64(consumer_key:consumer_secret)
    credentials = f"{ATMOS_CONSUMER_KEY}:{ATMOS_CONSUMER_SECRET}"
    basic_auth = base64.b64encode(credentials.encode()).decode()

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.post(
                f"{ATMOS_BASE_URL}/token",
                params={"grant_type": "client_credentials"},
                headers={
                    "Authorization": f"Basic {basic_auth}",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data={"grant_type": "client_credentials"}
            )

            if response.status_code != 200:
                logger.error(f"Atmos token request failed: {response.status_code} {response.text}")
                raise AtmosError("TOKEN_ERROR", f"Failed to get token: {response.text}", response.status_code)

            data = response.json()
            _token_cache["access_token"] = data["access_token"]
            _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600)

            logger.info("Atmos access token obtained successfully")
            return _token_cache["access_token"]

        except httpx.RequestError as e:
            logger.error(f"Atmos token request error: {e}")
            raise AtmosError("NETWORK_ERROR", f"Failed to connect to Atmos: {str(e)}", 503)


async def _make_request(method: str, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Make an authenticated request to the Atmos API.
    Automatically handles token acquisition.
    """
    token = await get_access_token()

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            url = f"{ATMOS_BASE_URL}{endpoint}"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            if method.upper() == "POST":
                response = await client.post(url, json=data, headers=headers)
            elif method.upper() == "GET":
                response = await client.get(url, headers=headers, params=data)
            else:
                raise AtmosError("INVALID_METHOD", f"Unsupported HTTP method: {method}")

            result = response.json()

            # Check for Atmos API errors
            if response.status_code != 200:
                logger.error(f"Atmos API error: {response.status_code} {result}")
                raise AtmosError(
                    result.get("result", {}).get("code", "UNKNOWN"),
                    result.get("result", {}).get("description", "Unknown error"),
                    response.status_code
                )

            # Some endpoints return result.code != "OK"
            result_obj = result.get("result", {})
            if result_obj.get("code") and result_obj["code"] != "OK":
                # Not all non-OK codes are errors (e.g., STPIMS-ERR-092 = transaction closed, but data is returned)
                # So we log but don't raise for transaction info requests
                logger.warning(f"Atmos API response code: {result_obj['code']} - {result_obj.get('description', '')}")

            return result

        except httpx.RequestError as e:
            logger.error(f"Atmos API request error: {e}")
            raise AtmosError("NETWORK_ERROR", f"Failed to connect to Atmos: {str(e)}", 503)


# ==============================================
# Card Binding Methods (Uzcard/Humo)
# ==============================================

async def bind_card_init(card_number: str, expiry: str) -> Dict[str, Any]:
    """
    Step 1: Create card binding request.
    Sends SMS confirmation code to the cardholder.

    Args:
        card_number: Card number (e.g., "8600490744313347")
        expiry: Card expiry in format "YYMM" (e.g., "2410")

    Returns:
        {
            "result": {"code": "OK", "description": "..."},
            "transaction_id": 442,
            "phone": "********9999"
        }
    """
    return await _make_request("POST", "/partner/bind-card/init", {
        "card_number": card_number,
        "expiry": expiry
    })


async def bind_card_confirm(transaction_id: int, otp: str) -> Dict[str, Any]:
    """
    Step 2: Confirm card binding with OTP code from SMS.

    Args:
        transaction_id: Transaction ID from bind_card_init
        otp: SMS confirmation code

    Returns:
        {
            "result": {"code": "OK", "description": "..."},
            "data": {
                "card_id": 1579076,
                "pan": "986009******1840",
                "expiry": "2505",
                "card_holder": "TEST",
                "balance": 1000000000,
                "phone": "********9999",
                "card_token": "<card-token>"
            },
            "transaction_id": 4789
        }
    """
    return await _make_request("POST", "/partner/bind-card/confirm", {
        "transaction_id": transaction_id,
        "otp": otp
    })


async def list_bound_cards(page: int = 1, page_size: int = 50) -> Dict[str, Any]:
    """
    Get list of all cards bound to the merchant.

    Args:
        page: Page number (default: 1)
        page_size: Number of items per page (default: 50)

    Returns:
        {
            "result": {"code": "OK", "description": "..."},
            "cardDataSmallList": [
                {
                    "card_id": 1579076,
                    "card_token": "<card-token>",
                    "pan": "986009******1840",
                    "expiry": "2505"
                }
            ]
        }
    """
    return await _make_request("POST", "/partner/list-cards", {
        "page": page,
        "page_size": page_size
    })


async def remove_bound_card(card_id: int, card_token: str) -> Dict[str, Any]:
    """
    Remove (unbind) a previously bound card.

    Args:
        card_id: Card ID from bind_card_confirm
        card_token: Card token from bind_card_confirm

    Returns:
        {
            "result": {"code": "OK", "description": "..."},
            "data": {"card_id": 1666711, "pan": null, ...}
        }
    """
    return await _make_request("POST", "/partner/remove-card", {
        "id": card_id,
        "token": card_token
    })


# ==============================================
# Payment Transaction Methods
# ==============================================

async def create_transaction(amount: int, account: str, lang: str = "ru") -> Dict[str, Any]:
    """
    Step 1: Create a payment transaction (draft).

    Args:
        amount: Amount in tiyin (e.g., 5000000 = 50,000 UZS)
        account: Invoice/account number (unique identifier for this payment)
        lang: Language for labels ("ru", "uz", "en")

    Returns:
        {
            "result": {"code": "OK", ...},
            "transaction_id": 111111,
            "store_transaction": { ... }
        }
    """
    payload = {
        "amount": amount,
        "account": account,
        "lang": lang
    }

    # Add store_id and terminal_id if configured
    if ATMOS_STORE_ID:
        payload["store_id"] = ATMOS_STORE_ID
    if ATMOS_TERMINAL_ID:
        payload["terminal_id"] = ATMOS_TERMINAL_ID

    return await _make_request("POST", "/merchant/pay/create", payload)


async def pre_apply_transaction(
    transaction_id: int,
    store_id: Optional[int] = None,
    card_number: Optional[str] = None,
    expiry: Optional[str] = None,
    card_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Step 2: Pre-apply (pre-confirm) a transaction.
    Sends OTP to cardholder for confirmation.

    Use EITHER (card_number + expiry) OR card_token:
    - card_number + expiry: for one-time card payment with SMS OTP
    - card_token: for payment with a previously bound card

    Args:
        transaction_id: Transaction ID from create_transaction
        store_id: Store ID (uses env default if not provided)
        card_number: Card number (for one-time payment)
        expiry: Card expiry YYMM (for one-time payment)
        card_token: Token of a bound card (for recurring payment)

    Returns:
        {
            "transaction_id": 202072,
            "result": {"code": "OK", "description": "..."}
        }
    """
    payload: Dict[str, Any] = {
        "transaction_id": transaction_id,
        "store_id": int(store_id or ATMOS_STORE_ID or 0)
    }

    if card_token:
        # Payment with bound card
        payload["card_token"] = card_token
    elif card_number and expiry:
        # One-time card payment
        payload["card_number"] = card_number
        payload["expiry"] = expiry
    else:
        raise AtmosError("INVALID_PARAMS", "Either card_token or (card_number + expiry) must be provided")

    return await _make_request("POST", "/merchant/pay/pre-apply", payload)


async def apply_transaction(transaction_id: int, otp: str, store_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Step 3: Confirm transaction and charge the card.

    Args:
        transaction_id: Transaction ID
        otp: OTP code from SMS
        store_id: Store ID (uses env default if not provided)

    Returns:
        {
            "result": {"code": "OK", ...},
            "store_transaction": {
                "success_trans_id": 0000000,
                "amount": 5000000,
                "confirmed": true,
                ...
            },
            "ofd_url": "...",
            "ofd_url_commission": "..."
        }
    """
    return await _make_request("POST", "/merchant/pay/apply", {
        "transaction_id": transaction_id,
        "otp": int(otp),
        "store_id": int(store_id or ATMOS_STORE_ID or 0)
    })


async def get_transaction_info(transaction_id: int, store_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Get information about a transaction.

    Args:
        transaction_id: Transaction ID
        store_id: Store ID (uses env default if not provided)

    Returns:
        {
            "result": {"code": "...", "description": "..."},
            "store_transaction": { ...full transaction details... }
        }
    """
    return await _make_request("POST", "/merchant/pay/get", {
        "store_id": int(store_id or ATMOS_STORE_ID or 0),
        "transaction_id": transaction_id
    })


async def reverse_transaction(transaction_id: int, reason: str = "Refund") -> Dict[str, Any]:
    """
    Cancel/reverse a previously confirmed transaction.
    Returns funds to the card.

    Args:
        transaction_id: Transaction ID to reverse
        reason: Reason for reversal

    Returns:
        {
            "result": {"code": "OK", "description": "..."},
            "transaction_id": 000001
        }
    """
    return await _make_request("POST", "/merchant/pay/reverse", {
        "transaction_id": transaction_id,
        "reason": reason
    })


# ==============================================
# Callback Verification
# ==============================================

def verify_callback_sign(store_id: str, transaction_id: str, invoice: str, amount: str, sign: str) -> bool:
    """
    Verify the signature from Atmos Callback API.
    sign = sha256(store_id + transaction_id + invoice + amount + api_key)

    Args:
        store_id: Store ID
        transaction_id: Transaction ID
        invoice: Invoice number
        amount: Amount
        sign: Signature to verify

    Returns:
        True if signature is valid
    """
    if not ATMOS_API_KEY:
        logger.warning("ATMOS_API_KEY not set, cannot verify callback sign")
        return False

    raw = f"{store_id}{transaction_id}{invoice}{amount}{ATMOS_API_KEY}"
    expected_sign = hashlib.sha256(raw.encode()).hexdigest()
    return sign == expected_sign
