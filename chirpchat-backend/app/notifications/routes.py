
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional
from uuid import UUID

from app.auth.dependencies import get_current_active_user
from app.auth.schemas import UserPublic
from app.database import db_manager
from app.utils.logging import logger
from app.notifications.schemas import PushSubscriptionCreate, NotificationSettingsUpdate, NotificationSettingsResponse
from postgrest.exceptions import APIError

router = APIRouter(prefix="/notifications", tags=["Notifications"])

@router.post("/subscribe", status_code=status.HTTP_201_CREATED)
async def subscribe_to_push(
    subscription: PushSubscriptionCreate,
    current_user: UserPublic = Depends(get_current_active_user)
):
    """
    Subscribes a user's device to push notifications.
    The frontend provides the subscription object from the browser's Push API.
    """
    logger.info(f"User {current_user.id} attempting to subscribe endpoint: {subscription.endpoint}")
    
    sub_data = {
        "user_id": str(current_user.id),
        "endpoint": subscription.endpoint,
        "p256dh_key": subscription.keys.p256dh,
        "auth_key": subscription.keys.auth,
        "is_active": True,
        # 'device_info' could be added here if sent from the client
    }
    
    try:
        # Use upsert to handle cases where the same endpoint subscribes again.
        # It will update the keys and ensure it's active.
        db_manager.admin_client.table("push_subscriptions").upsert(sub_data).execute()
        logger.info(f"Successfully subscribed/updated endpoint for user {current_user.id}")
        return {"msg": "Subscription successful"}
    except APIError as e:
        logger.error(f"Error subscribing user {current_user.id} to push notifications: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not save push subscription")

@router.post("/unsubscribe", status_code=status.HTTP_200_OK)
async def unsubscribe_from_push(
    subscription: dict, # Expecting {"endpoint": "..."}
    current_user: UserPublic = Depends(get_current_active_user)
):
    """
    Unsubscribes a user's device from push notifications.
    """
    endpoint = subscription.get("endpoint")
    if not endpoint:
        raise HTTPException(status_code=400, detail="Endpoint is required")

    logger.info(f"User {current_user.id} attempting to unsubscribe endpoint: {endpoint}")
    
    try:
        # Instead of deleting, we mark as inactive. This could be useful for analytics.
        db_manager.admin_client.table("push_subscriptions").update(
            {"is_active": False}
        ).eq("user_id", str(current_user.id)).eq("endpoint", endpoint).execute()
        
        logger.info(f"Successfully unsubscribed endpoint for user {current_user.id}")
        return {"msg": "Unsubscription successful"}
    except APIError as e:
        logger.error(f"Error unsubscribing user {current_user.id} from push notifications: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not remove push subscription")

@router.get("/settings", response_model=NotificationSettingsResponse)
async def get_notification_settings(
    current_user: UserPublic = Depends(get_current_active_user)
):
    """
    Retrieves the current user's notification preferences.
    If settings don't exist, it creates and returns default settings.
    """
    logger.info(f"Fetching notification settings for user {current_user.id}")
    try:
        settings_resp = db_manager.get_table("user_notification_settings").select("*").eq("user_id", str(current_user.id)).maybe_single().execute()
        
        if not settings_resp or not settings_resp.data:
            logger.warning(f"No notification settings found for user {current_user.id}. Creating default settings.")
            
            # Create default settings
            default_settings = {
                "user_id": str(current_user.id),
                "messages": True,
                "mood_updates": True,
                "thinking_of_you": True,
                "voice_messages": True,
                "media_sharing": True,
                "quiet_hours_enabled": False,
                "quiet_hours_start": None,
                "quiet_hours_end": None,
                "quiet_hours_weekdays_only": False,
                "timezone": "UTC",
                "is_dnd_enabled": False,
                "custom_moods": [],
                "quick_moods": [],
            }
            
            # Insert default settings into the database
            insert_resp = db_manager.admin_client.table("user_notification_settings").insert(default_settings).execute()
            
            if not insert_resp.data:
                raise HTTPException(status_code=500, detail="Failed to create default notification settings.")
            
            # Return the newly created settings
            return NotificationSettingsResponse(**insert_resp.data[0])

        # If settings were found, return them
        return NotificationSettingsResponse(**settings_resp.data)

    except APIError as e:
        logger.error(f"Error fetching/creating notification settings for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not retrieve or create notification settings.")

@router.put("/settings", response_model=NotificationSettingsResponse)
async def update_notification_settings(
    settings_update: NotificationSettingsUpdate,
    current_user: UserPublic = Depends(get_current_active_user)
):
    """
    Updates the current user's notification preferences.
    """
    update_data = settings_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No settings provided to update")

    logger.info(f"User {current_user.id} updating notification settings with: {update_data}")
    
    try:
        db_manager.get_table("user_notification_settings").update(
            update_data
        ).eq("user_id", str(current_user.id)).execute()

        updated_settings_resp = db_manager.get_table("user_notification_settings").select("*").eq("user_id", str(current_user.id)).maybe_single().execute()

        if not updated_settings_resp or not updated_settings_resp.data:
             raise HTTPException(status_code=404, detail="Failed to update settings or user not found")

        return NotificationSettingsResponse(**updated_settings_resp.data)
    except APIError as e:
        logger.error(f"Error updating notification settings for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not update notification settings")
