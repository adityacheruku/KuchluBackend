
from pydantic import BaseModel, Field
from typing import Optional, Dict, List
from uuid import UUID
import datetime

class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str

class PushSubscriptionCreate(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys

class NotificationSettingsUpdate(BaseModel):
    messages: Optional[bool] = None
    mood_updates: Optional[bool] = None
    thinking_of_you: Optional[bool] = None
    voice_messages: Optional[bool] = None
    media_sharing: Optional[bool] = None
    quiet_hours_enabled: Optional[bool] = None
    quiet_hours_start: Optional[datetime.time] = None
    quiet_hours_end: Optional[datetime.time] = None
    quiet_hours_weekdays_only: Optional[bool] = None
    timezone: Optional[str] = Field(None, max_length=50)
    is_dnd_enabled: Optional[bool] = None
    custom_moods: Optional[List[Dict[str, str]]] = None # e.g., [{ "id": "Studying", "emoji": "📚" }]
    quick_moods: Optional[List[str]] = None # e.g., ["Happy", "Sad", "Studying"]

class NotificationSettingsResponse(BaseModel):
    user_id: UUID
    messages: bool
    mood_updates: bool
    thinking_of_you: bool
    voice_messages: bool
    media_sharing: bool
    quiet_hours_enabled: bool
    quiet_hours_start: Optional[datetime.time] = None
    quiet_hours_end: Optional[datetime.time] = None
    quiet_hours_weekdays_only: bool
    timezone: str
    is_dnd_enabled: bool
    custom_moods: List[Dict[str, str]] = Field(default_factory=list)
    quick_moods: List[str] = Field(default_factory=list)

    class Config:
        from_attributes = True

class NotificationPayload(BaseModel):
    title: str
    options: Dict
