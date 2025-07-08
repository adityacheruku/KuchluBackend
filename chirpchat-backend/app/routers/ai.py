import os
from enum import Enum
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.auth.dependencies import get_current_user
from app.auth.models import UserInDB as User
import httpx

HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
HUGGINGFACE_MOOD_MODEL_URL = os.getenv("HUGGINGFACE_MOOD_MODEL_URL")

class Mood(str, Enum):
    happy = "happy"
    sad = "sad"
    neutral = "neutral"
    angry = "angry"
    # Add more moods as needed

class SuggestMoodInput(BaseModel):
    messageText: str
    currentMood: Mood

class SuggestMoodOutput(BaseModel):
    suggestedMood: Mood = None
    confidence: float = None
    reasoning: str = None

router = APIRouter(prefix="/ai", tags=["AI"])

@router.post("/suggest-mood", response_model=SuggestMoodOutput)
async def suggest_mood(
    input_data: SuggestMoodInput,
    current_user: User = Depends(get_current_user),
):
    if not HUGGINGFACE_API_KEY or not HUGGINGFACE_MOOD_MODEL_URL:
        raise HTTPException(status_code=500, detail="AI model configuration missing")

    headers = {
        "Authorization": f"Bearer {HUGGINGFACE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": input_data.messageText,
        # Optionally include currentMood if model supports it
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(HUGGINGFACE_MOOD_MODEL_URL, json=payload, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to get mood suggestion from AI model")
        result = response.json()

    # Parse result according to model's response format
    # This is a placeholder parsing logic
    suggested_mood = result.get("label", None)
    confidence = result.get("score", None)
    reasoning = result.get("reasoning", None)

    return SuggestMoodOutput(
        suggestedMood=suggested_mood,
        confidence=confidence,
        reasoning=reasoning,
    )
