"""
Payments Router
================
Endpoints for Atmos payment processing:
- Create payment transaction
- Pre-apply (send OTP to cardholder)
- Apply (confirm payment with OTP)
- Get transaction info
- Reverse (refund) transaction

Supports both:
1. One-time card payment (card_number + expiry + OTP)
2. Bound card payment (card_token, no manual card entry needed)

Used for weekly/monthly subscription payments.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional
import logging
from datetime import datetime
from api.database import get_pool
from api.atmos import (
    create_transaction,
    pre_apply_transaction,
    apply_transaction,
    get_transaction_info,
    reverse_transaction,
    verify_callback_sign,
    AtmosError
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ==============================================
# Request/Response Models
# ==============================================

class CreatePaymentRequest(BaseModel):
    """Create a new payment"""
    user_id: int = Field(..., description="Telegram user ID")
    amount: int = Field(..., description="Amount in tiyin (100 tiyin = 1 so'm)", gt=0)
    description: str = Field(default="", description="Payment description")
    payment_type: str = Field(default="subscription", description="Payment type: subscription, weekly, monthly, one_time")


class PreApplyPaymentRequest(BaseModel):
    """Pre-apply payment (send OTP)"""
    transaction_id: int = Field(..., description="Transaction ID from create step")
    card_number: Optional[str] = Field(None, description="Card number (for one-time payment)")
    expiry: Optional[str] = Field(None, description="Card expiry YYMM (for one-time payment)")
    card_token: Optional[str] = Field(None, description="Card token (for bound card payment)")
    store_id: Optional[int] = Field(None, description="Store ID (optional, uses default)")


class ApplyPaymentRequest(BaseModel):
    """Confirm payment with OTP"""
    transaction_id: int = Field(..., description="Transaction ID")
    otp: str = Field(..., description="SMS OTP code", min_length=4, max_length=6)
    store_id: Optional[int] = Field(None, description="Store ID (optional)")
    user_id: int = Field(..., description="Telegram user ID")


class PaymentInfoRequest(BaseModel):
    """Get payment info"""
    transaction_id: int = Field(..., description="Transaction ID")
    store_id: Optional[int] = Field(None, description="Store ID (optional)")


class ReversePaymentRequest(BaseModel):
    """Reverse/refund a payment"""
    transaction_id: int = Field(..., description="Transaction ID to reverse")
    reason: str = Field(default="Qaytarish / Возврат", description="Reason for reversal")
    user_id: int = Field(..., description="Telegram user ID")


class PayWithBoundCardRequest(BaseModel):
    """One-step payment with a bound card (for auto-billing)"""
    user_id: int = Field(..., description="Telegram user ID")
    card_token: str = Field(..., description="Card token of bound card")
    amount: int = Field(..., description="Amount in tiyin", gt=0)
    description: str = Field(default="Obuna to'lovi / Оплата подписки")
    payment_type: str = Field(default="subscription")


# ==============================================
# Database helpers
# ==============================================

async def save_payment_record(
    user_id: int,
    atmos_transaction_id: int,
    amount: int,
    payment_type: str,
    description: str,
    status: str = "created"
) -> None:
    """Save payment record to database"""
    pool = await get_pool()
    if not pool:
        logger.warning("Database not available, cannot save payment")
        return

    try:
        async with pool.acquire() as conn:
            # Create payments table if not exists
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS atmos_payments (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    atmos_transaction_id BIGINT NOT NULL,
                    amount BIGINT NOT NULL,
                    payment_type TEXT DEFAULT 'subscription',
                    description TEXT DEFAULT '',
                    status TEXT DEFAULT 'created',
                    success_trans_id BIGINT,
                    ofd_url TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    confirmed_at TIMESTAMP,
                    reversed_at TIMESTAMP,
                    UNIQUE(atmos_transaction_id)
                )
            """)

            await conn.execute("""
                INSERT INTO atmos_payments (user_id, atmos_transaction_id, amount, payment_type, description, status)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (atmos_transaction_id) DO NOTHING
            """, user_id, atmos_transaction_id, amount, payment_type, description, status)

            logger.info(f"Payment record saved: user={user_id}, tx={atmos_transaction_id}, amount={amount}")
    except Exception as e:
        logger.error(f"Failed to save payment record: {e}")


