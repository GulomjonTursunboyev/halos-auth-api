from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from api.database import get_pool
from api.engine import FinancialInput, FinancialEngine
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

class PlanInput(BaseModel):
    income_self: float = 0
    income_partner: float = 0
    rent: float = 0
    kindergarten: float = 0
    utilities: float = 0
    loan_payment: float = 0
    total_debt: float = 0

@router.get("/plan/current")
async def get_current_plan(telegram_id: int):
    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    async with pool.acquire() as conn:
        # Get user ID and mode
        user = await conn.fetchrow("SELECT id, mode FROM users WHERE telegram_id = $1", telegram_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_id = user['id']
        profile = await conn.fetchrow("SELECT * FROM financial_profiles WHERE user_id = $1", user_id)
        
        result = None
        if profile:
            try:
                input_data = FinancialInput(
                    mode=user['mode'] or 'solo',
                    income_self=profile['income_self'] or 0,
                    income_partner=profile['income_partner'] or 0,
                    rent=profile['rent'] or 0,
                    kindergarten=profile['kindergarten'] or 0,
                    utilities=profile['utilities'] or 0,
                    loan_payment=profile['loan_payment'] or 0,
                    total_debt=profile['total_debt'] or 0
                )
                engine = FinancialEngine(input_data)
                result = engine.calculate()
            except Exception as e:
                logger.error(f"Calculation error: {e}")
        
        return {
            "profile": dict(profile) if profile else None,
            "result": result
        }

@router.post("/plan/calculate")
async def calculate_plan(telegram_id: int, plan: PlanInput):
    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    async with pool.acquire() as conn:
        # Get user
        user = await conn.fetchrow("SELECT id, mode FROM users WHERE telegram_id = $1", telegram_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_id = user['id']
        mode = user['mode'] or 'solo'
        
        # Update Profiles
        existing = await conn.fetchval("SELECT id FROM financial_profiles WHERE user_id=$1", user_id)
        
        if existing:
            profile_id = await conn.fetchval("""
                UPDATE financial_profiles 
                SET income_self=$2, income_partner=$3, rent=$4, kindergarten=$5, utilities=$6, loan_payment=$7, total_debt=$8, updated_at=CURRENT_TIMESTAMP
                WHERE user_id=$1 RETURNING id
            """, user_id, plan.income_self, plan.income_partner, plan.rent, plan.kindergarten, plan.utilities, plan.loan_payment, plan.total_debt)
        else:
            profile_id = await conn.fetchval("""
                INSERT INTO financial_profiles (user_id, income_self, income_partner, rent, kindergarten, utilities, loan_payment, total_debt)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id
            """, user_id, plan.income_self, plan.income_partner, plan.rent, plan.kindergarten, plan.utilities, plan.loan_payment, plan.total_debt)

        # Calculate
        input_data = FinancialInput(
            mode=mode,
            income_self=plan.income_self,
            income_partner=plan.income_partner,
            rent=plan.rent,
            kindergarten=plan.kindergarten,
            utilities=plan.utilities,
            loan_payment=plan.loan_payment,
            total_debt=plan.total_debt
        )
        engine = FinancialEngine(input_data)
        result = engine.calculate()
        
        # Save Calculation History
        try:
            await conn.execute("""
                INSERT INTO calculations (
                    user_id, profile_id, mode, 
                    total_income, mandatory_living, mandatory_debt, free_cash, 
                    exit_months, exit_date
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """, user_id, profile_id, result['mode'], 
               result['total_income'], result.get('mandatory_living',0), result.get('mandatory_debt',0), result['free_cash'], 
               result.get('exit_months'), result.get('exit_date'))
        except Exception as e:
            logger.error(f"Failed to save calculation history: {e}")
            # Continue without saving history

        return result
