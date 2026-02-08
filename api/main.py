"""
Halos Auth API - FastAPI Application
Mobile app authentication via Telegram
Full backend for transactions, debts, and user management
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routers import auth, transactions, debts, users

app = FastAPI(
    title="Halos API",
    description="Backend API for Halos mobile app - transactions, debts, user management",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(transactions.router, prefix="/api", tags=["Transactions"])
app.include_router(debts.router, prefix="/api", tags=["Debts"])
app.include_router(users.router, prefix="/api", tags=["Users"])


@app.get("/")
async def root():
    return {"message": "Halos API", "status": "running", "version": "2.0.0"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
