

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional, List, Any
from uuid import UUID
from datetime import datetime, timezone
import json
from pydantic import BaseModel

from app.chat.schemas import (
    ChatCreate, ChatResponse, ChatListResponse, MessageCreate, MessageInDB,
    MessageListResponse, ReactionToggle, ChatParticipant, MessageStatusEnum,
    MessageModeEnum
)
from app.auth.dependencies import get_current_active_user, get_current_user
from app.auth.schemas import UserPublic
from app.database import db_manager
from app.websocket import manager as ws_manager
from app.utils.logging import logger 
from app.notifications.service import notification_service
import uuid

router = APIRouter(prefix="/chats", tags=["Chats"])

def map_db_message_to_schema(message_data: dict) -> dict:
    """Centralized function to map raw DB message data to a schema-compatible dict."""
    if not message_data: return {}
    if message_data.get('media_type'): message_data['message_subtype'] = message_data['media_type']
    if message_data.get('media_url'):
        subtype = message_data.get('message_subtype')
        if subtype == 'image':
            message_data['image_url'] = message_data['media_url']
            if message_data.get('thumbnail_url'): message_data['image_thumbnail_url'] = message_data.get('thumbnail_url')
        elif subtype in ['clip', 'voice_message', 'audio']:
            message_data['clip_url'] = message_data['media_url']
            if message_data.get('thumbnail_url'): message_data['image_thumbnail_url'] = message_data.get('thumbnail_url')
        elif subtype == 'document': message_data['document_url'] = message_data['media_url']
    if message_data.get('file_size'): message_data['file_size_bytes'] = message_data['file_size']
    if isinstance(message_data.get('file_metadata'), str):
        try:
            metadata = json.loads(message_data['file_metadata'])
            message_data.update(metadata)
        except (json.JSONDecodeError, TypeError): pass 
    status_map = {"sent_to_server": "sent", "delivered_to_recipient": "delivered", "read_by_recipient": "read"}
    if message_data.get("status") in status_map: message_data["status"] = status_map[message_data["status"]]
    if message_data.get("stickers"): message_data["sticker_image_url"] = message_data["stickers"].get("image_url")
    return message_data

async def get_message_with_details_from_db(message_id: UUID) -> Optional[MessageInDB]:
    """Helper function to fetch a message and join its sticker/media details."""
    try:
        response = db_manager.get_table("messages").select("*, stickers(image_url)").eq("id", str(message_id)).maybe_single().execute()
        if not response.data: return None
        mapped_data = map_db_message_to_schema(response.data)
        return MessageInDB.model_validate(mapped_data)
    except Exception as e:
        logger.error(f"Error getting message with details from DB for message {message_id}: {e}", exc_info=True)
        return None

async def get_chat_list_for_user(user_id: UUID) -> List[ChatResponse]:
    """Helper to get a user's chat list, with last message details including sticker URL."""
    try:
        rpc_response = db_manager.admin_client.rpc('get_user_chat_list', {'p_user_id': str(user_id)}).execute()
        if not rpc_response.data: return []
        for chat_data in rpc_response.data:
            if chat_data.get('last_message'): chat_data['last_message'] = map_db_message_to_schema(chat_data['last_message'])
        return [ChatResponse.model_validate(chat) for chat in rpc_response.data]
    except Exception as e:
        logger.error(f"Error calling get_user_chat_list RPC for user {user_id}: {e}", exc_info=True)
        return []

@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(message_id: UUID, chat_id: UUID = Query(...), current_user: UserPublic = Depends(get_current_user)):
    logger.info(f"User {current_user.id} attempting to delete message {message_id} from chat {chat_id}")
    msg_resp = db_manager.get_table("messages").select("user_id, chat_id").eq("id", str(message_id)).single().execute()
    if not msg_resp.data: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    if str(msg_resp.data["user_id"]) != str(current_user.id) or str(msg_resp.data["chat_id"]) != str(chat_id): raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own messages.")
    db_manager.get_table("messages").delete().eq("id", str(message_id)).execute()
    await ws_manager.broadcast_message_deletion(str(chat_id), str(message_id))
    return None

@router.post("/{chat_id}/clear", status_code=status.HTTP_204_NO_CONTENT)
async def clear_chat_for_user(chat_id: UUID, current_user: UserPublic = Depends(get_current_active_user)):
    """Clears the chat history for the current user only by creating a marker message."""
    logger.info(f"User {current_user.id} clearing history for chat {chat_id} for themselves.")
    participant_check_resp = db_manager.get_table("chat_participants").select("user_id").eq("chat_id", str(chat_id)).eq("user_id", str(current_user.id)).maybe_single().execute()
    if not participant_check_resp.data: raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a participant of this chat.")
    marker_message = {"id": str(uuid.uuid4()), "chat_id": str(chat_id), "user_id": str(current_user.id), "message_subtype": "history_cleared_marker", "text": None, "created_at": "now()", "updated_at": "now()", "reactions": {}}
    db_manager.get_table("messages").insert(marker_message).execute()
    logger.info(f"History clear marker set for user {current_user.id} in chat {chat_id}.")
    return None