async def update_payment_status(
    atmos_transaction_id: int,
    status: str,
    success_trans_id: Optional[int] = None,
    ofd_url: Optional[str] = None
) -> None:
    """Update payment status in database"""
    pool = await get_pool()
    if not pool:
        return

    try:
        async with pool.acquire() as conn:
            if status == "confirmed":
                await conn.execute("""
                    UPDATE atmos_payments 
                    SET status = $1, success_trans_id = $2, ofd_url = $3, confirmed_at = NOW()
                    WHERE atmos_transaction_id = $4
                """, status, success_trans_id, ofd_url, atmos_transaction_id)
            elif status == "reversed":
                await conn.execute("""
                    UPDATE atmos_payments 
                    SET status = $1, reversed_at = NOW()
                    WHERE atmos_transaction_id = $2
                """, status, atmos_transaction_id)
            else:
                await conn.execute("""
                    UPDATE atmos_payments SET status = $1 WHERE atmos_transaction_id = $2
                """, status, atmos_transaction_id)
    except Exception as e:
        logger.error(f"Failed to update payment status: {e}")


async def get_user_payments(user_id: int, limit: int = 50, offset: int = 0) -> list:
    """Get user's payment history"""
    pool = await get_pool()
    if not pool:
        return []

    try:
        async with pool.acquire() as conn:
            # Ensure table exists
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS atmos_payments (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    atmos_transaction_id BIGINT NOT NULL,
                    amount BIGINT NOT NULL,
                    payment_type TEXT DEFAULT 'subscription',
                    description TEXT DEFAULT '',
                    status TEXT DEFAULT 'created',
                    success_trans_id BIGINT,
                    ofd_url TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    confirmed_at TIMESTAMP,
                    reversed_at TIMESTAMP,
                    UNIQUE(atmos_transaction_id)
                )
            """)

            rows = await conn.fetch("""
                SELECT id, atmos_transaction_id, amount, payment_type, description, 
                       status, success_trans_id, ofd_url, created_at, confirmed_at, reversed_at
                FROM atmos_payments
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """, user_id, limit, offset)
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Failed to get user payments: {e}")
        return []


# ==============================================
# API Endpoints
# ==============================================

@router.post("/payments/create")
async def api_create_payment(request: CreatePaymentRequest):
    """
    Step 1: Create a payment transaction.
    Creates a draft in Atmos and saves to local database.
    """
    try:
        # Generate a unique account/invoice number
        account = f"HALOS-{request.user_id}-{int(datetime.now().timestamp())}"

        result = await create_transaction(
            amount=request.amount,
            account=account,
            lang="ru"
        )

        atmos_tx_id = result.get("transaction_id")

        # Save to database
        await save_payment_record(
            user_id=request.user_id,
            atmos_transaction_id=atmos_tx_id,
            amount=request.amount,
            payment_type=request.payment_type,
            description=request.description
        )

        return {
            "success": True,
            "transaction_id": atmos_tx_id,
            "amount": request.amount,
            "amount_formatted": f"{request.amount / 100:,.0f} so'm",
            "store_transaction": result.get("store_transaction"),
            "message": "To'lov yaratildi / Платёж создан"
        }
    except AtmosError as e:
        raise HTTPException(status_code=e.status_code, detail={
            "success": False,
            "code": e.code,
            "message": e.description
        })
    except Exception as e:
        logger.error(f"Create payment error: {e}")
        raise HTTPException(status_code=500, detail={
            "success": False,
            "message": f"Server xatosi: {str(e)}"
        })


@router.post("/payments/pre-apply")
async def api_pre_apply_payment(request: PreApplyPaymentRequest):
    """
    Step 2: Pre-apply payment (send OTP to card holder).
    Use card_number+expiry for one-time, or card_token for bound card.
    """
    try:
        result = await pre_apply_transaction(
            transaction_id=request.transaction_id,
            store_id=request.store_id,
            card_number=request.card_number,
            expiry=request.expiry,
            card_token=request.card_token
        )

        # Update status
        await update_payment_status(request.transaction_id, "pre_applied")

        return {
            "success": True,
            "transaction_id": result.get("transaction_id"),
            "message": "SMS kod yuborildi / SMS код отправлен"
        }
    except AtmosError as e:
        await update_payment_status(request.transaction_id, f"error:{e.code}")
        raise HTTPException(status_code=e.status_code, detail={
            "success": False,
            "code": e.code,
            "message": e.description
        })
    except Exception as e:
        logger.error(f"Pre-apply payment error: {e}")
        raise HTTPException(status_code=500, detail={
            "success": False,
            "message": f"Server xatosi: {str(e)}"
        })


@router.post("/payments/apply")
async def api_apply_payment(request: ApplyPaymentRequest):
    """
    Step 3: Confirm payment with OTP.
    Charges the card and finalizes the transaction.
    """
    try:
        result = await apply_transaction(
            transaction_id=request.transaction_id,
            otp=request.otp,
            store_id=request.store_id
        )

        store_tx = result.get("store_transaction", {})

        # Update status in database
        await update_payment_status(
            atmos_transaction_id=request.transaction_id,
            status="confirmed",
            success_trans_id=store_tx.get("success_trans_id"),
            ofd_url=result.get("ofd_url")
        )

        return {
            "success": True,
            "transaction_id": request.transaction_id,
            "success_trans_id": store_tx.get("success_trans_id"),
            "amount": store_tx.get("amount"),
            "amount_formatted": f"{store_tx.get('amount', 0) / 100:,.0f} so'm",
            "confirmed": store_tx.get("confirmed"),
            "ofd_url": result.get("ofd_url"),
            "message": "To'lov muvaffaqiyatli amalga oshirildi / Оплата прошла успешно"
        }
    except AtmosError as e:
        await update_payment_status(request.transaction_id, f"error:{e.code}")
        raise HTTPException(status_code=e.status_code, detail={
            "success": False,
            "code": e.code,
            "message": e.description
        })
    except Exception as e:
        logger.error(f"Apply payment error: {e}")
        raise HTTPException(status_code=500, detail={
            "success": False,
            "message": f"Server xatosi: {str(e)}"
        })


@router.post("/payments/info")
async def api_payment_info(request: PaymentInfoRequest):
    """
    Get information about a transaction from Atmos.
    """
    try:
        result = await get_transaction_info(
            transaction_id=request.transaction_id,
            store_id=request.store_id
        )

        store_tx = result.get("store_transaction", {})

        return {
            "success": True,
            "transaction": {
                "transaction_id": store_tx.get("trans_id"),
                "success_trans_id": store_tx.get("success_trans_id"),
                "amount": store_tx.get("amount"),
                "amount_formatted": f"{store_tx.get('amount', 0) / 100:,.0f} so'm",
                "confirmed": store_tx.get("confirmed"),
                "status_code": store_tx.get("status_code"),
                "status_message": store_tx.get("status_message"),
                "prepay_time": store_tx.get("prepay_time"),
                "confirm_time": store_tx.get("confirm_time"),
                "terminal_id": store_tx.get("terminal_id"),
                "account": store_tx.get("account")
            },
            "result": result.get("result")
        }
    except AtmosError as e:
        raise HTTPException(status_code=e.status_code, detail={
            "success": False,
            "code": e.code,
            "message": e.description
        })


@router.post("/payments/reverse")
async def api_reverse_payment(request: ReversePaymentRequest):
    """
    Reverse (refund) a previously confirmed payment.
    """
    try:
        result = await reverse_transaction(
            transaction_id=request.transaction_id,
            reason=request.reason
        )

        await update_payment_status(request.transaction_id, "reversed")

        return {
            "success": True,
            "transaction_id": result.get("transaction_id"),
            "message": "To'lov bekor qilindi / Оплата отменена"
        }
    except AtmosError as e:
        raise HTTPException(status_code=e.status_code, detail={
            "success": False,
            "code": e.code,
            "message": e.description
        })
    except Exception as e:
        logger.error(f"Reverse payment error: {e}")
        raise HTTPException(status_code=500, detail={
            "success": False,
            "message": f"Server xatosi: {str(e)}"
        })


@router.post("/payments/pay-with-card")
async def api_pay_with_bound_card(request: PayWithBoundCardRequest):
    """
    Full payment flow with bound card (for auto-billing).
    Creates transaction, pre-applies with card_token, and returns transaction.
    Since card_token is used, no OTP is needed from the user.
    
    Used for weekly/monthly automatic subscription charges.
    """
    try:
        # Step 1: Create transaction
        account = f"HALOS-{request.user_id}-{int(datetime.now().timestamp())}"
        create_result = await create_transaction(
            amount=request.amount,
            account=account,
            lang="ru"
        )

        atmos_tx_id = create_result.get("transaction_id")

        # Save to database
        await save_payment_record(
            user_id=request.user_id,
            atmos_transaction_id=atmos_tx_id,
            amount=request.amount,
            payment_type=request.payment_type,
            description=request.description
        )

        # Step 2: Pre-apply with card token
        pre_result = await pre_apply_transaction(
            transaction_id=atmos_tx_id,
            card_token=request.card_token
        )

        await update_payment_status(atmos_tx_id, "pre_applied")

        return {
            "success": True,
            "transaction_id": atmos_tx_id,
            "amount": request.amount,
            "amount_formatted": f"{request.amount / 100:,.0f} so'm",
            "message": "SMS kod yuborilib, tasdiqlash kutilmoqda / SMS код отправлен, ожидается подтверждение",
            "next_step": "Call /payments/apply with transaction_id and OTP"
        }
    except AtmosError as e:
        raise HTTPException(status_code=e.status_code, detail={
            "success": False,
            "code": e.code,
            "message": e.description
        })
    except Exception as e:
        logger.error(f"Pay with bound card error: {e}")
        raise HTTPException(status_code=500, detail={
            "success": False,
            "message": f"Server xatosi: {str(e)}"
        })


@router.get("/payments/history/{user_id}")
async def api_payment_history(user_id: int, limit: int = 50, offset: int = 0):
    """
    Get user's payment history from the local database.
    """
    try:
        payments = await get_user_payments(user_id, limit, offset)
        return {
            "success": True,
            "payments": payments,
            "count": len(payments),
            "user_id": user_id
        }
    except Exception as e:
        logger.error(f"Payment history error: {e}")
        raise HTTPException(status_code=500, detail={
            "success": False,
            "message": f"Server xatosi: {str(e)}"
        })


# ==============================================
# Atmos Callback Endpoint
# ==============================================

@router.post("/payments/callback")
async def atmos_callback(request: Request):
    """
    Callback endpoint for Atmos to notify about payment status.
    Atmos sends: store_id, transaction_id, invoice, amount, sign
    
    The sign is verified using: sha256(store_id + transaction_id + invoice + amount + api_key)
    
    Must return {"status": 1, "message": "Success"} to confirm.
    """
    try:
        body = await request.json()
        logger.info(f"Atmos callback received: {body}")

        store_id = str(body.get("store_id", ""))
        transaction_id = str(body.get("transaction_id", ""))
        invoice = str(body.get("invoice", ""))
        amount = str(body.get("amount", ""))
        sign = str(body.get("sign", ""))

        # Verify signature
        if not verify_callback_sign(store_id, transaction_id, invoice, amount, sign):
            logger.warning(f"Invalid callback sign for tx {transaction_id}")
            return {"status": 0, "message": "Invalid sign"}

        # Update payment status
        await update_payment_status(int(transaction_id), "callback_confirmed")

        logger.info(f"Atmos callback confirmed for tx {transaction_id}")
        return {"status": 1, "message": "Успешно"}

    except Exception as e:
        logger.error(f"Atmos callback error: {e}")
        return {"status": 0, "message": f"Error: {str(e)}"}
