from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import List
from app.auth.schemas import UserPublic

class PartnerRequestCreate(BaseModel):
    recipient_id: UUID

class PartnerRequestResponse(BaseModel):
    id: UUID
    sender: UserPublic
    recipient: UserPublic
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class PartnerRequestAction(BaseModel):
    action: str # "accept" or "reject"

class PartnerSuggestionResponse(BaseModel):
    users: List[UserPublic]

class IncomingRequestsResponse(BaseModel):
    requests: List[PartnerRequestResponse]
