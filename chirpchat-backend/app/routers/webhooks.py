

import json
from fastapi import APIRouter, Request, Header, HTTPException, status, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
import cloudinary
import cloudinary.utils
import hmac
import os
from hashlib import sha1

from app.config import settings
from app.database import db_manager
from app.websocket import manager as ws_manager
from app.chat.routes import get_message_with_details_from_db
from app.utils.logging import logger

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

def verify_cloudinary_signature(body: bytes, signature_header: str, timestamp_header: str) -> bool:
    """Verifies the Cloudinary webhook signature using HMAC-SHA1."""
    if not settings.CLOUDINARY_API_SECRET:
        logger.error("CLOUDINARY_API_SECRET is not set. Cannot verify webhook.")
        return False
        
    try:
        sig_parts = {p.split('=')[0]: p.split('=')[1] for p in signature_header.split(' ')}
        v1_signature = sig_parts.get('v1')

        if not v1_signature:
            logger.warning("Webhook signature 'v1' not found in header.")
            return False

        string_to_sign = body + timestamp_header.encode('utf-8') + settings.CLOUDINARY_API_SECRET.encode('utf-8')
        
        expected_signature = sha1(string_to_sign).hexdigest()
        
        return hmac.compare_digest(expected_signature, v1_signature)
    except Exception as e:
        logger.error(f"Unexpected error during webhook signature verification: {e}")
        return False

class EagerTransformation(BaseModel):
    transformation: str
    width: Optional[int] = None
    height: Optional[int] = None
    bytes: Optional[int] = None
    format: str
    url: str
    secure_url: str

class CloudinaryWebhookPayload(BaseModel):
    public_id: str
    version: int
    asset_id: str
    resource_type: str
    format: str
    bytes: int
    width: Optional[int] = None
    height: Optional[int] = None
    url: str
    secure_url: str
    duration: Optional[float] = None
    original_filename: Optional[str] = None
    eager: Optional[List[EagerTransformation]] = Field(None)
    notification_type: str


def map_eager_to_urls(eager_list: Optional[List[EagerTransformation]], resource_type: str) -> dict:
    urls = {}
    if not eager_list:
        return urls
        
    for t in eager_list:
        if resource_type == "image":
            if "w_250" in t.transformation:
                urls["thumbnail_250"] = t.secure_url.split(t.url.split('/')[-1])[0] + t.url.split('/')[-1]
            elif "w_800" in t.transformation:
                urls["preview_800"] = t.secure_url.split(t.url.split('/')[-1])[0] + t.url.split('/')[-1]
        elif resource_type == "video":
            if "sp_auto" in t.transformation and t.format == "m3u8":
                urls["hls_manifest"] = t.secure_url.split(t.url.split('/')[-1])[0] + t.url.split('/')[-1]
            if "f_jpg" in t.transformation:
                urls["static_thumbnail"] = t.secure_url.split(t.url.split('/')[-1])[0] + t.url.split('/')[-1]
            if "f_gif" in t.transformation:
                urls["animated_preview"] = t.secure_url.split(t.url.split('/')[-1])[0] + t.url.split('/')[-1]
            if t.format == "mp4":
                urls["mp4_video"] = t.secure_url.split(t.url.split('/')[-1])[0] + t.url.split('/')[-1]
            if t.format == "mp3":
                urls["mp3_audio"] = t.secure_url.split(t.url.split('/')[-1])[0] + t.url.split('/')[-1]
    return urls


@router.post("/cloudinary/media-processed")
async def handle_cloudinary_media_processed(
    request: Request,
    x_cld_timestamp: str = Header(...),
    x_cld_signature: str = Header(...)
):
    body_bytes = await request.body()
    
    # In a production environment, signature verification is CRITICAL.
    # if not verify_cloudinary_signature(body_bytes, x_cld_signature, x_cld_timestamp):
    #     logger.warning("Invalid Cloudinary webhook signature received.")
    #     raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    try:
        data = json.loads(body_bytes)
        if data.get('notification_type') != 'eager' and data.get('notification_type') != 'upload':
            return {"status": "ignored", "reason": "notification type is not 'eager' or 'upload'"}
        payload = CloudinaryWebhookPayload.model_validate(data)
    except Exception as e:
        logger.error(f"Webhook payload validation error: {e}")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid webhook payload: {e}")

    message_resp = db_manager.get_table("messages").select("id, chat_id").eq("client_temp_id", payload.public_id).maybe_single().execute()

    if not message_resp.data:
        logger.warning(f"Webhook received for unknown public_id/client_temp_id: {payload.public_id}")
        return {"status": "ignored", "reason": "message not found"}

    message_db_id = message_resp.data['id']
    chat_id = str(message_resp.data['chat_id'])

    final_media_metadata = {
        "public_id": payload.public_id,
        "resource_type": payload.resource_type,
        "format": payload.format,
        "bytes": payload.bytes,
        "duration_seconds": payload.duration,
        "width": payload.width,
        "height": payload.height,
        "urls": {
            "original": payload.secure_url,
            **map_eager_to_urls(payload.eager, payload.resource_type)
        }
    }

    update_data = {
        "upload_status": "completed",
        "status": "sent",
        "media_url": payload.secure_url,
        "thumbnail_url": final_media_metadata["urls"].get("static_thumbnail") or final_media_metadata["urls"].get("thumbnail_250"),
        "file_size": payload.bytes,
        "file_metadata": json.dumps(final_media_metadata)
    }

    db_manager.get_table("messages").update(update_data).eq("id", str(message_db_id)).execute()

    updated_message = await get_message_with_details_from_db(message_db_id)
    if updated_message:
        await ws_manager.broadcast_media_processed(chat_id, updated_message)

    return {"status": "success"}

