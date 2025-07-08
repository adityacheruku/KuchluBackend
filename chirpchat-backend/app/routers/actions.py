
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from uuid import UUID
from datetime import datetime, timezone

from app.auth.dependencies import get_current_active_user
from app.auth.schemas import UserPublic
from app.notifications.service import notification_service
from app.database import db_manager
from app.websocket import manager as ws_manager
from app.utils.logging import logger
from app.actions.schemas import MoodUpdatePayload, MoodPingPayload
from app.analytics.schemas import MoodAnalyticsCreate, MoodAnalyticsContext

router = APIRouter(prefix="/actions", tags=["Quick Actions"])

async def _track_mood_analytics(user_id: UUID, mood_name: str, mood_emoji: str | None, context: dict):
    """Helper function to be run in the background for tracking mood analytics."""
    now = datetime.now(timezone.utc)
    day_of_week = now.strftime('%A').lower()
    time_of_day = 'night'
    if 5 <= now.hour < 12: time_of_day = 'morning'
    elif 12 <= now.hour < 17: time_of_day = 'afternoon'
    elif 17 <= now.hour < 21: time_of_day = 'evening'
    
    analytics_context_payload = MoodAnalyticsContext(
        time_of_day=time_of_day, 
        day_of_week=day_of_week,
        partner_id=context.get("partner_id"),
        source=context.get("source")
    )
    
    # This is for validation only
    analytics_payload = MoodAnalyticsCreate(
        mood_name=mood_name,
        mood_emoji=mood_emoji,
        context=analytics_context_payload
    )

    analytics_data = {
        "user_id": str(user_id),
        "partner_id": str(context.get("partner_id")) if context.get("partner_id") else None,
        "mood_name": mood_name,
        "mood_emoji": mood_emoji,
        "source": context.get("source"),
        "context": analytics_context_payload.model_dump_json(),
        "created_at": now.isoformat(),
    }
    
    try:
        db_manager.admin_client.table("mood_analytics").insert(analytics_data).execute()
        logger.info(f"Logged mood analytics for user {user_id}: {mood_name}")
    except Exception as e:
        logger.error(f"Failed to log mood analytics for user {user_id}: {e}", exc_info=True)


@router.post("/update-mood", response_model=UserPublic)
async def update_mood(
    payload: MoodUpdatePayload,
    background_tasks: BackgroundTasks,
    current_user: UserPublic = Depends(get_current_active_user)
):
    """
    Updates the user's mood and notifies their partner.
    This is a simplified endpoint intended for quick actions like from the AssistiveTouch menu.
    """
    logger.info(f"User {current_user.id} updating mood to '{payload.mood}' via quick action.")
    
    update_data = {
        "mood": payload.mood,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    updated_user_response_obj = db_manager.get_table("users").update(update_data).eq("id", str(current_user.id)).select().single().execute()
    
    if not updated_user_response_obj.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found or update failed")

    updated_user = UserPublic.model_validate(updated_user_response_obj.data)

    background_tasks.add_task(
        _track_mood_analytics,
        user_id=current_user.id,
        mood_name=payload.mood,
        mood_emoji=None, # Not available in this simpler context
        context={
            "partner_id": updated_user.partner_id,
            "source": "profile_update"
        }
    )
    await ws_manager.broadcast_user_profile_update(user_id=current_user.id, updated_data={"mood": updated_user.mood})
    
    if updated_user.partner_id and updated_user.mood != current_user.mood:
        await notification_service.send_mood_change_notification(user=updated_user, new_mood=updated_user.mood)
        
    return updated_user

@router.post("/ping-mood", status_code=status.HTTP_200_OK)
async def ping_mood(
    payload: MoodPingPayload,
    background_tasks: BackgroundTasks,
    current_user: UserPublic = Depends(get_current_active_user)
):
    """
    Sends a one-time mood notification to the user's partner.
    This action is checked against the recipient's DND settings.
    It also logs this action for analytics.
    """
    if not current_user.partner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="You do not have a partner to send a mood to.")
    
    logger.info(f"User {current_user.id} sending mood ping '{payload.mood_name}' to partner {current_user.partner_id}.")

    background_tasks.add_task(
        _track_mood_analytics,
        user_id=current_user.id,
        mood_name=payload.mood_name,
        mood_emoji=payload.mood_emoji,
        context={
            "partner_id": current_user.partner_id,
            "source": "assistive_touch_ping"
        }
    )
    
    await notification_service.send_mood_ping_notification(
        sender=current_user,
        recipient_id=current_user.partner_id,
        mood_id=payload.mood_name,
        mood_emoji=payload.mood_emoji
    )

    return {"status": "Mood ping sent"}