@router.post("/", response_model=ChatResponse)
async def create_chat(chat_create: ChatCreate, current_user: UserPublic = Depends(get_current_active_user)):
    recipient_id = chat_create.recipient_id
    if not current_user.partner_id or current_user.partner_id != recipient_id: raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only create a chat with your designated partner.")
    try:
        find_chat_resp = db_manager.admin_client.rpc('find_existing_chat_with_participant_details', {'user1_id': str(current_user.id), 'user2_id': str(recipient_id)}).execute()
        if find_chat_resp.data: return ChatResponse.model_validate(find_chat_resp.data)
    except Exception as e: logger.error(f"Error calling find_existing_chat RPC: {e}", exc_info=True)
    new_chat_id = uuid.uuid4()
    new_chat_data = {"id": str(new_chat_id), "created_at": "now()", "updated_at": "now()"}
    db_manager.get_table("chats").insert(new_chat_data).execute()
    participants_to_add = [{"chat_id": str(new_chat_id), "user_id": str(current_user.id), "joined_at": "now()"}, {"chat_id": str(new_chat_id), "user_id": str(recipient_id), "joined_at": "now()"}]
    db_manager.get_table("chat_participants").insert(participants_to_add).execute()
    find_chat_resp = db_manager.admin_client.rpc('find_existing_chat_with_participant_details', {'user1_id': str(current_user.id), 'user2_id': str(recipient_id)}).execute()
    if not find_chat_resp.data: raise HTTPException(status_code=500, detail="Failed to retrieve newly created chat.")
    return ChatResponse.model_validate(find_chat_resp.data)

@router.get("/", response_model=ChatListResponse)
async def list_chats(current_user: UserPublic = Depends(get_current_active_user)):
    chat_responses = await get_chat_list_for_user(current_user.id)
    return ChatListResponse(chats=chat_responses)

@router.get("/{chat_id}/messages", response_model=MessageListResponse)
async def get_messages(chat_id: UUID, limit: int = 50, before_timestamp: Optional[datetime] = None, current_user: UserPublic = Depends(get_current_active_user)):
    is_participant_resp = db_manager.get_table("chat_participants").select("user_id").eq("chat_id", str(chat_id)).eq("user_id", str(current_user.id)).execute()
    if not is_participant_resp.data: raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant of this chat")
    marker_resp = db_manager.get_table("messages").select("created_at").eq("chat_id", str(chat_id)).eq("user_id", str(current_user.id)).eq("message_subtype", "history_cleared_marker").order("created_at", desc=True).limit(1).maybe_single().execute()
    marker_timestamp = marker_resp.data['created_at'] if marker_resp and marker_resp.data else None
    query = db_manager.get_table("messages").select("*, stickers(image_url)").eq("chat_id", str(chat_id)).order("created_at", desc=True).limit(limit)
    if before_timestamp: query = query.lt("created_at", before_timestamp.isoformat())
    if marker_timestamp: query = query.gt("created_at", marker_timestamp)
    messages_resp = query.execute()
    messages_data_list = messages_resp.data or []
    cleaned_messages = [map_db_message_to_schema(m) for m in reversed(messages_data_list)]
    return MessageListResponse(messages=[MessageInDB.model_validate(m) for m in cleaned_messages])

@router.post("/{chat_id}/messages", response_model=MessageInDB)
async def send_message_http(chat_id: UUID, message_create: MessageCreate, current_user: UserPublic = Depends(get_current_active_user)):
    is_participant_resp = db_manager.get_table("chat_participants").select("user_id").eq("chat_id", str(chat_id)).eq("user_id", str(current_user.id)).maybe_single().execute()
    if not is_participant_resp.data: raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant of this chat")
    if await ws_manager.is_message_processed(message_create.client_temp_id): raise HTTPException(status_code=status.HTTP_200_OK, detail="Duplicate message, already processed.")
    message_id = uuid.uuid4()
    if message_create.mode == MessageModeEnum.INCOGNITO:
        incognito_message_obj = MessageInDB(id=message_id, chat_id=chat_id, user_id=current_user.id, **message_create.model_dump(exclude={'chat_id', 'recipient_id'}), status=MessageStatusEnum.SENT, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc), reactions={})
        await ws_manager.mark_message_as_processed(message_create.client_temp_id)
        await ws_manager.broadcast_chat_message(str(chat_id), incognito_message_obj)
        return incognito_message_obj
    message_data_to_insert = message_create.model_dump(exclude_unset=True, exclude={'chat_id', 'recipient_id'})
    message_data_to_insert.update({"id": str(message_id), "chat_id": str(chat_id), "user_id": str(current_user.id), "status": MessageStatusEnum.SENT.value, "mode": message_create.mode.value if message_create.mode else MessageModeEnum.NORMAL.value, "created_at": "now()", "updated_at": "now()", "reactions": {}})
    insert_resp_obj = db_manager.get_table("messages").insert(message_data_to_insert).execute()
    if not insert_resp_obj.data: raise HTTPException(status_code=500, detail="Failed to send message")
    await ws_manager.mark_message_as_processed(message_create.client_temp_id)
    db_manager.get_table("chats").update({"updated_at": "now()"}).eq("id", str(chat_id)).execute()
    message_for_response = await get_message_with_details_from_db(message_id)
    if not message_for_response: raise HTTPException(status_code=500, detail="Could not retrieve message details after sending.")
    await ws_manager.broadcast_chat_message(str(chat_id), message_for_response)
    await notification_service.send_new_message_notification(sender=current_user, chat_id=chat_id, message=message_for_response)
    return message_for_response

