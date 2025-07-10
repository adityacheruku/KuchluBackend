from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List
from uuid import UUID
from datetime import datetime
import re

ALL_MOODS = ["Happy", "Sad", "Neutral", "Excited", "Thoughtful", "Chilling", "Angry", "Anxious", "Content"]
Mood = str 

class PhoneSchema(BaseModel):
    phone: str
    @validator('phone')
    def validate_phone(cls, v):
        if not re.match(r"^\+[1-9]\d{1,14}$", v):
            raise ValueError('Phone number must be in E.164 format (e.g., +12223334444)')
        return v

class VerifyOtpRequest(PhoneSchema):
    otp: str = Field(min_length=6, max_length=6)

class VerifyOtpResponse(BaseModel):
    registration_token: str

# Firebase Authentication Schemas
class FirebaseSignupRequest(BaseModel):
    firebase_token: str = Field(..., description="Firebase ID token from client")

class FirebaseLoginRequest(BaseModel):
    firebase_token: str = Field(..., description="Firebase ID token from client")

class CompleteRegistrationRequest(BaseModel):
    registration_token: str
    display_name: str
    password: str = Field(min_length=8)
    email: Optional[EmailStr] = None

class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)

class DeleteAccountRequest(BaseModel):
    password: str

class UserBase(BaseModel):
    id: UUID
    phone: str
    display_name: str
    email: Optional[EmailStr] = None
    avatar_url: Optional[str] = None
    mood: Optional[Mood] = "Neutral"
    is_online: Optional[bool] = False
    last_seen: Optional[datetime] = None
    partner_id: Optional[UUID] = None
    firebase_uid: Optional[str] = None

class UserLogin(BaseModel):
    phone: str
    password: str

class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    mood: Optional[Mood] = None
    email: Optional[EmailStr] = None
    avatar_url: Optional[str] = None

class UserPublic(BaseModel):
    id: UUID
    display_name: str
    avatar_url: Optional[str] = None
    mood: Optional[Mood] = "Neutral"
    is_online: Optional[bool] = False
    last_seen: Optional[datetime] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    partner_id: Optional[UUID] = None
    firebase_uid: Optional[str] = None

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserPublic

class TokenData(BaseModel):
    phone: Optional[str] = None
    user_id: Optional[UUID] = None
    token_type: Optional[str] = None

class ActivityHistoryEvent(BaseModel):
    id: str
    type: str
    timestamp: datetime
    user_id: str
    mood: Optional[str] = None
    recipient_id: Optional[str] = None
    sender_id: Optional[str] = None

    
