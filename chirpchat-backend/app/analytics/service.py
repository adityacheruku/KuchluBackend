
from uuid import UUID
from datetime import datetime, timedelta, timezone
from collections import Counter

from app.database import db_manager
from app.utils.logging import logger
from postgrest.exceptions import APIError

async def get_frequently_used_moods(user_id: UUID, count: int = 5, days_ago: int = 90) -> list:
    """
    Analyzes mood usage for a user and returns their most frequent moods.
    """
    try:
        time_cutoff = datetime.now(timezone.utc) - timedelta(days=days_ago)
        
        response = db_manager.admin_client.table("mood_analytics").select(
            "mood_name, mood_emoji"
        ).eq("user_id", str(user_id)).gte(
            "created_at", time_cutoff.isoformat()
        ).execute()
        
        if not response.data:
            return []
            
        # Use a counter to get frequencies of (mood_name, mood_emoji) tuples
        mood_counter = Counter(
            (item['mood_name'], item.get('mood_emoji')) for item in response.data if item.get('mood_name')
        )
        
        most_common_moods = mood_counter.most_common(count)
        
        suggestions = [
            {"id": mood_name, "emoji": mood_emoji or '❓', "label": mood_name} 
            for (mood_name, mood_emoji), freq in most_common_moods
        ]
        
        return suggestions
        
    except Exception as e:
        logger.error(f"Error getting suggested moods for user {user_id}: {e}", exc_info=True)
        return []

async def get_partner_influenced_mood_suggestions(partner_id: UUID, count: int = 5, days_ago: int = 30) -> list:
    """
    Analyzes mood usage for a user's partner and returns their most frequent moods.
    """
    if not partner_id:
        return []
    try:
        time_cutoff = datetime.now(timezone.utc) - timedelta(days=days_ago)
        
        # Query for moods sent BY THE PARTNER.
        response = db_manager.admin_client.table("mood_analytics").select(
            "mood_name, mood_emoji"
        ).eq("user_id", str(partner_id)).gte( # The user_id is the partner because they are the sender
            "created_at", time_cutoff.isoformat()
        ).execute()
        
        if not response.data:
            return []
            
        mood_counter = Counter(
            (item['mood_name'], item.get('mood_emoji')) for item in response.data if item.get('mood_name')
        )
        
        most_common_moods = mood_counter.most_common(count)
        
        suggestions = [
            {"id": mood_name, "emoji": mood_emoji or '❓', "label": mood_name} 
            for (mood_name, mood_emoji), freq in most_common_moods
        ]
        
        return suggestions
        
    except APIError as e:
        logger.error(f"Error getting partner suggested moods for partner {partner_id}: {e.message}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"Unexpected error in get_partner_influenced_mood_suggestions for partner {partner_id}: {e}", exc_info=True)
        return []

class AnalyticsService:
    async def get_frequently_used_moods(self, user_id: UUID, count: int = 5, days_ago: int = 90) -> list:
        return await get_frequently_used_moods(user_id, count, days_ago)
    
    async def get_partner_influenced_mood_suggestions(self, partner_id: UUID, count: int = 5, days_ago: int = 30) -> list:
        return await get_partner_influenced_mood_suggestions(partner_id, count, days_ago)

analytics_service = AnalyticsService()
