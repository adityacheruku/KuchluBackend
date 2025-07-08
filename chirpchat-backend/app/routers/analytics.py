from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from app.auth.dependencies import get_current_active_user
from app.auth.schemas import UserPublic
from app.database import db_manager
from app.utils.logging import logger
from app.analytics.schemas import FileAnalyticsCreate, MoodAnalyticsCreate
from app.analytics.service import analytics_service
from datetime import datetime, timezone
from typing import Optional, List

router = APIRouter(prefix="/analytics", tags=["Analytics"])


class MoodSuggestion(BaseModel):
    id: str
    label: str
    emoji: Optional[str] = None

class MoodSuggestionResponse(BaseModel):
    suggestions: List[MoodSuggestion]


@router.post("/file", status_code=status.HTTP_201_CREATED)
async def track_file_analytics(
    payload: FileAnalyticsCreate,
    current_user: UserPublic = Depends(get_current_active_user)
):
    """
    Receives and stores file upload analytics from the client.
    This is a fire-and-forget endpoint from the client's perspective.
    """
    logger.info(f"Received file analytics for message {payload.message_id} from user {current_user.id}")
    
    analytics_data = {
        "user_id": str(current_user.id),
        "message_id": str(payload.message_id),
        "upload_duration_seconds": payload.upload_duration_seconds,
        "file_size_bytes": payload.file_size_bytes,
        "compressed_size_bytes": payload.compressed_size_bytes,
        "network_quality": payload.network_quality,
        "file_type": payload.file_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    
    try:
        db_manager.admin_client.table("file_analytics").insert(analytics_data).execute()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Could not store file analytics: {e}", exc_info=True)
        # We don't raise an HTTPException because the client doesn't need to know about this failure.
        # This is a background tracking task.
        return {"status": "error"}

@router.post("/mood", status_code=status.HTTP_201_CREATED)
async def track_mood_analytics(
    payload: MoodAnalyticsCreate,
    current_user: UserPublic = Depends(get_current_active_user)
):
    """
    Receives and stores mood selection analytics from the client.
    This captures the initial mood selection event. The outcome fields
    can be populated later by a separate process.
    """
    logger.info(f"Received mood analytics for '{payload.mood_id}' from user {current_user.id}")
    
    analytics_data = {
        "user_id": str(current_user.id),
        "mood_id": payload.mood_id,
        "mood_emoji": payload.mood_emoji,
        "context": payload.context.model_dump_json(), # Store context as a JSON string
        "created_at": datetime.now(timezone.utc).isoformat(),
        # Outcome fields are null initially, to be filled in later by another service/process
        "partner_response_time": None,
        "partner_reaction": None,
        "conversation_started": None,
        "mood_reciprocated": None,
    }
    
    try:
        # Assumes a 'mood_analytics' table exists in the database
        db_manager.admin_client.table("mood_analytics").insert(analytics_data).execute()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Could not store mood analytics: {e}", exc_info=True)
        # This is a background task, so we don't want to fail the user's primary action.
        return {"status": "error"}


@router.get("/moods/suggestions", response_model=MoodSuggestionResponse)
async def get_suggested_moods(current_user: UserPublic = Depends(get_current_active_user)):
    """
    Returns a list of suggested moods for the user based on their usage history.
    """
    suggestions = await analytics_service.get_frequently_used_moods(user_id=current_user.id)
    return MoodSuggestionResponse(suggestions=[MoodSuggestion(**s) for s in suggestions])

@router.get("/moods/partner-suggestions", response_model=MoodSuggestionResponse)
async def get_partner_suggested_moods(current_user: UserPublic = Depends(get_current_active_user)):
    """
    Returns a list of suggested moods based on the user's partner's usage history.
    """
    if not current_user.partner_id:
        return MoodSuggestionResponse(suggestions=[])
        
    suggestions = await analytics_service.get_partner_influenced_mood_suggestions(partner_id=current_user.partner_id)
    return MoodSuggestionResponse(suggestions=[MoodSuggestion(**s) for s in suggestions])
