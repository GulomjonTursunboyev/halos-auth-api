from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum

router = APIRouter()

# In-memory storage (production'da database bo'ladi)
transactions_db: dict = {}
transaction_counter = 0

class TransactionType(str, Enum):
    income = "income"
    expense = "expense"

class TransactionCreate(BaseModel):
    type: TransactionType
    amount: float
    category: str
    description: Optional[str] = None
    date: Optional[datetime] = None
    telegram_id: Optional[int] = None
    source: str = "app"

class TransactionUpdate(BaseModel):
    type: Optional[TransactionType] = None
    amount: Optional[float] = None
    category: Optional[str] = None
    description: Optional[str] = None
    date: Optional[datetime] = None

class Transaction(BaseModel):
    id: int
    user_id: int
    telegram_id: Optional[int]
    type: TransactionType
    amount: float
    category: str
    description: Optional[str]
    date: datetime
    source: str
    created_at: datetime
    updated_at: Optional[datetime]

@router.get("/transactions")
async def get_transactions(
    telegram_id: Optional[int] = None,
    type: Optional[TransactionType] = None,
    category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
):
    user_key = str(telegram_id) if telegram_id else "default"
    user_transactions = transactions_db.get(user_key, [])
    
    # Filter
    filtered = user_transactions
    if type:
        filtered = [t for t in filtered if t["type"] == type]
    if category:
        filtered = [t for t in filtered if t["category"] == category]
    if start_date:
        filtered = [t for t in filtered if datetime.fromisoformat(t["date"]) >= start_date]
    if end_date:
        filtered = [t for t in filtered if datetime.fromisoformat(t["date"]) <= end_date]
    
    # Sort by date desc
    filtered.sort(key=lambda x: x["date"], reverse=True)
    
    return {
        "transactions": filtered[offset:offset+limit],
        "total": len(filtered)
    }

@router.post("/transactions")
async def create_transaction(data: TransactionCreate):
    global transaction_counter
    transaction_counter += 1
    
    user_key = str(data.telegram_id) if data.telegram_id else "default"
    
    transaction = {
        "id": transaction_counter,
        "user_id": data.telegram_id or 0,
        "telegram_id": data.telegram_id,
        "type": data.type,
        "amount": data.amount,
        "category": data.category,
        "description": data.description,
        "date": (data.date or datetime.now()).isoformat(),
        "source": data.source,
        "created_at": datetime.now().isoformat(),
        "updated_at": None
    }
    
    if user_key not in transactions_db:
        transactions_db[user_key] = []
    transactions_db[user_key].append(transaction)
    
    return transaction

@router.get("/transactions/stats")
async def get_transaction_stats(
    telegram_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
):
    user_key = str(telegram_id) if telegram_id else "default"
    user_transactions = transactions_db.get(user_key, [])
    
    total_income = sum(t["amount"] for t in user_transactions if t["type"] == "income")
    total_expense = sum(t["amount"] for t in user_transactions if t["type"] == "expense")
    
    by_category = {}
    for t in user_transactions:
        if t["type"] == "expense":
            by_category[t["category"]] = by_category.get(t["category"], 0) + t["amount"]
    
    return {
        "total_income": total_income,
        "total_expense": total_expense,
        "balance": total_income - total_expense,
        "by_category": by_category,
        "monthly": []
    }

@router.patch("/transactions/{id}")
async def update_transaction(id: int, data: TransactionUpdate):
    for user_key, transactions in transactions_db.items():
        for t in transactions:
            if t["id"] == id:
                if data.type:
                    t["type"] = data.type
                if data.amount:
                    t["amount"] = data.amount
                if data.category:
                    t["category"] = data.category
                if data.description is not None:
                    t["description"] = data.description
                if data.date:
                    t["date"] = data.date.isoformat()
                t["updated_at"] = datetime.now().isoformat()
                return t
    raise HTTPException(status_code=404, detail="Transaction not found")

@router.delete("/transactions/{id}")
async def delete_transaction(id: int):
    for user_key, transactions in transactions_db.items():
        for i, t in enumerate(transactions):
            if t["id"] == id:
                del transactions[i]
                return {"message": "Deleted"}
    raise HTTPException(status_code=404, detail="Transaction not found")
