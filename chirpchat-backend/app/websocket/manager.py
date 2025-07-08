
import asyncio
import json
from uuid import UUID
from typing import Dict, List, Any, Optional
from fastapi import WebSocket
from starlette.websockets import WebSocketState
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.utils.logging import logger
from app.database import db_manager
from app.redis_client import get_redis_client
from app.chat.schemas import MessageStatusEnum, MessageInDB

USER_CONNECTIONS_KEY = "user_connections"
BROADCAST_CHANNEL = "chirpchat:broadcast"
PROCESSED_MESSAGES_PREFIX = "processed_messages:"
EVENT_SEQUENCE_KEY = "global_event_sequence"
EVENT_LOG_KEY = "event_log"
PROCESSED_MESSAGE_TTL_SECONDS = 300
EVENT_LOG_TTL_SECONDS = 60 * 60 * 24
TRIM_EVENT_LOG_AFTER_N_EVENTS = 5000
SERVER_ID = settings.SERVER_INSTANCE_ID
THROTTLE_LAST_SEEN_UPDATE_SECONDS = 120

active_local_connections: Dict[UUID, WebSocket] = {}
user_last_activity_update_db: Dict[UUID, datetime] = {}

async def connect(websocket: WebSocket, user_id: UUID):
    await websocket.accept()
    redis = await get_redis_client()
    active_local_connections[user_id] = websocket
    
    await redis.hset(USER_CONNECTIONS_KEY, str(user_id), SERVER_ID)
    db_manager.get_table("users").update({"is_online": True, "last_seen": "now()"}).eq("id", str(user_id)).execute()
    
    user_mood_resp = db_manager.get_table("users").select("mood").eq("id", str(user_id)).maybe_single().execute()
    mood = user_mood_resp.data.get('mood', 'Neutral') if user_mood_resp.data else 'Neutral'
    await broadcast_presence_update(user_id, is_online=True, mood=mood)
    logger.info(f"User {user_id} connected to instance {SERVER_ID}.")

async def disconnect(user_id: UUID):
    if user_id in active_local_connections:
        del active_local_connections[user_id]
    
    redis = await get_redis_client()
    await redis.hdel(USER_CONNECTIONS_KEY, str(user_id))
    db_manager.get_table("users").update({"is_online": False, "last_seen": "now()"}).eq("id", str(user_id)).execute()
    
    user_mood_resp = db_manager.get_table("users").select("mood").eq("id", str(user_id)).maybe_single().execute()
    mood = user_mood_resp.data.get('mood', 'Neutral') if user_mood_resp.data else 'Neutral'
    await broadcast_presence_update(user_id, is_online=False, mood=mood)
    logger.info(f"User {user_id} disconnected from instance {SERVER_ID}.")

async def send_personal_message(websocket: WebSocket, payload: dict):
    try:
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.send_json(payload)
    except Exception as e:
        logger.error(f"Failed to send personal message: {e}", exc_info=True)

async def is_message_processed(client_temp_id: str) -> bool:
    if not client_temp_id: return False
    redis = await get_redis_client()
    return bool(await redis.exists(f"{PROCESSED_MESSAGES_PREFIX}{client_temp_id}"))

async def mark_message_as_processed(client_temp_id: str):
    if not client_temp_id: return
    redis = await get_redis_client()
    await redis.set(f"{PROCESSED_MESSAGES_PREFIX}{client_temp_id}", "1", ex=PROCESSED_MESSAGE_TTL_SECONDS)

async def send_ack(websocket: WebSocket, client_temp_id: str, server_id: Optional[str] = None):
    await send_personal_message(websocket, {"event_type": "message_ack", "client_temp_id": client_temp_id, "server_assigned_id": server_id or client_temp_id, "status": MessageStatusEnum.SENT.value, "timestamp": datetime.now(timezone.utc).isoformat()})

async def broadcast_to_users(user_ids: List[UUID], payload: Dict[str, Any]):
    redis = await get_redis_client()
    sequence_num = await redis.incr(EVENT_SEQUENCE_KEY)
    payload_with_seq = {**payload, "sequence": sequence_num}
    
    message_to_publish = {"target_user_ids": [str(uid) for uid in user_ids], "payload": payload_with_seq}
    message_json = json.dumps(message_to_publish)

    async with redis.pipeline(transaction=True) as pipe:
        pipe.zadd(EVENT_LOG_KEY, {message_json: sequence_num})
        pipe.zremrangebyscore(EVENT_LOG_KEY, "-inf", f"({sequence_num - TRIM_EVENT_LOG_AFTER_N_EVENTS}")
        await pipe.execute()
    await redis.expire(EVENT_LOG_KEY, EVENT_LOG_TTL_SECONDS)
    await redis.publish(BROADCAST_CHANNEL, message_json)

async def _get_chat_participants(chat_id: str) -> List[UUID]:
    try:
        resp = db_manager.get_table("chat_participants").select("user_id").eq("chat_id", chat_id).execute()
        return [UUID(row["user_id"]) for row in resp.data]
    except Exception as e:
        logger.error(f"DB error fetching participants for chat {chat_id}: {e}", exc_info=True)
        return []

async def broadcast_message_deletion(chat_id: str, message_id: str):
    participant_ids = await _get_chat_participants(chat_id)
    payload = {"event_type": "message_deleted", "chat_id": chat_id, "message_id": message_id}
    if participant_ids: await broadcast_to_users(participant_ids, payload)

async def broadcast_chat_history_cleared(chat_id: str):
    """Broadcasts that a chat's history has been cleared."""
    participant_ids = await _get_chat_participants(chat_id)
    payload = {"event_type": "chat_history_cleared", "chat_id": chat_id}
    if participant_ids:
        await broadcast_to_users(participant_ids, payload)

