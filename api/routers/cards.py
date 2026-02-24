"""
Card Binding Router
===================
Endpoints for binding/unbinding Uzcard/Humo cards via Atmos API.
Users can bind their cards to enable recurring payments and
view card transaction history.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
import logging
from api.database import get_pool
from api.atmos import (
    bind_card_init,
    bind_card_confirm,
    list_bound_cards,
    remove_bound_card,
    AtmosError
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ==============================================
# Request/Response Models
# ==============================================

class CardBindInitRequest(BaseModel):
    """Request to start card binding"""
    card_number: str = Field(..., description="Card number (16 digits)", min_length=16, max_length=16)
    expiry: str = Field(..., description="Card expiry in YYMM format (e.g., '2410')", min_length=4, max_length=4)
    user_id: int = Field(..., description="Telegram user ID")


class CardBindConfirmRequest(BaseModel):
    """Request to confirm card binding with OTP"""
    transaction_id: int = Field(..., description="Transaction ID from init step")
    otp: str = Field(..., description="SMS OTP code", min_length=4, max_length=6)
    user_id: int = Field(..., description="Telegram user ID")


class CardRemoveRequest(BaseModel):
    """Request to remove a bound card"""
    card_id: int = Field(..., description="Card ID")
    card_token: str = Field(..., description="Card token")
    user_id: int = Field(..., description="Telegram user ID")


class UserCardsRequest(BaseModel):
    """Request to get user's cards"""
    user_id: int = Field(..., description="Telegram user ID")


# ==============================================
# Database helpers
# ==============================================

async def save_user_card(user_id: int, card_data: dict) -> None:
    """Save a bound card to the database linked to user"""
    pool = await get_pool()
    if not pool:
        logger.warning("Database not available, cannot save card")
        return

    try:
        async with pool.acquire() as conn:
            # Create cards table if not exists
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_cards (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    card_id BIGINT NOT NULL,
                    card_token TEXT NOT NULL,
                    pan TEXT,
                    expiry TEXT,
                    card_holder TEXT,
                    phone TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(user_id, card_id)
                )
            """)

            await conn.execute("""
                INSERT INTO user_cards (user_id, card_id, card_token, pan, expiry, card_holder, phone)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (user_id, card_id) 
                DO UPDATE SET 
                    card_token = EXCLUDED.card_token,
                    pan = EXCLUDED.pan,
                    expiry = EXCLUDED.expiry,
                    card_holder = EXCLUDED.card_holder,
                    phone = EXCLUDED.phone,
                    is_active = TRUE
            """,
                user_id,
                card_data.get("card_id"),
                card_data.get("card_token"),
                card_data.get("pan"),
                card_data.get("expiry"),
                card_data.get("card_holder"),
                card_data.get("phone")
            )
            logger.info(f"Card {card_data.get('pan')} saved for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to save card: {e}")


async def deactivate_user_card(user_id: int, card_id: int) -> None:
    """Mark a card as inactive in the database"""
    pool = await get_pool()
    if not pool:
        return

    try:
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE user_cards SET is_active = FALSE 
                WHERE user_id = $1 AND card_id = $2
            """, user_id, card_id)
    except Exception as e:
        logger.error(f"Failed to deactivate card: {e}")


async def get_user_cards_from_db(user_id: int) -> list:
    """Get user's active cards from database"""
    pool = await get_pool()
    if not pool:
        return []

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT card_id, card_token, pan, expiry, card_holder, phone, created_at
                FROM user_cards 
                WHERE user_id = $1 AND is_active = TRUE
                ORDER BY created_at DESC
            """, user_id)
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Failed to get user cards: {e}")
        return []


# ==============================================
# API Endpoints
# ==============================================

@router.post("/cards/bind/init")
async def api_bind_card_init(request: CardBindInitRequest):
    """
    Step 1: Start card binding process.
    Sends SMS OTP to the cardholder's phone.
    
    Returns transaction_id to use in confirmation step.
    """
    try:
        result = await bind_card_init(request.card_number, request.expiry)
        return {
            "success": True,
            "transaction_id": result.get("transaction_id"),
            "phone": result.get("phone"),
            "message": "SMS kod yuborildi / SMS код отправлен"
        }
    except AtmosError as e:
        raise HTTPException(status_code=e.status_code, detail={
            "success": False,
            "code": e.code,
            "message": e.description
        })
    except Exception as e:
        logger.error(f"Card bind init error: {e}")
        raise HTTPException(status_code=500, detail={
            "success": False,
            "message": "Server xatosi / Ошибка сервера"
        })


@router.post("/cards/bind/confirm")
async def api_bind_card_confirm(request: CardBindConfirmRequest):
    """
    Step 2: Confirm card binding with OTP code.
    Saves the card token to the database for future payments.
    
    Returns card details including masked PAN and card_token.
    """
    try:
        result = await bind_card_confirm(request.transaction_id, request.otp)
        
        card_data = result.get("data", {})
        
        # Save card to database
        await save_user_card(request.user_id, card_data)

        return {
            "success": True,
            "card": {
                "card_id": card_data.get("card_id"),
                "pan": card_data.get("pan"),
                "expiry": card_data.get("expiry"),
                "card_holder": card_data.get("card_holder"),
                "balance": card_data.get("balance"),
                "phone": card_data.get("phone")
            },
            "message": "Karta muvaffaqiyatli bog'landi / Карта успешно привязана"
        }
    except AtmosError as e:
        raise HTTPException(status_code=e.status_code, detail={
            "success": False,
            "code": e.code,
            "message": e.description
        })
    except Exception as e:
        logger.error(f"Card bind confirm error: {e}")
        raise HTTPException(status_code=500, detail={
            "success": False,
            "message": "Server xatosi / Ошибка сервера"
        })


@router.post("/cards/list")
async def api_list_user_cards(request: UserCardsRequest):
    """
    Get list of user's bound cards from the database.
    """
    try:
        cards = await get_user_cards_from_db(request.user_id)
        return {
            "success": True,
            "cards": cards,
            "count": len(cards)
        }
    except Exception as e:
        logger.error(f"List cards error: {e}")
        raise HTTPException(status_code=500, detail={
            "success": False,
            "message": "Server xatosi / Ошибка сервера"
        })


@router.post("/cards/remove")
async def api_remove_card(request: CardRemoveRequest):
    """
    Remove (unbind) a previously bound card.
    Removes from both Atmos and the local database.
    """
    try:
        # Remove from Atmos
        result = await remove_bound_card(request.card_id, request.card_token)

        # Deactivate in local database
        await deactivate_user_card(request.user_id, request.card_id)

        return {
            "success": True,
            "message": "Karta muvaffaqiyatli olib tashlandi / Карта успешно удалена"
        }
    except AtmosError as e:
        raise HTTPException(status_code=e.status_code, detail={
            "success": False,
            "code": e.code,
            "message": e.description
        })
    except Exception as e:
        logger.error(f"Remove card error: {e}")
        raise HTTPException(status_code=500, detail={
            "success": False,
            "message": "Server xatosi / Ошибка сервера"
        })


@router.get("/cards/bound")
async def api_list_all_bound_cards(page: int = 1, page_size: int = 50):
    """
    Get all cards bound to the merchant from Atmos (admin endpoint).
    """
    try:
        result = await list_bound_cards(page, page_size)
        return {
            "success": True,
            "cards": result.get("cardDataSmallList", []),
            "page": page,
            "page_size": page_size
        }
    except AtmosError as e:
        raise HTTPException(status_code=e.status_code, detail={
            "success": False,
            "code": e.code,
            "message": e.description
        })
