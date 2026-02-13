"""
Halos Auth API - FastAPI Application
Mobile app authentication via Telegram
Full backend for transactions, debts, and user management
Synced with Telegram bot database
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from api.routers import auth, transactions, debts, users, plans
from api.database import init_db, close_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database
    await init_db()
    yield
    # Shutdown: Close database
    await close_db()


app = FastAPI(
    title="Halos API",
    description="Backend API for Halos mobile app - transactions, debts, user management. Synced with Telegram bot.",
    version="2.2.0",
    lifespan=lifespan
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
app.include_router(plans.router, prefix="/api", tags=["Plans"])


@app.get("/")
async def root():
    return {"message": "Halos API", "status": "running", "version": "2.2.0", "sync": "telegram_bot"}


@app.get("/health")
async def health_check():
    from api.database import is_db_available
    return {
        "status": "healthy",
        "database": "connected" if is_db_available() else "in-memory"
    }