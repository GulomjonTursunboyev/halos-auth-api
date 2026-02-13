from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
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
    """Get current financial plan and profile for a user"""
    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    async with pool.acquire() as conn:
        # Get user ID and mode
        # Uses 'telegram_id' to find 'id' (user_id) in users table
        user = await conn.fetchrow("SELECT id, mode FROM users WHERE telegram_id = $1", telegram_id)
        if not user:
            # Return empty plan if user not found, instead of 404, to allow frontend to handle "no plan" state gracefully
            return {
                "profile": None,
                "result": None,
                "user_found": False
            }
        
        user_id = user['id']
        mode = user.get('mode', 'solo')
        
        # Get Financial Profile
        profile = await conn.fetchrow("SELECT * FROM financial_profiles WHERE user_id = $1", user_id)
        
        result = None
        if profile:
            try:
                # Map DB profile to engine input
                input_data = FinancialInput(
                    mode=mode,
                    income_self=float(profile['income_self'] or 0),
                    income_partner=float(profile['income_partner'] or 0),
                    rent=float(profile['rent'] or 0),
                    kindergarten=float(profile['kindergarten'] or 0),
                    utilities=float(profile['utilities'] or 0),
                    loan_payment=float(profile['loan_payment'] or 0),
                    total_debt=float(profile['total_debt'] or 0)
                )
                
                # Run calculation
                engine = FinancialEngine(input_data)
                result = engine.calculate()
                
            except Exception as e:
                logger.error(f"Calculation error for user {telegram_id}: {e}")
                # Don't fail the request, just return no result
        
        # Convert record to dict safely
        profile_dict = dict(profile) if profile else None
        
        # Format dates if present in result
        if result:
            # Ensure dates are strings for JSON response
            for key, val in result.items():
                if hasattr(val, 'isoformat'):
                    result[key] = val.isoformat()
        
        return {
            "profile": profile_dict,
            "result": result,
            "user_found": True
        }

@router.post("/plan/calculate")
async def calculate_plan(telegram_id: int, plan: PlanInput):
    """Calculate and save a new financial plan"""
    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    async with pool.acquire() as conn:
        # Get user
        user = await conn.fetchrow("SELECT id, mode FROM users WHERE telegram_id = $1", telegram_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_id = user['id']
        mode = user.get('mode', 'solo')
        
        # Upsert Financial Profile
        # We use a transaction to ensure data integrity
        async with conn.transaction():
            existing = await conn.fetchval("SELECT id FROM financial_profiles WHERE user_id=$1", user_id)
            
            if existing:
                profile_id = await conn.fetchval("""
                    UPDATE financial_profiles 
                    SET income_self=$2, income_partner=$3, rent=$4, kindergarten=$5, 
                        utilities=$6, loan_payment=$7, total_debt=$8, updated_at=CURRENT_TIMESTAMP
                    WHERE user_id=$1 RETURNING id
                """, user_id, plan.income_self, plan.income_partner, plan.rent, 
                   plan.kindergarten, plan.utilities, plan.loan_payment, plan.total_debt)
            else:
                profile_id = await conn.fetchval("""
                    INSERT INTO financial_profiles (
                        user_id, income_self, income_partner, rent, kindergarten, 
                        utilities, loan_payment, total_debt
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id
                """, user_id, plan.income_self, plan.income_partner, plan.rent, 
                   plan.kindergarten, plan.utilities, plan.loan_payment, plan.total_debt)

            # Calculate Result
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
            
            # Save Calculation History (optional but good for analytics)
            try:
                # We need to adapt the keys to match what the 'calculations' table expects
                # based on app/database.py schema
                await conn.execute("""
                    INSERT INTO calculations (
                        user_id, profile_id, mode, 
                        total_income, mandatory_living, mandatory_debt, free_cash, 
                        monthly_savings, monthly_debt_payment, monthly_living, monthly_invest,
                        exit_months, exit_date, savings_12_months, savings_at_exit
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                """, 
                user_id, profile_id, result['mode'], 
                result['total_income'], result.get('mandatory_living',0), result.get('mandatory_debt',0), result['free_cash'],
                result.get('monthly_savings', 0), result.get('monthly_debt_payment', 0), 
                result.get('monthly_living_extra', 0) if 'monthly_living_extra' in result else result.get('monthly_living', 0),
                result.get('monthly_invest', 0),
                result.get('exit_months'), result.get('exit_date'),
                result.get('savings_12_months', 0), result.get('savings_at_exit', 0)
                )
            except Exception as e:
                logger.error(f"Failed to save calculation history: {e}")
                # Non-critical failure
    
        # Format dates for response
        for key, val in result.items():
            if hasattr(val, 'isoformat'):
                result[key] = val.isoformat()
        
        return result
