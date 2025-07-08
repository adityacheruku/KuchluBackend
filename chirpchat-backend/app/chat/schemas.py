from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
import enum

class ClipTypeEnum(str, enum.Enum):
    AUDIO = "audio"
    VIDEO = "video"

class MessageSubtypeEnum(str, enum.Enum):
    TEXT = "text"
    STICKER = "sticker"
    CLIP = "clip"
    IMAGE = "image"
    DOCUMENT = "document"
    VOICE_MESSAGE = "voice_message"
    EMOJI_ONLY = "emoji_only"
    HISTORY_CLEARED_MARKER = "history_cleared_marker"

class MessageModeEnum(str, enum.Enum):
    NORMAL = "normal"
    FIGHT = "fight"
    INCOGNITO = "incognito"

SUPPORTED_EMOJIS = ['👍', '❤️', '😂', '😮', '😢', '🙏']
SupportedEmoji = str

class MessageStatusEnum(str, enum.Enum):
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"

class MessageBase(BaseModel):
    text: Optional[str] = None
    message_subtype: Optional[MessageSubtypeEnum] = MessageSubtypeEnum.TEXT
    mode: Optional[MessageModeEnum] = MessageModeEnum.NORMAL
    sticker_id: Optional[UUID] = None
    clip_type: Optional[ClipTypeEnum] = None
    clip_placeholder_text: Optional[str] = None
    clip_url: Optional[str] = None
    image_url: Optional[str] = None
    image_thumbnail_url: Optional[str] = None
    preview_url: Optional[str] = None
    document_url: Optional[str] = None
    document_name: Optional[str] = None
    duration_seconds: Optional[int] = None
    file_size_bytes: Optional[int] = None
    file_metadata: Optional[Dict[str, Any]] = None
    audio_format: Optional[str] = None
    transcription: Optional[str] = None
    reply_to_message_id: Optional[UUID] = None

class MessageCreate(MessageBase):
    chat_id: Optional[UUID] = None
    recipient_id: Optional[UUID] = None
    client_temp_id: Optional[str] = None

class MessageInDB(MessageBase):
    id: UUID
    user_id: UUID
    chat_id: UUID
    created_at: datetime
    updated_at: datetime
    reactions: Optional[Dict[SupportedEmoji, List[UUID]]] = Field(default_factory=dict)
    status: Optional[MessageStatusEnum] = MessageStatusEnum.SENT
    client_temp_id: Optional[str] = None
    sticker_image_url: Optional[str] = None
    class Config: from_attributes = True

class ChatParticipant(BaseModel):
    id: UUID
    display_name: str
    avatar_url: Optional[str] = None
    mood: Optional[str] = "Neutral"
    is_online: Optional[bool] = False
    last_seen: Optional[datetime] = None
    class Config: from_attributes = True

class ChatBase(BaseModel):
    id: UUID

class ChatResponse(ChatBase):
    participants: List[ChatParticipant]
    last_message: Optional[MessageInDB] = None
    created_at: datetime
    updated_at: datetime
    class Config: from_attributes = True

class ReactionToggle(BaseModel):
    emoji: SupportedEmoji

class ChatCreate(BaseModel):
    recipient_id: UUID

class ChatListResponse(BaseModel):
    chats: List[ChatResponse]

class MessageListResponse(BaseModel):
    messages: List[MessageInDB]

class DefaultChatPartnerResponse(BaseModel):
    user_id: UUID
    display_name: str
    avatar_url: Optional[str] = None
    class Config: from_attributes = True
