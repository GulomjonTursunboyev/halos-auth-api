"""
Halos Auth API - FastAPI Application
Mobile app authentication via Telegram
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routers import auth

app = FastAPI(
    title="Halos Auth API",
    description="Authentication API for Halos mobile app via Telegram",
    version="1.0.0"
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


@app.get("/")
async def root():
    return {"message": "Halos Auth API", "status": "running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