class MediaMessagePayload(BaseModel):
    client_temp_id: str
    chat_id: str
    public_id: str
    media_type: str
    cloudinary_metadata: dict

@router.post("/send-media-message", response_model=MessageInDB)
async def send_media_message(payload: MediaMessagePayload, current_user: UserPublic = Depends(get_current_active_user)):
    chat_id = UUID(payload.chat_id)
    is_participant_resp = db_manager.get_table("chat_participants").select("user_id").eq("chat_id", str(chat_id)).eq("user_id", str(current_user.id)).maybe_single().execute()
    if not is_participant_resp.data: raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant of this chat")
    if await ws_manager.is_message_processed(payload.client_temp_id): raise HTTPException(status_code=status.HTTP_200_OK, detail="Duplicate media message, already processed.")
    
    message_db_id = uuid.uuid4()
    cloudinary_meta = payload.cloudinary_metadata
    
    message_data_to_insert = {
        "id": str(message_db_id), "chat_id": str(chat_id), "user_id": str(current_user.id),
        "media_type": payload.media_type, "mode": MessageModeEnum.NORMAL.value, "status": MessageStatusEnum.SENT.value,
        "upload_status": "completed", "created_at": "now()", "updated_at": "now()", "reactions": {},
        "client_temp_id": payload.client_temp_id,
        "media_url": cloudinary_meta.get('secure_url'),
        "file_size": cloudinary_meta.get('bytes'),
        "thumbnail_url": next((item['secure_url'] for item in cloudinary_meta.get('eager', []) if item.get('transformation')), None),
        "file_metadata": json.dumps({
            "duration_seconds": cloudinary_meta.get('duration'),
            "audio_format": cloudinary_meta.get('audio', {}).get('codec'),
            "document_name": cloudinary_meta.get('original_filename'),
            "clip_type": cloudinary_meta.get('resource_type')
        })
    }
    
    db_manager.get_table("messages").insert(message_data_to_insert).execute()
    await ws_manager.mark_message_as_processed(payload.client_temp_id)
    db_manager.get_table("chats").update({"updated_at": "now()"}).eq("id", str(chat_id)).execute()
    
    message_out = await get_message_with_details_from_db(message_db_id)
    if not message_out: raise Exception(f"Could not retrieve media message details for ID: {message_db_id}")
    await ws_manager.broadcast_chat_message(str(chat_id), message_out)
    await notification_service.send_new_message_notification(sender=current_user, chat_id=chat_id, message=message_out)
    return message_out


@router.post("/messages/{message_id}/reactions", response_model=MessageInDB)
async def react_to_message(message_id: UUID, reaction_toggle: ReactionToggle, current_user: UserPublic = Depends(get_current_active_user)):
    message_resp_obj = db_manager.get_table("messages").select("*").eq("id", str(message_id)).maybe_single().execute()
    if not message_resp_obj.data: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    message_db = message_resp_obj.data 
    chat_id_str = str(message_db["chat_id"])
    if message_db.get("mode") == MessageModeEnum.INCOGNITO.value: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot react to incognito messages.")
    participant_check_resp = db_manager.get_table("chat_participants").select("user_id").eq("chat_id", chat_id_str).eq("user_id", str(current_user.id)).maybe_single().execute()
    if not participant_check_resp.data: raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant of this chat")
    reactions, emoji, user_id_str = message_db.get("reactions") or {}, reaction_toggle.emoji, str(current_user.id)
    if emoji not in reactions: reactions[emoji] = []
    if user_id_str in reactions[emoji]: reactions[emoji].remove(user_id_str)
    else: reactions[emoji].append(user_id_str)
    if not reactions[emoji]: del reactions[emoji]
    db_manager.get_table("messages").update({"reactions": reactions, "updated_at": "now()"}).eq("id", str(message_id)).execute()
    message_for_response = await get_message_with_details_from_db(message_id)
    if not message_for_response: raise HTTPException(status_code=500, detail="Could not retrieve updated message details after reaction.")
    await ws_manager.broadcast_reaction_update(chat_id_str, message_for_response)
    return message_for_response
