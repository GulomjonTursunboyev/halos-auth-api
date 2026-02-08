from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum

router = APIRouter()

# In-memory storage
debts_db: dict = {}
debt_counter = 0

class DebtStatus(str, Enum):
    active = "active"
    paid = "paid"
    overdue = "overdue"

class DebtCreate(BaseModel):
    is_lent: bool
    person_name: str
    amount: float
    phone_number: Optional[str] = None
    description: Optional[str] = None
    given_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    telegram_id: Optional[int] = None

class DebtUpdate(BaseModel):
    person_name: Optional[str] = None
    amount: Optional[float] = None
    paid_amount: Optional[float] = None
    phone_number: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    status: Optional[DebtStatus] = None

class DebtPayment(BaseModel):
    amount: Optional[float] = None

@router.get("/debts")
async def get_debts(
    telegram_id: Optional[int] = None,
    is_lent: Optional[bool] = None,
):
    user_key = str(telegram_id) if telegram_id else "default"
    user_debts = debts_db.get(user_key, [])
    
    filtered = user_debts
    if is_lent is not None:
        filtered = [d for d in filtered if d["is_lent"] == is_lent]
    
    # Sort by date desc
    filtered.sort(key=lambda x: x["given_date"], reverse=True)
    
    return {
        "debts": filtered,
        "total": len(filtered)
    }

@router.post("/debts")
async def create_debt(data: DebtCreate):
    global debt_counter
    debt_counter += 1
    
    user_key = str(data.telegram_id) if data.telegram_id else "default"
    
    debt = {
        "id": debt_counter,
        "user_id": data.telegram_id or 0,
        "telegram_id": data.telegram_id,
        "is_lent": data.is_lent,
        "person_name": data.person_name,
        "phone_number": data.phone_number,
        "amount": data.amount,
        "paid_amount": 0,
        "currency": "UZS",
        "description": data.description,
        "given_date": (data.given_date or datetime.now()).isoformat(),
        "due_date": data.due_date.isoformat() if data.due_date else None,
        "status": "active",
        "created_at": datetime.now().isoformat(),
        "updated_at": None
    }
    
    if user_key not in debts_db:
        debts_db[user_key] = []
    debts_db[user_key].append(debt)
    
    return debt

@router.get("/debts/stats")
async def get_debt_stats(telegram_id: Optional[int] = None):
    user_key = str(telegram_id) if telegram_id else "default"
    user_debts = debts_db.get(user_key, [])
    
    active_debts = [d for d in user_debts if d["status"] == "active"]
    overdue_debts = [d for d in user_debts if d["status"] == "overdue"]
    
    total_lent = sum(d["amount"] - d["paid_amount"] for d in active_debts if d["is_lent"])
    total_borrowed = sum(d["amount"] - d["paid_amount"] for d in active_debts if not d["is_lent"])
    
    return {
        "total_lent": total_lent,
        "total_borrowed": total_borrowed,
        "active_count": len(active_debts),
        "overdue_count": len(overdue_debts)
    }

@router.patch("/debts/{id}")
async def update_debt(id: int, data: DebtUpdate):
    for user_key, debts in debts_db.items():
        for d in debts:
            if d["id"] == id:
                if data.person_name:
                    d["person_name"] = data.person_name
                if data.amount:
                    d["amount"] = data.amount
                if data.paid_amount is not None:
                    d["paid_amount"] = data.paid_amount
                if data.phone_number is not None:
                    d["phone_number"] = data.phone_number
                if data.description is not None:
                    d["description"] = data.description
                if data.due_date:
                    d["due_date"] = data.due_date.isoformat()
                if data.status:
                    d["status"] = data.status
                d["updated_at"] = datetime.now().isoformat()
                return d
    raise HTTPException(status_code=404, detail="Debt not found")

@router.post("/debts/{id}/pay")
async def pay_debt(id: int, data: DebtPayment):
    for user_key, debts in debts_db.items():
        for d in debts:
            if d["id"] == id:
                if data.amount:
                    d["paid_amount"] += data.amount
                else:
                    d["paid_amount"] = d["amount"]
                
                if d["paid_amount"] >= d["amount"]:
                    d["status"] = "paid"
                
                d["updated_at"] = datetime.now().isoformat()
                return d
    raise HTTPException(status_code=404, detail="Debt not found")

@router.delete("/debts/{id}")
async def delete_debt(id: int):
    for user_key, debts in debts_db.items():
        for i, d in enumerate(debts):
            if d["id"] == id:
                del debts[i]
                return {"message": "Deleted"}
    raise HTTPException(status_code=404, detail="Debt not found")
