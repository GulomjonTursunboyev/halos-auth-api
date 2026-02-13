"""
Users Router - PostgreSQL backed
User profile and statistics from Telegram bot database
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from api.database import get_pool, is_db_available

router = APIRouter()

# In-memory users storage (fallback)
users_db: dict = {}


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    language_code: Optional[str] = None


@router.get("/user/profile")
async def get_user_profile(telegram_id: Optional[int] = None):
    """Get user profile with stats - reads from Telegram bot's database"""
    if not telegram_id:
        raise HTTPException(status_code=400, detail="telegram_id required")
    
    pool = await get_pool()
    
    if pool:
        async with pool.acquire() as conn:
            # Get user from bot's users table
            user_row = await conn.fetchrow(
                "SELECT * FROM users WHERE telegram_id = $1",
                telegram_id
            )
            
            if not user_row:
                return {
                    "user": {
                        "id": telegram_id,
                        "telegram_id": telegram_id,
                        "first_name": "User",
                        "last_name": None,
                        "username": None,
                        "phone_number": None,
                        "language_code": "uz",
                        "is_premium": False,
                        "subscription_tier": "free",
                        "created_at": datetime.now().isoformat()
                    },
                    "balance": 0,
                    "transaction_stats": {
                        "total_income": 0,
                        "total_expense": 0,
                        "balance": 0,
                    },
                    "debt_stats": {
                        "total_lent": 0,
                        "total_borrowed": 0,
                        "active_count": 0,
                    }
                }
            
            user_id = user_row["id"]
            
            # Build user profile from DB
            user = {
                "id": user_row["id"],
                "telegram_id": user_row["telegram_id"],
                "first_name": user_row.get("first_name"),
                "last_name": user_row.get("last_name"),
                "username": user_row.get("username"),
                "phone_number": user_row.get("phone_number"),
                "language_code": user_row.get("language", "uz"),
                "is_premium": user_row.get("subscription_tier", "free") != "free",
                "subscription_tier": user_row.get("subscription_tier", "free"),
                "created_at": user_row["created_at"].isoformat() if user_row.get("created_at") else None,
                "last_active": user_row["last_active"].isoformat() if user_row.get("last_active") else None,
            }
            
            # Get transaction stats
            tx_stats = await conn.fetchrow(
                """SELECT 
                    COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0) as total_income,
                    COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0) as total_expense
                FROM transactions WHERE user_id = $1""",
                user_id
            )
            
            total_income = float(tx_stats["total_income"])
            total_expense = float(tx_stats["total_expense"])
            
            # Get debt stats
            debt_stats = await conn.fetchrow(
                """SELECT 
                    COALESCE(SUM(CASE WHEN debt_type = 'gave' AND status = 'active' THEN amount - COALESCE(returned_amount, 0) ELSE 0 END), 0) as total_lent,
                    COALESCE(SUM(CASE WHEN debt_type = 'took' AND status = 'active' THEN amount - COALESCE(returned_amount, 0) ELSE 0 END), 0) as total_borrowed,
                    COUNT(CASE WHEN status = 'active' THEN 1 END) as active_count
                FROM personal_debts WHERE user_id = $1""",
                user_id
            )
            
            return {
                "user": user,
                "balance": total_income - total_expense,
                "transaction_stats": {
                    "total_income": total_income,
                    "total_expense": total_expense,
                    "balance": total_income - total_expense,
                },
                "debt_stats": {
                    "total_lent": float(debt_stats["total_lent"]),
                    "total_borrowed": float(debt_stats["total_borrowed"]),
                    "active_count": int(debt_stats["active_count"]),
                }
            }
    
    # Fallback to in-memory
    user_key = str(telegram_id)
    user = users_db.get(user_key)
    
    if not user:
        user = {
            "id": telegram_id,
            "telegram_id": telegram_id,
            "first_name": "User",
            "last_name": None,
            "username": None,
            "phone_number": None,
            "language_code": "uz",
            "is_premium": False,
            "created_at": datetime.now().isoformat(),
        }
        users_db[user_key] = user
    
    return {
        "user": user,
        "balance": 0,
        "transaction_stats": {"total_income": 0, "total_expense": 0, "balance": 0},
        "debt_stats": {"total_lent": 0, "total_borrowed": 0, "active_count": 0}
    }


@router.patch("/user/profile")
async def update_user_profile(data: UserUpdate, telegram_id: Optional[int] = None):
    """Update user profile"""
    if not telegram_id:
        raise HTTPException(status_code=400, detail="telegram_id required")
    
    pool = await get_pool()
    
    if pool:
        async with pool.acquire() as conn:
            # Build update query
            updates = []
            params = [telegram_id]
            param_idx = 2
            
            if data.first_name is not None:
                updates.append(f"first_name = ${param_idx}")
                params.append(data.first_name)
                param_idx += 1
            
            if data.last_name is not None:
                updates.append(f"last_name = ${param_idx}")
                params.append(data.last_name)
                param_idx += 1
            
            if data.phone_number is not None:
                updates.append(f"phone_number = ${param_idx}")
                params.append(data.phone_number)
                param_idx += 1
            
            if data.language_code is not None:
                updates.append(f"language = ${param_idx}")
                params.append(data.language_code)
                param_idx += 1
            
            if updates:
                updates.append("updated_at = CURRENT_TIMESTAMP")
                query = f"UPDATE users SET {', '.join(updates)} WHERE telegram_id = $1 RETURNING *"
                row = await conn.fetchrow(query, *params)
                
                if row:
                    return {
                        "id": row["id"],
                        "telegram_id": row["telegram_id"],
                        "first_name": row.get("first_name"),
                        "last_name": row.get("last_name"),
                        "username": row.get("username"),
                        "phone_number": row.get("phone_number"),
                        "language_code": row.get("language", "uz"),
                    }
        
        raise HTTPException(status_code=404, detail="User not found")
    
    # Fallback to in-memory
    user_key = str(telegram_id)
    user = users_db.get(user_key)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if data.first_name:
        user["first_name"] = data.first_name
    if data.last_name is not None:
        user["last_name"] = data.last_name
    if data.phone_number is not None:
        user["phone_number"] = data.phone_number
    if data.language_code:
        user["language_code"] = data.language_code
    
    users_db[user_key] = user
    return user


# Store user after telegram login
def save_telegram_user(telegram_id: int, username: str = None, first_name: str = None, last_name: str = None):
    user_key = str(telegram_id)
    existing = users_db.get(user_key, {})
    
    user = {
        "id": telegram_id,
        "telegram_id": telegram_id,
        "first_name": first_name or existing.get("first_name", "User"),
        "last_name": last_name or existing.get("last_name"),
        "username": username or existing.get("username"),
        "phone_number": existing.get("phone_number"),
        "language_code": existing.get("language_code", "uz"),
        "is_premium": existing.get("is_premium", False),
        "created_at": existing.get("created_at", datetime.now().isoformat()),
        "last_active_at": datetime.now().isoformat()
    }
    
    users_db[user_key] = user
    return user
