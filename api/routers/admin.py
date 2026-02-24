"""
Admin Router - Halos Auth API
Admin-only endpoints for user management and statistics
Requires admin_telegram_id in ADMIN_IDS environment variable
"""

import os
import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from api.database import get_pool

logger = logging.getLogger(__name__)
router = APIRouter()

# Admin IDs from environment (same as bot ADMIN_IDS)
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]


def verify_admin(admin_telegram_id: int):
    """Raise 403 if not admin"""
    if not ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Admin access not configured")
    if admin_telegram_id not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Admin access denied")


class SetProRequest(BaseModel):
    admin_telegram_id: int
    is_pro: bool


@router.get("/admin/stats")
async def get_stats(admin_telegram_id: int = Query(...)):
    """Get system statistics — admin only"""
    verify_admin(admin_telegram_id)
    pool = await get_pool()

    if not pool:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        async with pool.acquire() as conn:
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
            pro_users = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE is_premium = true"
            ) or 0

            active_today = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE last_active >= NOW() - INTERVAL '1 day'"
            ) or 0

            active_week = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE last_active >= NOW() - INTERVAL '7 days'"
            ) or 0

            total_transactions = 0
            try:
                total_transactions = await conn.fetchval("SELECT COUNT(*) FROM transactions") or 0
            except Exception:
                pass

        return {
            "total_users": total_users,
            "pro_users": pro_users,
            "active_today": active_today,
            "active_week": active_week,
            "total_transactions": total_transactions,
        }
    except Exception as e:
        logger.error(f"Admin stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/users")
async def list_users(
    admin_telegram_id: int = Query(...),
    limit: int = Query(default=500, le=1000),
    offset: int = Query(default=0),
):
    """List all users — admin only"""
    verify_admin(admin_telegram_id)
    pool = await get_pool()

    if not pool:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT
                    telegram_id,
                    first_name,
                    last_name,
                    username,
                    language,
                    is_premium,
                    created_at,
                    last_active
                FROM users
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2""",
                limit, offset
            )

        users = []
        for row in rows:
            users.append({
                "telegram_id": row["telegram_id"],
                "first_name": row["first_name"] or "",
                "last_name": row["last_name"] or "",
                "username": row["username"] or "",
                "language_code": row["language"] or "uz",
                "is_premium": bool(row["is_premium"]),
                "created_at": str(row["created_at"]) if row["created_at"] else None,
                "last_active": str(row["last_active"]) if row["last_active"] else None,
            })

        return users
    except Exception as e:
        logger.error(f"Admin list_users error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/admin/users/{target_telegram_id}/set-pro")
async def set_user_pro(target_telegram_id: int, body: SetProRequest):
    """Grant or revoke PRO access for a user — admin only"""
    verify_admin(body.admin_telegram_id)
    pool = await get_pool()

    if not pool:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT id FROM users WHERE telegram_id = $1", target_telegram_id
            )
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            await conn.execute(
                "UPDATE users SET is_premium = $1, updated_at = NOW() WHERE telegram_id = $2",
                body.is_pro, target_telegram_id
            )

        logger.info(
            f"Admin {body.admin_telegram_id} set PRO={body.is_pro} for user {target_telegram_id}"
        )
        return {"success": True, "telegram_id": target_telegram_id, "is_pro": body.is_pro}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin set_pro error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
