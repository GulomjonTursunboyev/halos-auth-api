from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()

# In-memory users storage
users_db: dict = {}

class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    language_code: Optional[str] = None

@router.get("/user/profile")
async def get_user_profile(telegram_id: Optional[int] = None):
    if not telegram_id:
        raise HTTPException(status_code=400, detail="telegram_id required")
    
    user_key = str(telegram_id)
    user = users_db.get(user_key)
    
    if not user:
        # Create default user
        user = {
            "id": telegram_id,
            "telegram_id": telegram_id,
            "first_name": "User",
            "last_name": None,
            "username": None,
            "photo_url": None,
            "phone_number": None,
            "language_code": "uz",
            "is_premium": False,
            "created_at": datetime.now().isoformat(),
            "last_active_at": datetime.now().isoformat()
        }
        users_db[user_key] = user
    
    # Import stats from transactions and debts routers
    from api.routers.transactions import transactions_db
    from api.routers.debts import debts_db
    
    user_transactions = transactions_db.get(user_key, [])
    user_debts = debts_db.get(user_key, [])
    
    total_income = sum(t["amount"] for t in user_transactions if t["type"] == "income")
    total_expense = sum(t["amount"] for t in user_transactions if t["type"] == "expense")
    
    active_debts = [d for d in user_debts if d["status"] == "active"]
    total_lent = sum(d["amount"] - d["paid_amount"] for d in active_debts if d["is_lent"])
    total_borrowed = sum(d["amount"] - d["paid_amount"] for d in active_debts if not d["is_lent"])
    
    return {
        "user": user,
        "balance": total_income - total_expense,
        "transaction_stats": {
            "total_income": total_income,
            "total_expense": total_expense,
            "balance": total_income - total_expense,
            "by_category": {},
            "monthly": []
        },
        "debt_stats": {
            "total_lent": total_lent,
            "total_borrowed": total_borrowed,
            "active_count": len(active_debts),
            "overdue_count": 0
        }
    }

@router.patch("/user/profile")
async def update_user_profile(data: UserUpdate, telegram_id: Optional[int] = None):
    if not telegram_id:
        raise HTTPException(status_code=400, detail="telegram_id required")
    
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
    
    user["last_active_at"] = datetime.now().isoformat()
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
        "photo_url": existing.get("photo_url"),
        "phone_number": existing.get("phone_number"),
        "language_code": existing.get("language_code", "uz"),
        "is_premium": existing.get("is_premium", False),
        "created_at": existing.get("created_at", datetime.now().isoformat()),
        "last_active_at": datetime.now().isoformat()
    }
    
    users_db[user_key] = user
    return user
