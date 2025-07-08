
import asyncio
import json
from fastapi import APIRouter, Request, Query, Depends
from sse_starlette.sse import EventSourceResponse, ServerSentEvent
from typing import List, Dict, Any, Optional

from app.auth.dependencies import try_get_user_from_token, get_current_user
from app.auth.schemas import UserPublic
from app.redis_client import get_redis_client
from app.websocket.manager import BROADCAST_CHANNEL, EVENT_LOG_KEY
from app.utils.logging import logger

router = APIRouter(prefix="/events", tags=["Server-Sent Events"])

async def sse_event_generator(request: Request, token: Optional[str]):
    """
    Yields server-sent events for a user, handling authentication and connection lifecycle.
    """
    current_user = await try_get_user_from_token(token)
    if not current_user:
        logger.warning("SSE: Authentication failed for provided token.")
        yield ServerSentEvent(event="auth_error", data=json.dumps({"detail": "Authentication failed"}))
        return

    user_id_str = str(current_user.id)
    redis = await get_redis_client()
    pubsub = redis.pubsub(ignore_subscribe_messages=True)
    
    try:
        await pubsub.subscribe(BROADCAST_CHANNEL)
        logger.info(f"User {user_id_str} connected via SSE and subscribed to Redis.")
        yield ServerSentEvent(event="sse_connected", data=json.dumps({"status": "ok"}))
        
        while True:
            if await request.is_disconnected():
                break
            try:
                message = await asyncio.wait_for(pubsub.get_message(timeout=15), timeout=20)
                if message and message["type"] == "message":
                    message_data = json.loads(message["data"])
                    if user_id_str in message_data.get("target_user_ids", []):
                        payload = message_data.get("payload", {})
                        event_type = payload.get("event_type", "message")
                        yield ServerSentEvent(event=event_type, data=json.dumps(payload))
                else:
                    yield ServerSentEvent(event="ping", data="keep-alive")
            except asyncio.TimeoutError:
                 yield ServerSentEvent(event="ping", data="keep-alive")
    except asyncio.CancelledError:
        logger.info(f"SSE generator for user {user_id_str} was cancelled.")
    finally:
        logger.info(f"Closing SSE resources for user {user_id_str}.")
        if pubsub: await pubsub.close()

@router.get("/subscribe")
async def subscribe_to_events(request: Request, token: Optional[str] = Query(None)):
    """Subscribes a client to real-time events using Server-Sent Events (SSE)."""
    return EventSourceResponse(sse_event_generator(request, token))

@router.get("/sync", response_model=List[Dict[str, Any]])
async def sync_events(since: int = Query(0, description="The last sequence number the client has processed."), current_user: UserPublic = Depends(get_current_user)):
    """Retrieves all broadcasted events since a given sequence number to catch up a client."""
    redis = await get_redis_client()
    user_id_str = str(current_user.id)
    
    try:
        event_score_pairs = await redis.zrangebyscore(EVENT_LOG_KEY, f"({since}", "+inf", withscores=True)
        authorized_events = []
        for event_json, score in event_score_pairs:
            event_data = json.loads(event_json)
            if user_id_str in event_data.get('target_user_ids', []):
                payload_with_seq = {**event_data['payload'], 'sequence': int(score)}
                authorized_events.append(payload_with_seq)
        
        logger.info(f"Sync request for user {user_id_str} since sequence {since} returned {len(authorized_events)} events.")
        return authorized_events
    except Exception as e:
        logger.error(f"Error during event sync for user {user_id_str}: {e}", exc_info=True)
        return []
