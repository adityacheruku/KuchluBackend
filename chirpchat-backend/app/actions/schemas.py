from pydantic import BaseModel

class MoodUpdatePayload(BaseModel):
    mood: str

class MoodPingPayload(BaseModel):
    mood_name: str
    mood_emoji: str