async def broadcast_chat_message(chat_id: str, message_data: MessageInDB):
    participant_ids = await _get_chat_participants(chat_id)
    payload = {"event_type": "new_message", "message": message_data.model_dump(mode='json'), "chat_id": chat_id}
    if participant_ids: await broadcast_to_users(participant_ids, payload)

async def broadcast_media_processed(chat_id: str, message_data: MessageInDB):
    """Broadcasts that a media message has been processed and is ready for display."""
    participant_ids = await _get_chat_participants(chat_id)
    payload = {"event_type": "media_processed", "message": message_data.model_dump(mode='json')}
    if participant_ids:
        await broadcast_to_users(participant_ids, payload)

async def broadcast_reaction_update(chat_id: str, message_data: MessageInDB):
    participant_ids = await _get_chat_participants(chat_id)
    dumped_message_data = message_data.model_dump(mode='json')
    payload = {"event_type": "message_reaction_update", "message_id": dumped_message_data["id"], "chat_id": chat_id, "reactions": dumped_message_data.get("reactions", {})}
    if participant_ids: await broadcast_to_users(participant_ids, payload)

async def broadcast_typing_indicator(chat_id: str, typing_user_id: UUID, is_typing: bool):
    recipients = [pid for pid in await _get_chat_participants(chat_id) if pid != typing_user_id]
    payload = {"event_type": "typing_indicator", "chat_id": chat_id, "user_id": str(typing_user_id), "is_typing": is_typing}
    if recipients: await broadcast_to_users(recipients, payload)

async def broadcast_presence_update(user_id: UUID, is_online: bool, mood: str):
    user_chats_resp = db_manager.get_table("chat_participants").select("chat_id").eq("user_id", str(user_id)).execute()
    if not user_chats_resp.data: return
    chat_ids = [row["chat_id"] for row in user_chats_resp.data]
    recipients_resp = db_manager.get_table("chat_participants").select("user_id").in_("chat_id", chat_ids).neq("user_id", str(user_id)).execute()
    if not recipients_resp.data: return
    unique_recipients = list({UUID(row["user_id"]) for row in recipients_resp.data})
    payload = {"event_type": "user_presence_update", "user_id": str(user_id), "is_online": is_online, "last_seen": datetime.now(timezone.utc).isoformat(), "mood": mood}
    if unique_recipients: await broadcast_to_users(unique_recipients, payload)

async def broadcast_user_profile_update(user_id: UUID, updated_data: dict):
    user_chats_resp = db_manager.get_table("chat_participants").select("chat_id").eq("user_id", str(user_id)).execute()
    if not user_chats_resp.data: return
    chat_ids = [row["chat_id"] for row in user_chats_resp.data]
    recipients_resp = db_manager.get_table("chat_participants").select("user_id").in_("chat_id", chat_ids).neq("user_id", str(user_id)).execute()
    if not recipients_resp.data: return
    unique_recipients = list({UUID(row["user_id"]) for row in recipients_resp.data})
    payload = {"event_type": "user_profile_update", "user_id": str(user_id), **updated_data}
    if unique_recipients: await broadcast_to_users(unique_recipients, payload)

async def broadcast_chat_mode_update(chat_id: str, new_mode: str):
    participant_ids = await _get_chat_participants(chat_id)
    payload = {"event_type": "chat_mode_changed", "chat_id": chat_id, "mode": new_mode}
    if participant_ids: await broadcast_to_users(participant_ids, payload)

async def broadcast_message_status_update(chat_id: str, message_id: str, status: MessageStatusEnum, read_at: Optional[str] = None):
    participant_ids = await _get_chat_participants(chat_id)
    payload = {
        "event_type": "message_status_update",
        "chat_id": chat_id,
        "message_id": message_id,
        "status": status.value,
    }
    if read_at:
        payload["read_at"] = read_at
    if participant_ids:
        await broadcast_to_users(participant_ids, payload)

async def listen_for_broadcasts():
    logger.info(f"Instance {SERVER_ID} starting Redis Pub/Sub listener.")
    while True:
        try:
            pubsub = await get_redis_client()
            ps_client = pubsub.pubsub(ignore_subscribe_messages=True)
            await ps_client.subscribe(BROADCAST_CHANNEL)
            logger.info(f"Instance {SERVER_ID} subscribed to Redis channel '{BROADCAST_CHANNEL}'.")
            while True:
                message = await ps_client.get_message(ignore_subscribe_messages=True, timeout=None)
                if message and message["type"] == "message":
                    message_data = json.loads(message["data"])
                    target_user_ids = [UUID(uid) for uid in message_data["target_user_ids"]]
                    payload = message_data["payload"]
                    locally_connected_targets = [uid for uid in target_user_ids if uid in active_local_connections]
                    tasks = [send_personal_message(active_local_connections[user_id], payload) for user_id in locally_connected_targets]
                    if tasks: await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Error in Redis Pub/Sub listener on instance {SERVER_ID}: {e}", exc_info=True)
            await asyncio.sleep(5) # Wait before trying to reconnect

async def update_user_last_seen_throttled(user_id: UUID):
    now = datetime.now(timezone.utc)
    last_update = user_last_activity_update_db.get(user_id)
    if not last_update or (now - last_update) > timedelta(seconds=THROTTLE_LAST_SEEN_UPDATE_SECONDS):
        db_manager.get_table("users").update({"last_seen": "now()"}).eq("id", str(user_id)).execute()
        user_last_activity_update_db[user_id] = now

async def is_user_in_chat(user_id: UUID, chat_id: UUID) -> bool:
    resp = db_manager.get_table("chat_participants").select("user_id").eq("chat_id", str(chat_id)).eq("user_id", str(user_id)).maybe_single().execute()
    return bool(resp.data)

