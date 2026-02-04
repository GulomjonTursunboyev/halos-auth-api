# Halos Auth API

Telegram orqali mobil ilova autentifikatsiyasi uchun API.

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/telegram/session` | Yangi login session yaratish |
| GET | `/api/auth/telegram/session/{id}` | Session statusini tekshirish |
| POST | `/api/auth/telegram/session/{id}/confirm` | Sessionni tasdiqlash (bot orqali) |
| POST | `/api/auth/telegram/session/{id}/cancel` | Sessionni bekor qilish |
| POST | `/api/auth/verify-token` | JWT tokenni tekshirish |

## Auth Flow

```
Mobile App                    Auth API                    Telegram Bot
    |                            |                            |
    |-- POST /telegram/session ->|                            |
    |<-- session_id, deep_link --|                            |
    |                            |                            |
    |-- Open Telegram deep_link ----------------------->      |
    |                            |                            |
    |                            |<-- POST /confirm (user) ---|
    |                            |                            |
    |-- GET /session/{id} ------>|                            |
    |<-- status: confirmed, JWT -|                            |
```

## Deploy to Railway

1. Railway da yangi proyekt yarating
2. GitHub repo ni ulang
3. Environment variables qo'shing:
   - `JWT_SECRET` - JWT uchun secret key
   - `BOT_USERNAME` - Telegram bot username

## Local Development

```bash
pip install -r requirements.txt
uvicorn api.main:app --reload
```

API docs: http://localhost:8000/docs
