
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from uuid import UUID, uuid4
from passlib.context import CryptContext
from datetime import datetime

# Define password context for hashing and verification
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class UserInDB(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    email: EmailStr # Changed from username to email for login, more standard
    hashed_password: str
    display_name: str # Renamed from name for clarity
    avatar_url: Optional[str] = "https://placehold.co/100x100.png?text=U" # Default avatar
    mood: str = "Neutral" # Using str from ALL_MOODS
    phone: Optional[str] = None
    is_active: bool = True
    is_online: bool = False
    last_seen: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True # Supabase returns dicts, this helps if we ever map them directly

# Helper functions directly related to this conceptual model representation
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

# Note: Actual "User" table schema is defined and managed in Supabase.
# This file now primarily holds the Pydantic model for internal representation
# and password utility functions.
# The original Tortoise ORM User model is removed.
    