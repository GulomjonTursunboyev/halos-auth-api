"""
Transactions Router - PostgreSQL backed
Syncs with Telegram bot data
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum
from api.database import get_pool, is_db_available

router = APIRouter()

# Fallback in-memory storage
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


@router.get("/transactions")
async def get_transactions(
    telegram_id: Optional[int] = None,
    type: Optional[TransactionType] = None,
    category: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
):
    """Get transactions for a user - synced with Telegram bot"""
    pool = await get_pool()
    
    if pool and telegram_id:
        async with pool.acquire() as conn:
            # Get user_id from telegram_id
            user = await conn.fetchrow(
                "SELECT id FROM users WHERE telegram_id = $1",
                telegram_id
            )
            if not user:
                return {"transactions": [], "total": 0}
            
            user_id = user["id"]
            
            # Build query
            conditions = ["user_id = $1"]
            params = [user_id]
            param_idx = 2
            
            if type:
                conditions.append(f"type = ${param_idx}")
                params.append(type.value)
                param_idx += 1
            
            if category:
                conditions.append(f"category = ${param_idx}")
                params.append(category)
                param_idx += 1
            
            where_clause = " AND ".join(conditions)
            
            # Count total
            count_row = await conn.fetchrow(
                f"SELECT COUNT(*) as total FROM transactions WHERE {where_clause}",
                *params
            )
            total = count_row["total"]
            
            # Fetch transactions
            params.extend([limit, offset])
            rows = await conn.fetch(
                f"""SELECT id, user_id, type, category, category_key, amount, 
                          description, original_text, created_at
                   FROM transactions 
                   WHERE {where_clause}
                   ORDER BY created_at DESC
                   LIMIT ${param_idx} OFFSET ${param_idx + 1}""",
                *params
            )
            
            transactions = []
            for row in rows:
                tx = {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "telegram_id": telegram_id,
                    "type": row["type"],
                    "amount": float(row["amount"]),
                    "category": row["category"],
                    "category_key": row["category_key"],
                    "description": row["description"] or row["original_text"],
                    "date": row["created_at"].isoformat() if row["created_at"] else None,
                    "source": "telegram" if row["original_text"] else "app",
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
                transactions.append(tx)
            
            return {"transactions": transactions, "total": total}
    
    # Fallback to in-memory
    user_key = str(telegram_id) if telegram_id else "default"
    user_txs = transactions_db.get(user_key, [])
    
    filtered = user_txs
    if type:
        filtered = [t for t in filtered if t["type"] == type.value]
    if category:
        filtered = [t for t in filtered if t["category"] == category]
    
    filtered.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    total = len(filtered)
    filtered = filtered[offset:offset + limit]
    
    return {"transactions": filtered, "total": total}


@router.post("/transactions")
async def create_transaction(data: TransactionCreate):
    """Create a new transaction - synced with Telegram bot"""
    global transaction_counter
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
            
            # Insert transaction (same table as Telegram bot)
            row = await conn.fetchrow(
                """INSERT INTO transactions 
                       (user_id, type, category, amount, description, original_text)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   RETURNING id, created_at""",
                user_id, data.type.value, data.category, data.amount,
                data.description, data.description
            )
            
            return {
                "id": row["id"],
                "user_id": user_id,
                "telegram_id": data.telegram_id,
                "type": data.type.value,
                "amount": data.amount,
                "category": data.category,
                "description": data.description,
                "date": (data.date or datetime.now()).isoformat(),
                "source": data.source,
                "created_at": row["created_at"].isoformat()
            }
    
    # Fallback to in-memory
    transaction_counter += 1
    user_key = str(data.telegram_id) if data.telegram_id else "default"
    
    tx = {
        "id": transaction_counter,
        "user_id": data.telegram_id or 0,
        "telegram_id": data.telegram_id,
        "type": data.type.value,
        "amount": data.amount,
        "category": data.category,
        "description": data.description,
        "date": (data.date or datetime.now()).isoformat(),
        "source": data.source,
        "created_at": datetime.now().isoformat(),
    }
    
    if user_key not in transactions_db:
        transactions_db[user_key] = []
    transactions_db[user_key].append(tx)
    
    return tx


@router.get("/transactions/{tx_id}")
async def get_transaction(tx_id: int, telegram_id: Optional[int] = None):
    """Get a specific transaction"""
    pool = await get_pool()
    
    if pool:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT t.*, u.telegram_id 
                   FROM transactions t
                   JOIN users u ON t.user_id = u.id
                   WHERE t.id = $1""",
                tx_id
            )
            if not row:
                raise HTTPException(status_code=404, detail="Transaction not found")
            
            return {
                "id": row["id"],
                "user_id": row["user_id"],
                "telegram_id": row["telegram_id"],
                "type": row["type"],
                "amount": float(row["amount"]),
                "category": row["category"],
                "description": row["description"],
                "date": row["created_at"].isoformat() if row["created_at"] else None,
                "source": "telegram" if row["original_text"] else "app",
            }
    
    raise HTTPException(status_code=404, detail="Transaction not found")


@router.delete("/transactions/{tx_id}")
async def delete_transaction(tx_id: int, telegram_id: Optional[int] = None):
    """Delete a transaction"""
    pool = await get_pool()
    
    if pool:
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM transactions WHERE id = $1",
                tx_id
            )
            if "DELETE 1" in result:
                return {"message": "Transaction deleted", "id": tx_id}
    
    raise HTTPException(status_code=404, detail="Transaction not found")


@router.get("/transactions/summary")
async def get_transactions_summary(
    telegram_id: Optional[int] = None,
    period: str = "month",
):
    """Get transactions summary - total income/expense"""
    pool = await get_pool()
    
    if pool and telegram_id:
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT id FROM users WHERE telegram_id = $1",
                telegram_id
            )
            if not user:
                return {"total_income": 0, "total_expense": 0, "balance": 0}
            
            user_id = user["id"]
            
            # Get current month/week date range
            if period == "month":
                date_condition = "created_at >= DATE_TRUNC('month', CURRENT_DATE)"
            elif period == "week":
                date_condition = "created_at >= DATE_TRUNC('week', CURRENT_DATE)"
            else:
                date_condition = "1=1"
            
            row = await conn.fetchrow(
                f"""SELECT 
                        COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0) as total_income,
                        COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0) as total_expense
                   FROM transactions 
                   WHERE user_id = $1 AND {date_condition}""",
                user_id
            )
            
            income = float(row["total_income"])
            expense = float(row["total_expense"])
            
            return {
                "total_income": income,
                "total_expense": expense,
                "balance": income - expense,
                "period": period
            }
    
    return {"total_income": 0, "total_expense": 0, "balance": 0, "period": period}
