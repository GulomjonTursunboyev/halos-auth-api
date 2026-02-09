"""
Telegram Authentication Router
Handles mobile app login sessions via Telegram bot
Includes Telegram Mini App (WebApp) authentication
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from urllib.parse import parse_qs, unquote
import secrets
import jwt
import hmac
import hashlib
import json
import os

router = APIRouter()

# In-memory session storage (use Redis in production)
telegram_sessions = {}

# JWT settings
JWT_SECRET = os.getenv("JWT_SECRET", "halos-super-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 30  # 30 days

# Telegram Bot Token for WebApp validation
BOT_TOKEN = os.getenv("BOT_TOKEN", "")


class TelegramSessionCreate(BaseModel):
    """Request to create a new Telegram login session"""
    device_info: Optional[str] = None


class TelegramSessionResponse(BaseModel):
    """Response with session info for deep link"""
    session_id: str
    deep_link: str
    expires_at: datetime


class TelegramSessionConfirm(BaseModel):
    """Request to confirm a Telegram session"""
    telegram_id: int
    telegram_username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class TokenResponse(BaseModel):
    """JWT token response"""
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: dict


class SessionStatus(BaseModel):
    """Session status response"""
    status: str  # pending, confirmed, expired, cancelled
    user: Optional[dict] = None
    access_token: Optional[str] = None


class TelegramWebAppRequest(BaseModel):
    """Telegram Mini App (WebApp) authentication request"""
    init_data: str


def generate_refresh_token(user_data: dict) -> str:
    """Generate refresh token for user"""
    payload = {
        "sub": str(user_data["telegram_id"]),
        "telegram_id": user_data["telegram_id"],
        "type": "refresh",
        "exp": datetime.utcnow() + timedelta(days=90),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def generate_jwt_token(user_data: dict) -> str:
    """Generate JWT token for authenticated user"""
    payload = {
        "sub": str(user_data["telegram_id"]),
        "telegram_id": user_data["telegram_id"],
        "username": user_data.get("telegram_username"),
        "first_name": user_data.get("first_name"),
        "last_name": user_data.get("last_name"),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def validate_telegram_webapp_data(init_data: str) -> Optional[dict]:
    """
    Validate Telegram WebApp initData using HMAC-SHA256.
    Returns parsed data if valid, None otherwise.
    
    See: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not BOT_TOKEN:
        # If no bot token configured, skip validation (development mode)
        try:
            parsed = parse_qs(init_data)
            if 'user' in parsed:
                return json.loads(unquote(parsed['user'][0]))
            return None
        except:
            return None
    
    try:
        # Parse the init_data string
        parsed = parse_qs(init_data)
        
        # Get the hash from the data
        if 'hash' not in parsed:
            return None
        
        received_hash = parsed['hash'][0]
        
        # Create data-check-string (all key=value pairs except hash, sorted alphabetically)
        data_pairs = []
        for key, value in parsed.items():
            if key != 'hash':
                data_pairs.append(f"{key}={value[0]}")
        
        data_pairs.sort()
        data_check_string = '\n'.join(data_pairs)
        
        # Create secret key: HMAC-SHA256(bot_token, "WebAppData")
        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()
        
        # Calculate hash: HMAC-SHA256(secret_key, data_check_string)
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Compare hashes
        if not hmac.compare_digest(calculated_hash, received_hash):
            return None
        
        # Check auth_date (data should not be older than 24 hours)
        if 'auth_date' in parsed:
            auth_date = int(parsed['auth_date'][0])
            if datetime.utcnow().timestamp() - auth_date > 86400:  # 24 hours
                return None
        
        # Parse and return user data
        if 'user' in parsed:
            return json.loads(unquote(parsed['user'][0]))
        
        return None
        
    except Exception as e:
        print(f"Error validating WebApp data: {e}")
        return None


