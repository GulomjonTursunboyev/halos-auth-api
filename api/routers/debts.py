"""
Debts Router - PostgreSQL backed
Syncs with Telegram bot data
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum
from api.database import get_pool, is_db_available

router = APIRouter()

# Fallback in-memory storage (when no database)
debts_db: dict = {}
debt_counter = 0


class DebtStatus(str, Enum):
    active = "active"
    paid = "paid"
    overdue = "overdue"


class DebtCreate(BaseModel):
    is_lent: bool  # True = berdim (gave), False = oldim (took)
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


async def get_user_id_by_telegram(telegram_id: int) -> Optional[int]:
    pool = await get_pool()
    if not pool:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE telegram_id = $1",
            telegram_id
        )
        return row["id"] if row else None


@router.get("/debts")
async def get_debts(
    telegram_id: Optional[int] = None,
    is_lent: Optional[bool] = None,
):
    """Get all debts for a user - synced with Telegram bot"""
    pool = await get_pool()
    
    if pool and telegram_id:
        # Use PostgreSQL
        async with pool.acquire() as conn:
            # Get user_id from telegram_id
            user = await conn.fetchrow(
                "SELECT id FROM users WHERE telegram_id = $1",
                telegram_id
            )
            if not user:
                return {"debts": [], "total": 0}
            
            user_id = user["id"]
            
            # Fetch debts from personal_debts table
            # debt_type: 'gave' = berdim (is_lent=True), 'took' = oldim (is_lent=False)
            if is_lent is not None:
                debt_type = "gave" if is_lent else "took"
                rows = await conn.fetch(
                    \"\"\"SELECT id, user_id, debt_type, person_name, amount, description,
                              given_date, due_date, status, returned_amount, created_at
                       FROM personal_debts 
                       WHERE user_id = $1 AND debt_type = $2
                       ORDER BY given_date DESC\"\"\",
                    user_id, debt_type
                )
            else:
                rows = await conn.fetch(
                    \"\"\"SELECT id, user_id, debt_type, person_name, amount, description,
                              given_date, due_date, status, returned_amount, created_at
                       FROM personal_debts 
                       WHERE user_id = $1
                       ORDER BY given_date DESC\"\"\",
                    user_id
                )
            
            debts = []
            for row in rows:
                debt = {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "telegram_id": telegram_id,
                    "is_lent": row["debt_type"] == "gave",
                    "person_name": row["person_name"],
                    "phone_number": None,
                    "amount": float(row["amount"]),
                    "paid_amount": float(row["returned_amount"] or 0),
                    "currency": "UZS",
                    "description": row["description"],
                    "given_date": row["given_date"].isoformat() if row["given_date"] else None,
                    "due_date": row["due_date"].isoformat() if row["due_date"] else None,
                    "status": row["status"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
                debts.append(debt)
            
            return {"debts": debts, "total": len(debts)}
    
    # Fallback to in-memory
    user_key = str(telegram_id) if telegram_id else "default"
    user_debts = debts_db.get(user_key, [])
    filtered = user_debts
    if is_lent is not None:
        filtered = [d for d in filtered if d["is_lent"] == is_lent]
    filtered.sort(key=lambda x: x.get("given_date", ""), reverse=True)
    return {"debts": filtered, "total": len(filtered)}


@router.post("/debts")
async def create_debt(data: DebtCreate):
    """Create a new debt - synced with Telegram bot"""
    global debt_counter
    pool = await get_pool()
    
    if pool and data.telegram_id:
        async with pool.acquire() as conn:
            # Get user_id
            user = await conn.fetchrow(
                "SELECT id FROM users WHERE telegram_id = $1",
                data.telegram_id
            )
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            user_id = user["id"]
            debt_type = "gave" if data.is_lent else "took"
            given_date = data.given_date or datetime.now()
            
            # Insert into personal_debts (same table as Telegram bot)
            row = await conn.fetchrow(
                \"\"\"INSERT INTO personal_debts 
                       (user_id, debt_type, person_name, amount, description, 
                        given_date, due_date, status, returned_amount)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, 'active', 0)
                   RETURNING id, created_at\"\"\",
                user_id, debt_type, data.person_name, data.amount,
                data.description, given_date.date(), 
                data.due_date.date() if data.due_date else None
            )
            
            return {
                "id": row["id"],
                "user_id": user_id,
                "telegram_id": data.telegram_id,
                "is_lent": data.is_lent,
                "person_name": data.person_name,
                "amount": data.amount,
                "paid_amount": 0,
                "currency": "UZS",
                "description": data.description,
                "given_date": given_date.isoformat(),
                "due_date": data.due_date.isoformat() if data.due_date else None,
                "status": "active",
                "created_at": row["created_at"].isoformat()
            }
    
    # Fallback to in-memory
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
    }
    
    if user_key not in debts_db:
        debts_db[user_key] = []
    debts_db[user_key].append(debt)
    
    return debt


@router.get("/debts/{debt_id}")
async def get_debt(debt_id: int, telegram_id: Optional[int] = None):
    """Get a specific debt"""
    pool = await get_pool()
    
    if pool:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                \"\"\"SELECT d.*, u.telegram_id 
                   FROM personal_debts d
                   JOIN users u ON d.user_id = u.id
                   WHERE d.id = $1\"\"\",
                debt_id
            )
            if not row:
                raise HTTPException(status_code=404, detail="Debt not found")
            
            return {
                "id": row["id"],
                "user_id": row["user_id"],
                "telegram_id": row["telegram_id"],
                "is_lent": row["debt_type"] == "gave",
                "person_name": row["person_name"],
                "amount": float(row["amount"]),
                "paid_amount": float(row["returned_amount"] or 0),
                "currency": "UZS",
                "description": row["description"],
                "given_date": row["given_date"].isoformat() if row["given_date"] else None,
                "due_date": row["due_date"].isoformat() if row["due_date"] else None,
                "status": row["status"],
            }
    
    # Fallback
    raise HTTPException(status_code=404, detail="Debt not found")


@router.put("/debts/{debt_id}")
async def update_debt(debt_id: int, data: DebtUpdate, telegram_id: Optional[int] = None):
    """Update a debt"""
    pool = await get_pool()
    
    if pool:
        async with pool.acquire() as conn:
            # Build update query dynamically
            updates = []
            params = [debt_id]
            param_idx = 2
            
            if data.person_name is not None:
                updates.append(f"person_name = ${param_idx}")
                params.append(data.person_name)
                param_idx += 1
            
            if data.amount is not None:
                updates.append(f"amount = ${param_idx}")
                params.append(data.amount)
                param_idx += 1
            
            if data.paid_amount is not None:
                updates.append(f"returned_amount = ${param_idx}")
                params.append(data.paid_amount)
                param_idx += 1
            
            if data.description is not None:
                updates.append(f"description = ${param_idx}")
                params.append(data.description)
                param_idx += 1
            
            if data.due_date is not None:
                updates.append(f"due_date = ${param_idx}")
                params.append(data.due_date.date())
                param_idx += 1
            
            if data.status is not None:
                updates.append(f"status = ${param_idx}")
                params.append(data.status.value)
                param_idx += 1
            
            updates.append("updated_at = CURRENT_TIMESTAMP")
            
            if updates:
                query = f"UPDATE personal_debts SET {', '.join(updates)} WHERE id = $1 RETURNING *"
                row = await conn.fetchrow(query, *params)
                
                if row:
                    return {"message": "Debt updated", "id": debt_id}
    
    raise HTTPException(status_code=404, detail="Debt not found")


@router.post("/debts/{debt_id}/pay")
async def pay_debt(debt_id: int, payment: DebtPayment = None, telegram_id: Optional[int] = None):
    """Record a payment for a debt"""
    pool = await get_pool()
    
    if pool:
        async with pool.acquire() as conn:
            # Get current debt
            row = await conn.fetchrow(
                "SELECT * FROM personal_debts WHERE id = $1",
                debt_id
            )
            if not row:
                raise HTTPException(status_code=404, detail="Debt not found")
            
            current_paid = float(row["returned_amount"] or 0)
            total_amount = float(row["amount"])
            
            if payment and payment.amount:
                new_paid = current_paid + payment.amount
            else:
                new_paid = total_amount  # Full payment
            
            new_status = "paid" if new_paid >= total_amount else "active"
            
            await conn.execute(
                \"\"\"UPDATE personal_debts 
                   SET returned_amount = $1, status = $2, 
                       returned_date = CASE WHEN $2 = 'paid' THEN CURRENT_DATE ELSE returned_date END,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = $3\"\"\",
                new_paid, new_status, debt_id
            )
            
            return {
                "message": "Payment recorded",
                "id": debt_id,
                "paid_amount": new_paid,
                "remaining": max(0, total_amount - new_paid),
                "status": new_status
            }
    
    raise HTTPException(status_code=404, detail="Debt not found")


@router.delete("/debts/{debt_id}")
async def delete_debt(debt_id: int, telegram_id: Optional[int] = None):
    """Delete a debt"""
    pool = await get_pool()
    
    if pool:
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM personal_debts WHERE id = $1",
                debt_id
            )
            if "DELETE 1" in result:
                return {"message": "Debt deleted", "id": debt_id}
    
    raise HTTPException(status_code=404, detail="Debt not found")
