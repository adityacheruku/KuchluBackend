
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt, ExpiredSignatureError
from passlib.context import CryptContext
from fastapi import UploadFile, HTTPException, status
from app.config import settings
from app.utils.logging import logger

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def _create_token(data: dict, expires_delta: timedelta, token_type: str) -> str:
    to_encode = data.copy()
    to_encode.update({"token_type": token_type})
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def create_access_token(data: dict) -> str:
    expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return _create_token(data, expires, "access")

def create_refresh_token(data: dict) -> str:
    expires = timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
    return _create_token(data, expires, "refresh")

def create_registration_token(phone: str) -> str:
    expires = timedelta(minutes=10)
    return _create_token({"sub": phone}, expires, "registration")

def verify_registration_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("token_type") != "registration":
            return None
        return payload.get("sub")
    except (JWTError, ExpiredSignatureError):
        return None

# Based on fileValidation.ts on the frontend
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/heic"}
ALLOWED_CLIP_TYPES = {"audio/mpeg", "audio/wav", "audio/webm", "audio/ogg", "audio/mp4", "video/mp4", "video/quicktime", "video/webm", "audio/x-m4a"}
ALLOWED_DOCUMENT_TYPES = {"application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain"}

MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_CLIP_SIZE = 100 * 1024 * 1024 # 100MB
MAX_DOCUMENT_SIZE = 50 * 1024 * 1024 # 50MB

def _validate_file(file: UploadFile, allowed_types: set, max_size: int):
    if file.content_type not in allowed_types:
        logger.warning(f"Invalid file type: {file.content_type}. Allowed: {allowed_types}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid file type: {file.content_type}.")
    
    # file.size might not be available for all streams, but we check if it is
    if file.size and file.size > max_size:
        logger.warning(f"File too large: {file.size} bytes. Max size: {max_size} bytes.")
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"File too large. Max size is {max_size/1024/1024:.0f}MB.")

def validate_image_upload(file: UploadFile):
    _validate_file(file, ALLOWED_IMAGE_TYPES, MAX_IMAGE_SIZE)

def validate_clip_upload(file: UploadFile):
    _validate_file(file, ALLOWED_CLIP_TYPES, MAX_CLIP_SIZE)

def validate_document_upload(file: UploadFile):
    _validate_file(file, ALLOWED_DOCUMENT_TYPES, MAX_DOCUMENT_SIZE)
