
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncio
import redis.asyncio as redis
from prometheus_fastapi_instrumentator import Instrumentator

from app.middleware.logging import LoggingMiddleware
from app.websocket import manager as ws_manager
from app.utils.logging import logger
from app.redis_client import redis_manager
from app.config import settings

from app.auth.routes import auth_router, user_router
from app.chat.routes import router as chat_router
from app.routers.uploads import router as uploads_router
from app.routers.ws import router as ws_router
from app.routers.ai import router as ai_router
from app.routers.stickers import router as stickers_router
from app.notifications.routes import router as notifications_router
from app.routers.partners import router as partners_router
from app.routers.events import router as events_router
from app.routers.analytics import router as analytics_router
from app.routers.webhooks import router as webhooks_router
from app.routers.media import router as media_router
from app.routers.actions import router as actions_router

app = FastAPI(
    title="Kuchlu API",
    description="Backend API for Kuchlu",
    version="1.0.0",
)

Instrumentator(excluded_handlers=["/metrics", "/health"]).instrument(app).expose(app)

# Conditionally configure CORS based on the environment
if settings.ENVIRONMENT == "development":
    logger.info("Running in development mode, allowing all origins for CORS.")
    cors_config = {
        "allow_origins": ["*"],
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }
else:
    cors_config = {
        "allow_origins": [
            "http://localhost:3000",
            "http://localhost:9002",
            "capacitor://localhost",
            "http://localhost",
            "https://kuchlu.vercel.app",
            "https://kuchlu.vercel.app",
        ],
        "allow_origin_regex": r"https://.*\.vercel\.app",
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(ws_manager.listen_for_broadcasts())
    logger.info("FastAPI application startup complete. Redis listener running.")

app.add_middleware(
    CORSMiddleware,
    **cors_config
)

app.add_middleware(LoggingMiddleware)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    logger.error(f"Unhandled error: {exc}\nTraceback: {traceback.format_exc()}")
    return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred.", "error_type": type(exc).__name__})

@app.get("/health", tags=["System"])
async def health_check():
    redis_healthy = False
    try:
        redis_client = await redis_manager.get_client()
        await redis_client.ping()
        redis_healthy = True
    except Exception as e:
        logger.error(f"Health check failed: Redis connection error - {e}")
    
    response_content = {
        "status": "healthy" if redis_healthy else "unhealthy",
        "service": "kuchlu-api", "version": app.version,
        "dependencies": {"redis": "healthy" if redis_healthy else "unhealthy"}
    }
    
    status_code = status.HTTP_200_OK if redis_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=response_content)

app.include_router(auth_router)
app.include_router(user_router)
app.include_router(chat_router)
app.include_router(uploads_router)
app.include_router(ws_router)
app.include_router(ai_router)
app.include_router(stickers_router)
app.include_router(notifications_router)
app.include_router(partners_router)
app.include_router(events_router)
app.include_router(analytics_router)
app.include_router(webhooks_router)
app.include_router(media_router)
app.include_router(actions_router)
