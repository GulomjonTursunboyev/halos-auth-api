"""
Database connection for Halos Auth API
Uses PostgreSQL (same database as Telegram bot for data sync)
"""

import asyncpg
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Global pool
_pool: Optional[asyncpg.Pool] = None

DATABASE_URL = os.getenv("DATABASE_URL", "")


async def init_db():
    """Initialize database connection pool"""
    global _pool
    
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set, using in-memory storage")
        return
    
    db_url = DATABASE_URL
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    
    try:
        _pool = await asyncpg.create_pool(
            dsn=db_url,
            min_size=2,
            max_size=10,
            command_timeout=30,
            ssl='require',
            max_inactive_connection_lifetime=60
        )
        logger.info("Database pool created successfully")
    except Exception as e:
        logger.error(f"Failed to create database pool: {e}")


async def close_db():
    """Close database connection pool"""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")


async def get_pool() -> Optional[asyncpg.Pool]:
    """Get database pool"""
    return _pool


def is_db_available() -> bool:
    """Check if database is available"""
    return _pool is not None