@router.post("/telegram/session", response_model=TelegramSessionResponse)
async def create_telegram_session(request: TelegramSessionCreate):
    """
    Create a new Telegram login session.
    Returns a session ID and deep link for the mobile app.
    """
    session_id = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=5)
    
    # Store session
    telegram_sessions[session_id] = {
        "status": "pending",
        "created_at": datetime.utcnow(),
        "expires_at": expires_at,
        "device_info": request.device_info,
        "user": None
    }
    
    # Bot username from environment or default
    bot_username = os.getenv("BOT_USERNAME", "HalosRobot")
    deep_link = f"https://t.me/{bot_username}?start=login_{session_id}"
    
    return TelegramSessionResponse(
        session_id=session_id,
        deep_link=deep_link,
        expires_at=expires_at
    )


@router.get("/telegram/session/{session_id}", response_model=SessionStatus)
async def get_session_status(session_id: str):
    """
    Check the status of a Telegram login session.
    Mobile app polls this endpoint to check if user confirmed login.
    """
    session = telegram_sessions.get(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Check if expired
    if datetime.utcnow() > session["expires_at"]:
        session["status"] = "expired"
        return SessionStatus(status="expired")
    
    if session["status"] == "confirmed" and session["user"]:
        # Generate JWT token
        token = generate_jwt_token(session["user"])
        return SessionStatus(
            status="confirmed",
            user=session["user"],
            access_token=token
        )
    
    return SessionStatus(status=session["status"])


@router.post("/telegram/session/{session_id}/confirm", response_model=TokenResponse)
async def confirm_telegram_session(session_id: str, request: TelegramSessionConfirm):
    """
    Confirm a Telegram login session (called by Telegram bot).
    This endpoint is called when user taps 'Confirm' button in Telegram.
    """
    session = telegram_sessions.get(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if datetime.utcnow() > session["expires_at"]:
        session["status"] = "expired"
        raise HTTPException(status_code=410, detail="Session expired")
    
    if session["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Session already {session['status']}")
    
    # Update session with user data
    user_data = {
        "telegram_id": request.telegram_id,
        "telegram_username": request.telegram_username,
        "first_name": request.first_name,
        "last_name": request.last_name
    }
    
    session["status"] = "confirmed"
    session["user"] = user_data
    session["confirmed_at"] = datetime.utcnow()
    
    # Generate JWT token
    access_token = generate_jwt_token(user_data)
    refresh_token = generate_refresh_token(user_data)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=user_data
    )


@router.post("/telegram/session/{session_id}/cancel")
async def cancel_telegram_session(session_id: str):
    """
    Cancel a Telegram login session.
    Called when user taps 'Cancel' button in Telegram.
    """
    session = telegram_sessions.get(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session["status"] = "cancelled"
    
    return {"status": "cancelled", "message": "Session cancelled"}


@router.post("/verify-token")
async def verify_token(token: str):
    """
    Verify a JWT token and return user info.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return {
            "valid": True,
            "user": {
                "telegram_id": payload.get("telegram_id"),
                "username": payload.get("username"),
                "first_name": payload.get("first_name"),
                "last_name": payload.get("last_name")
            }
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


@router.post("/telegram/webapp", response_model=TokenResponse)
async def authenticate_telegram_webapp(request: TelegramWebAppRequest):
    """
    Authenticate user from Telegram Mini App (WebApp).
    
    This endpoint validates the initData received from Telegram WebApp
    and returns a JWT token for the authenticated user.
    
    The initData is validated using HMAC-SHA256 with the bot token
    as per Telegram's WebApp authentication flow.
    
    See: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    # Validate initData
    user_data = validate_telegram_webapp_data(request.init_data)
    
    if not user_data:
        raise HTTPException(
            status_code=401, 
            detail="Invalid or expired Telegram WebApp data"
        )
    
    # Extract user info from Telegram WebApp data
    telegram_user = {
        "telegram_id": user_data.get("id"),
        "telegram_username": user_data.get("username"),
        "first_name": user_data.get("first_name"),
        "last_name": user_data.get("last_name"),
        "language_code": user_data.get("language_code"),
        "is_premium": user_data.get("is_premium", False)
    }
    
    # Generate tokens
    access_token = generate_jwt_token(telegram_user)
    refresh_token = generate_refresh_token(telegram_user)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=telegram_user
    )
