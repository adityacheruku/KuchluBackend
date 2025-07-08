
import os
import time
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Literal, Optional, List, Dict, Any

import cloudinary
from cloudinary.utils import api_sign_request
from dotenv import load_dotenv
load_dotenv()
from app.auth.dependencies import get_current_active_user
from app.auth.schemas import UserPublic
from app.utils.logging import logger
from app.config import settings

cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
    secure=True
)

router = APIRouter(prefix="/uploads", tags=["Uploads"])

class GetUploadSignatureRequest(BaseModel):
    public_id: str
    resource_type: Literal["image", "video", "raw", "auto"] = "auto"
    folder: str = "user_media_uploads"

class UploadSignatureResponse(BaseModel):
    signature: str
    timestamp: int
    api_key: str
    cloud_name: str
    public_id: str
    folder: str
    resource_type: str
    upload_preset: str
    eager: Optional[str] = None
    notification_url: Optional[str] = None
    type: str # Added type for 'private' uploads

@router.post("/get-cloudinary-upload-signature", response_model=UploadSignatureResponse, summary="Generate a signature for direct Cloudinary upload")
async def get_cloudinary_upload_signature(
    request: GetUploadSignatureRequest,
    current_user: UserPublic = Depends(get_current_active_user)
):
    """
    Generates a secure, time-sensitive signature that allows the client
    to upload a file directly to Cloudinary, bypassing our backend.
    """
    try:
        timestamp = int(time.time())
        final_folder = f"{request.folder}/user_{current_user.id}"
        upload_preset_name = "my_signed__upload_preset"

        if not settings.CLOUDINARY_WEBHOOK_URL:
            logger.error("CLOUDINARY_WEBHOOK_URL is not configured in the environment.")
            raise HTTPException(status_code=500, detail="Server is not configured for upload notifications.")

        notification_url = settings.CLOUDINARY_WEBHOOK_URL

        params_to_sign: Dict[str, Any] = {
            "timestamp": timestamp,
            "public_id": request.public_id,
            "folder": final_folder,
            "resource_type": request.resource_type,
            "type": "private", # This is the 'type' parameter (e.g., 'upload', 'private', 'authenticated')
            "notification_url": notification_url,
            "upload_preset": upload_preset_name,
        }

        eager_transformations: List[Dict[str, Any]] = []
        if request.resource_type == "image":
            eager_transformations.extend([
                {"width": 250, "height": 250, "crop": "fill", "quality": "auto", "format": "jpg"},
                {"width": 800, "quality": "auto", "format": "webp"}
            ])
        elif request.resource_type == "video":
            eager_transformations.extend([
                {"format": "mp4", "quality": "auto:low", "video_codec": "auto"},
                {"format": "mp3"},
                {"streaming_profile": "auto", "format": "m3u8"},
                {"format": "jpg", "start_offset": "1", "width": 400, "crop": "scale"},
                {"format": "gif", "duration": "5", "width": 250, "crop": "fill"}
            ])
        elif request.resource_type == "raw":
            eager_transformations.extend([
                {"format": "mp3"}
            ])

        if eager_transformations:
            eager_strings = []
            for t in eager_transformations:
                sorted_t_items = sorted(t.items())
                eager_strings.append("/".join([f"{k}_{v}" for k, v in sorted_t_items]))
            params_to_sign["eager"] = "|".join(eager_strings)

        logger.info(f"Parameters to sign: {params_to_sign}")
        signature = api_sign_request(params_to_sign, settings.CLOUDINARY_API_SECRET)

        return UploadSignatureResponse(
            signature=signature,
            timestamp=timestamp,
            api_key=settings.CLOUDINARY_API_KEY,
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            public_id=request.public_id,
            folder=final_folder,
            resource_type=request.resource_type,
            upload_preset=upload_preset_name,
            eager=params_to_sign.get("eager"),
            notification_url=notification_url,
            type="private"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating Cloudinary signature: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not generate upload signature.")

async def delete_cloudinary_asset(public_id: str, resource_type: str):
    """
    Asynchronously deletes a media asset from Cloudinary.
    Intended to be run as a background task.
    """
    try:
        logger.info(f"Background task: Deleting Cloudinary asset {public_id} (Type: {resource_type})")
        result = cloudinary.uploader.destroy(
            public_id,
            resource_type=resource_type,
            invalidate=True
        )
        if result.get("result") == "ok":
            logger.info(f"Successfully deleted Cloudinary asset: {public_id}")
        elif result.get("result") == "not found":
            logger.warning(f"Cloudinary asset {public_id} not found, assuming already deleted.")
        else:
            logger.error(f"Cloudinary API reported an error for asset {public_id}: {result.get('error', 'Unknown error')}")
    except Exception as e:
        logger.error(f"Exception during Cloudinary deletion for asset {public_id}: {e}", exc_info=True)
