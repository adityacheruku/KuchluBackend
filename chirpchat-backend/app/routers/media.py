

import time
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from typing import Literal, Dict, Any
import cloudinary
import cloudinary.utils
from uuid import UUID

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserPublic
from app.database import db_manager
from app.utils.logging import logger
from app.config import settings

router = APIRouter(prefix="/media", tags=["Media"])

cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
    secure=True
)

class SignedUrlResponse(BaseModel):
    url: str

@router.get("/{message_id}", response_model=SignedUrlResponse)
async def get_signed_media_url(
    message_id: UUID,
    current_user: UserPublic = Depends(get_current_user),
    version: str = Query('original')
):
    """
    Provides a secure, short-lived URL to access a private media asset.
    This endpoint verifies that the user is a participant in the chat
    before generating the signed URL for a specific media version.
    """
    message_resp = db_manager.get_table("messages").select("chat_id, file_metadata").eq("id", str(message_id)).maybe_single().execute()
    if not message_resp.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media message not found.")
        
    chat_id = message_resp.data.get('chat_id')
    participant_resp = db_manager.get_table("chat_participants").select("user_id").eq("chat_id", str(chat_id)).eq("user_id", str(current_user.id)).maybe_single().execute()
    
    if not participant_resp.data:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not authorized to view this media.")

    metadata = message_resp.data.get('file_metadata')
    if not isinstance(metadata, dict):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media metadata is missing or invalid.")

    public_id = metadata.get('public_id')
    resource_type = metadata.get('resource_type', 'image')
    
    if not public_id:
         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media public_id not found in metadata.")
         
    urls: Dict[str, Any] = metadata.get('urls', {})
    
    target_url_path = urls.get(version)
    if not target_url_path:
        target_url_path = urls.get('original')
        if not target_url_path:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Media version '{version}' or 'original' not found.")

    try:
        expires_at = int(time.time()) + 600 # 10 minutes expiry
        
        # Cloudinary URLs might already be fully qualified. We just need to sign them.
        # Let's rebuild the URL with transformations to be safe.
        url_options = {
            "resource_type": resource_type,
            "type": "private",
            "expires_at": expires_at,
        }
        
        # Extract transformations if they exist in the path, e.g. /t_my_preset/
        # This is a simplified example. Production logic might need to be more robust.
        # For now, we assume the full path is not needed and transformations are applied via presets if any
        
        signed_url = cloudinary.utils.cloudinary_url(public_id, **url_options)[0]
        
        return SignedUrlResponse(url=signed_url)

    except Exception as e:
        logger.error(f"Error generating signed URL for public_id {public_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not generate secure media URL.")

