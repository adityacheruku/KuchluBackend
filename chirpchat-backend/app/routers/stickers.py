
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from uuid import UUID
from datetime import datetime, timezone

from app.auth.dependencies import get_current_active_user
from app.auth.schemas import UserPublic
from app.database import db_manager
from app.utils.logging import logger
from app.stickers.schemas import (
    StickerPackResponse, 
    StickerListResponse, 
    StickerSearchBody,
    StickerFavoriteToggle,
)

router = APIRouter(prefix="/stickers", tags=["Stickers"])

@router.get("/packs", response_model=StickerPackResponse)
async def get_sticker_packs(
    current_user: UserPublic = Depends(get_current_active_user)
):
    """
    Retrieve all active, non-premium sticker packs.
    TODO: In the future, this can be customized to also return premium packs the user has unlocked.
    """
    logger.info(f"User {current_user.id} requesting sticker packs.")
    try:
        packs_resp = db_manager.get_table("sticker_packs").select("*").eq("is_active", True).eq("is_premium", False).execute()
        if not packs_resp or not packs_resp.data:
            return StickerPackResponse(packs=[])
        
        return StickerPackResponse(packs=packs_resp.data)
    except Exception as e:
        logger.error(f"Error fetching sticker packs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not retrieve sticker packs.")

@router.get("/pack/{pack_id}", response_model=StickerListResponse)
async def get_stickers_in_pack(
    pack_id: UUID,
    current_user: UserPublic = Depends(get_current_active_user)
):
    """
    Get all stickers within a specific pack, ordered by their `order_index`.
    """
    logger.info(f"User {current_user.id} requesting stickers for pack {pack_id}.")
    try:
        stickers_resp = db_manager.get_table("stickers").select("*").eq("pack_id", str(pack_id)).order("order_index", desc=False).execute()
        
        if not stickers_resp or not stickers_resp.data:
            return StickerListResponse(stickers=[])
            
        return StickerListResponse(stickers=stickers_resp.data)
    except Exception as e:
        logger.error(f"Error fetching stickers for pack {pack_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not retrieve stickers for the specified pack.")

@router.post("/search", response_model=StickerListResponse)
async def search_stickers(
    search_body: StickerSearchBody,
    current_user: UserPublic = Depends(get_current_active_user)
):
    """
    Search for stickers by a keyword.
    The search query is matched against sticker names and tags.
    """
    query = search_body.query.strip()
    logger.info(f"User {current_user.id} searching for stickers with query: '{query}'")
    if not query:
        return StickerListResponse(stickers=[])

    try:
        # Using PostgREST 'or' filter to search in name or tags.
        # Searches for query as a substring in 'name' (case-insensitive)
        # OR if the 'tags' array contains the query term.
        search_filter = f"or(name.ilike.%{query}%,tags.cs.{{{query}}})"
        search_resp = db_manager.get_table("stickers").select("*").filter("and", search_filter).limit(50).execute()
        
        if not search_resp or not search_resp.data:
            return StickerListResponse(stickers=[])
        
        return StickerListResponse(stickers=search_resp.data)
    except Exception as e:
        logger.error(f"Error searching stickers with query '{query}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while searching for stickers.")

@router.get("/recent", response_model=StickerListResponse)
async def get_recent_stickers(
    limit: int = 20,
    current_user: UserPublic = Depends(get_current_active_user)
):
    """Retrieve user's recently used stickers."""
    user_id_str = str(current_user.id)
    logger.info(f"User {user_id_str} requesting recent stickers.")
    
    try:
        recent_usage_resp = db_manager.get_table("user_sticker_usage").select("sticker_id").eq("user_id", user_id_str).order("last_used", desc=True).limit(limit).execute()
        
        if not recent_usage_resp or not recent_usage_resp.data:
            return StickerListResponse(stickers=[])
            
        recent_sticker_ids = [str(row['sticker_id']) for row in recent_usage_resp.data]
        
        stickers_resp = db_manager.get_table("stickers").select("*").in_("id", recent_sticker_ids).execute()
        
        if not stickers_resp or not stickers_resp.data:
            return StickerListResponse(stickers=[])
            
        sticker_map = {str(sticker['id']): sticker for sticker in stickers_resp.data}
        ordered_stickers = [sticker_map[sticker_id] for sticker_id in recent_sticker_ids if sticker_id in sticker_map]
        
        return StickerListResponse(stickers=ordered_stickers)
    except Exception as e:
        logger.error(f"Error fetching recent stickers for user {user_id_str}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while retrieving recent stickers.")

@router.get("/favorites", response_model=StickerListResponse)
async def get_favorite_stickers(
    current_user: UserPublic = Depends(get_current_active_user)
):
    """Retrieve user's favorite stickers."""
    user_id_str = str(current_user.id)
    logger.info(f"User {user_id_str} requesting favorite stickers.")
    
    try:
        favs_resp = db_manager.get_table("user_favorite_stickers").select("sticker_id").eq("user_id", user_id_str).order("favorited_at", desc=True).execute()
        
        if not favs_resp or not favs_resp.data:
            return StickerListResponse(stickers=[])
            
        favorite_sticker_ids = [str(row['sticker_id']) for row in favs_resp.data]
        
        stickers_resp = db_manager.get_table("stickers").select("*").in_("id", favorite_sticker_ids).execute()
        
        if not stickers_resp or not stickers_resp.data:
            return StickerListResponse(stickers=[])

        sticker_map = {str(sticker['id']): sticker for sticker in stickers_resp.data}
        ordered_stickers = [sticker_map[sticker_id] for sticker_id in favorite_sticker_ids if sticker_id in sticker_map]

        return StickerListResponse(stickers=ordered_stickers)
    except Exception as e:
        logger.error(f"Error fetching favorite stickers for user {user_id_str}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while retrieving favorite stickers.")


@router.post("/favorites/toggle", response_model=StickerListResponse)
async def toggle_favorite_sticker(
    favorite_toggle: StickerFavoriteToggle,
    current_user: UserPublic = Depends(get_current_active_user)
):
    """Adds or removes a sticker from the user's favorites and returns the updated list."""
    user_id_str = str(current_user.id)
    sticker_id_str = str(favorite_toggle.sticker_id)
    
    try:
        existing_fav_resp = db_manager.get_table("user_favorite_stickers").select("sticker_id").eq("user_id", user_id_str).eq("sticker_id", sticker_id_str).maybe_single().execute()
        
        if existing_fav_resp and existing_fav_resp.data:
            db_manager.get_table("user_favorite_stickers").delete().eq("user_id", user_id_str).eq("sticker_id", sticker_id_str).execute()
            logger.info(f"User {user_id_str} removed sticker {sticker_id_str} from favorites.")
        else:
            db_manager.get_table("user_favorite_stickers").insert({
                "user_id": user_id_str,
                "sticker_id": sticker_id_str,
                "favorited_at": datetime.now(timezone.utc).isoformat()
            }).execute()
            logger.info(f"User {user_id_str} added sticker {sticker_id_str} to favorites.")
            
        # Instead of duplicating code, just call the get_favorite_stickers function
        return await get_favorite_stickers(current_user)

    except Exception as e:
        logger.error(f"Error toggling favorite sticker for user {user_id_str}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not update sticker favorites.")
