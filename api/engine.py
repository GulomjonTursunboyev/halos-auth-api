"""
HALOS Financial Engine
Core calculation logic for debt freedom and wealth building
Adapted for Halos Auth API (Standalone)
"""
import math
from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import Dict, Any, Optional
from dataclasses import dataclass

# Constants
DEBT_MODE_SAVINGS_RATE = 0.10      # 10%
DEBT_MODE_ACCELERATED_RATE = 0.20  # 20%
DEBT_MODE_LIVING_RATE = 0.70       # 70%

WEALTH_MODE_INVEST_RATE = 0.30     # 30%
WEALTH_MODE_SAVINGS_RATE = 0.20    # 20%
WEALTH_MODE_LIVING_RATE = 0.50     # 50%


@dataclass
class FinancialInput:
    """Input data for financial calculations"""
    mode: str = "solo"
    income_self: float = 0
    income_partner: float = 0
    rent: float = 0
    kindergarten: float = 0
    utilities: float = 0
    loan_payment: float = 0
    total_debt: float = 0


class FinancialEngine:
    """
    HALOS Financial Calculation Engine
    
    Handles all financial calculations for:
    - Debt mode: Users with loans
    - Wealth mode: Users without loans
    """
    
    def __init__(self, input_data: FinancialInput):
        self.input = input_data
        
        # Calculate totals
        self.total_income = float(input_data.income_self) + float(input_data.income_partner)
        self.mandatory_living = (
            float(input_data.rent) + 
            float(input_data.kindergarten) + 
            float(input_data.utilities)
        )
        self.mandatory_debt = float(input_data.loan_payment)
        
        # Calculate free cash (Income - Mandatory Expenses - Minimum Debt Payment)
        self.free_cash = (
            self.total_income - 
            self.mandatory_debt - 
            self.mandatory_living
        )
    
    def calculate(self) -> Dict[str, Any]:
        """
        Main calculation method
        Returns appropriate result based on financial situation
        """
        # Check if expenses exceed income
        if self.free_cash < 0:
            return self._calculate_negative_cash()
        
        # Check if user has debt
        # We check if total_debt > 0 AND there is a monthly payment
        if float(self.input.total_debt) > 0:
            return self._calculate_debt_mode()
        else:
            return self._calculate_wealth_mode()
    
    def _calculate_debt_mode(self) -> Dict[str, Any]:
        """
        Calculate debt freedom plan
        
        FREE: Simple debt payoff (just monthly payments)
        PRO: Accelerated payoff with 70-20-10 method + savings
        """
        # === FREE VERSION: Simple debt payoff calculation ===
        # Total debt / Monthly payment = Exit months
        if self.mandatory_debt > 0:
            simple_exit_months = math.ceil(float(self.input.total_debt) / self.mandatory_debt)
        else:
            # If no monthly payment but has debt, assumed infinite or lump sum needed
            simple_exit_months = 0 if self.input.total_debt <= 0 else 999
            
        # Current date + exit months = Exit date
        simple_exit_date = datetime.now() + relativedelta(months=simple_exit_months)
        
        # === PRO VERSION: Accelerated 70-20-10 method ===
        # Monthly allocations from free cash
        # Note: Free cash is what's left AFTER mandatory living and MINIMUM debt payment
        
        monthly_savings = self.free_cash * DEBT_MODE_SAVINGS_RATE  # 10%
        accelerated_debt_payment = self.free_cash * DEBT_MODE_ACCELERATED_RATE  # 20% extra to debt
        monthly_living_extra = self.free_cash * DEBT_MODE_LIVING_RATE  # 70% extra to living (lifestyle)
        
        # Total monthly debt payment (mandatory minimum + accelerated portion)
        total_debt_payment = self.mandatory_debt + accelerated_debt_payment
        
        # Calculate PRO exit timeline (faster!)
        if total_debt_payment > 0:
            pro_exit_months = math.ceil(float(self.input.total_debt) / total_debt_payment)
        else:
            pro_exit_months = 0
        
        # Calculate PRO exit date
        pro_exit_date = datetime.now() + relativedelta(months=pro_exit_months)
        
        # Calculate months saved with PRO method
        months_saved = max(0, simple_exit_months - pro_exit_months)
        
        # Calculate savings projections
        savings_12_months = monthly_savings * 12
        savings_at_exit = monthly_savings * pro_exit_months
        
        return {
            "mode": "debt",
            "total_income": self.total_income,
            "mandatory_living": self.mandatory_living,
            "mandatory_debt": self.mandatory_debt,
            "free_cash": self.free_cash,
            
            # Key metrics
            "monthly_savings": monthly_savings,
            "monthly_debt_payment": total_debt_payment, # Total payment (min + extra)
            "accelerated_debt_extra": accelerated_debt_payment, # Just the extra part
            "monthly_living_extra": monthly_living_extra,
            "monthly_invest": 0,
            
            # Simple (FREE) calculations
            "simple_exit_months": simple_exit_months,
            "simple_exit_date": simple_exit_date.strftime("%Y-%m"),
            
            # PRO calculations
            "exit_months": pro_exit_months,
            "exit_date": pro_exit_date.strftime("%Y-%m"),
            "months_saved": months_saved,
            "savings_12_months": savings_12_months,
            "savings_at_exit": savings_at_exit,
        }
    
    def _calculate_wealth_mode(self) -> Dict[str, Any]:
        """
        Calculate wealth building plan
        
        Formula:
        - Invest = FreeCash × 30%
        - Savings = FreeCash × 20%
        - Living = FreeCash × 50%
        """
        # Monthly allocations
        monthly_invest = self.free_cash * WEALTH_MODE_INVEST_RATE
        monthly_savings = self.free_cash * WEALTH_MODE_SAVINGS_RATE
        monthly_living_extra = self.free_cash * WEALTH_MODE_LIVING_RATE
        
        # 12-month projections
        invest_12_months = monthly_invest * 12
        savings_12_months = monthly_savings * 12
        total_12_months = invest_12_months + savings_12_months
        
        return {
            "mode": "wealth",
            "total_income": self.total_income,
            "mandatory_living": self.mandatory_living,
            "mandatory_debt": 0,
            "free_cash": self.free_cash,
            
            # Allocations
            "monthly_invest": monthly_invest,
            "monthly_savings": monthly_savings,
            "monthly_living_extra": monthly_living_extra,
            "monthly_debt_payment": 0,
            
            # Projections
            "exit_months": 0,
            "exit_date": None,
            "invest_12_months": invest_12_months,
            "savings_12_months": savings_12_months,
            "total_12_months": total_12_months,
            "savings_at_exit": 0,
        }
    
    def _calculate_negative_cash(self) -> Dict[str, Any]:
        """Handle case where expenses exceed income"""
        total_expenses = self.mandatory_living + self.mandatory_debt
        
        return {
            "mode": "negative",
            "total_income": self.total_income,
            "total_expenses": total_expenses,
            "mandatory_living": self.mandatory_living,
            "mandatory_debt": self.mandatory_debt,
            "free_cash": self.free_cash,  # Will be negative
            "difference": self.free_cash,
            
            # Zero out recommendations
            "monthly_savings": 0,
            "monthly_debt_payment": self.mandatory_debt, # Only pay minimum if possible (in reality user is short)
            "monthly_invest": 0,
            "exit_months": 0,
            "exit_date": None
        }
