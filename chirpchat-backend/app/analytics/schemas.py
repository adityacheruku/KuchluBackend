

from pydantic import BaseModel, Field
from typing import Optional, Literal
from uuid import UUID

class FileAnalyticsCreate(BaseModel):
    message_id: UUID
    upload_duration_seconds: float
    file_size_bytes: int
    compressed_size_bytes: Optional[int] = None
    network_quality: str
    file_type: str

class MoodAnalyticsContext(BaseModel):
    time_of_day: Literal['morning', 'afternoon', 'evening', 'night']
    day_of_week: Literal['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    partner_id: Optional[UUID] = None
    source: Optional[Literal['assistive_touch_ping', 'profile_update']] = None


class MoodAnalyticsCreate(BaseModel):
    mood_id: str = Field(..., max_length=50)
    mood_emoji: Optional[str] = None
    context: MoodAnalyticsContext
