
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from uuid import UUID
from app.database import db_manager
from app.auth.dependencies import get_current_active_user
from app.auth.schemas import UserPublic
from app.utils.logging import logger
from . import partners
from app.partners.schemas import (
    PartnerRequestCreate, 
    PartnerRequestResponse, 
    PartnerRequestAction,
    PartnerSuggestionResponse,
    IncomingRequestsResponse
)

router = APIRouter(prefix="/partners", tags=["Partners"])

@router.get("/suggestions", response_model=PartnerSuggestionResponse)
async def get_partner_suggestions(current_user: UserPublic = Depends(get_current_active_user)):
    """
    Get a list of users who are not the current user and do not have a partner yet.
    """
    logger.info(f"User {current_user.id} requesting partner suggestions.")
    try:
        # Exclude self and users who already have a partner
        response = db_manager.get_table("users").select(
            "id, display_name, avatar_url, mood, phone, email, is_online, last_seen, partner_id"
        ).is_("partner_id", "NULL").neq("id", str(current_user.id)).execute()
        
        users = [UserPublic(**user_data) for user_data in response.data] if response.data else []
        return PartnerSuggestionResponse(users=users)
    except Exception as e:
        logger.error(f"Error fetching partner suggestions for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not retrieve partner suggestions.")

@router.post("/request", response_model=PartnerRequestResponse)
async def send_partner_request(
    request_data: PartnerRequestCreate,
    current_user: UserPublic = Depends(get_current_active_user)
):
    """
    Send a partner request to another user.
    """
    recipient_id = request_data.recipient_id
    if recipient_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot send a partner request to yourself.")

    logger.info(f"User {current_user.id} sending partner request to {recipient_id}.")
    
    # 1. Check if either user is already in a partnership.
    user_check_resp = db_manager.get_table("users").select("id, partner_id").in_("id", [str(current_user.id), str(recipient_id)]).execute()
    for user in user_check_resp.data:
        if user['partner_id'] is not None:
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"User {user['id']} is already in a partnership.")

    # 2. Check for an existing pending request between these two users in either direction.
    # This is done with two separate queries for robustness, avoiding the problematic `or` filter.
    request_check_1_resp = db_manager.get_table("partner_requests").select("id").eq(
        "sender_id", str(current_user.id)
    ).eq("recipient_id", str(recipient_id)).eq("status", "pending").limit(1).execute()

    if request_check_1_resp.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A pending request already exists with this user."
        )

    request_check_2_resp = db_manager.get_table("partner_requests").select("id").eq(
        "sender_id", str(recipient_id)
    ).eq("recipient_id", str(current_user.id)).eq("status", "pending").limit(1).execute()
    
    if request_check_2_resp.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This user has already sent you a pending request. Please check your incoming requests."
        )


    # 3. If all checks pass, create the new request.
    new_request_data = {
        "sender_id": str(current_user.id),
        "recipient_id": str(recipient_id)
    }
    try:
        insert_resp = db_manager.get_table("partner_requests").insert(new_request_data).execute()
        
        # To return a full response, we need to fetch the sender and recipient details
        created_request_id = insert_resp.data[0]['id']
        request_resp = db_manager.get_table("partner_requests").select("*, sender:sender_id(*), recipient:recipient_id(*)").eq("id", created_request_id).single().execute()
        
        return PartnerRequestResponse.model_validate(request_resp.data)
    except Exception as e:
        logger.error(f"Error sending partner request from {current_user.id} to {recipient_id}: {e}", exc_info=True)
        if "unique constraint" in str(e).lower():
            raise HTTPException(status_code=400, detail="A pending request to this user already exists.")
        raise HTTPException(status_code=500, detail="Could not send partner request.")

@router.get("/requests/incoming", response_model=IncomingRequestsResponse)
async def get_incoming_requests(current_user: UserPublic = Depends(get_current_active_user)):
    """
    Get all pending partner requests for the current user.
    """
    logger.info(f"Fetching incoming partner requests for user {current_user.id}")
    try:
        response = db_manager.get_table("partner_requests").select(
            "*, sender:sender_id(*), recipient:recipient_id(*)"
        ).eq("recipient_id", str(current_user.id)).eq("status", "pending").execute()
        
        requests = [PartnerRequestResponse.model_validate(req) for req in response.data] if response.data else []
        return IncomingRequestsResponse(requests=requests)
    except Exception as e:
        logger.error(f"Error fetching incoming requests for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not retrieve incoming requests.")


@router.get("/requests/outgoing", response_model=IncomingRequestsResponse)
async def get_outgoing_requests(current_user: UserPublic = Depends(get_current_active_user)):
    """
    Get all pending partner requests sent by the current user.
    """
    logger.info(f"Fetching outgoing partner requests for user {current_user.id}")
    try:
        response = db_manager.get_table("partner_requests").select(
            "*, sender:sender_id(*), recipient:recipient_id(*)"
        ).eq("sender_id", str(current_user.id)).eq("status", "pending").execute()
        
        requests = [PartnerRequestResponse.model_validate(req) for req in response.data] if response.data else []
        return IncomingRequestsResponse(requests=requests)
    except Exception as e:
        logger.error(f"Error fetching outgoing requests for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not retrieve outgoing requests.")


@router.post("/requests/{request_id}/respond", status_code=status.HTTP_204_NO_CONTENT)
async def respond_to_partner_request(
    request_id: UUID,
    action_data: PartnerRequestAction,
    current_user: UserPublic = Depends(get_current_active_user)
):
    """
    Accept or reject a partner request.
    """
    action = action_data.action.lower()
    if action not in ["accept", "reject"]:
        raise HTTPException(status_code=400, detail="Invalid action. Must be 'accept' or 'reject'.")

    logger.info(f"User {current_user.id} responding '{action}' to request {request_id}")

    if action == "accept":
        try:
            db_manager.admin_client.rpc(
                'accept_partner_request', 
                {'p_request_id': str(request_id), 'p_accepter_id': str(current_user.id)}
            ).execute()
        except Exception as e:
            logger.error(f"RPC accept_partner_request failed for user {current_user.id} on request {request_id}: {e}", exc_info=True)
            detail_message = getattr(e, 'message', str(e))
            raise HTTPException(status_code=400, detail=detail_message)
    
    elif action == "reject":
        try:
            # Verify the current user is the recipient before rejecting
            req_resp = db_manager.admin_client.table("partner_requests").select("recipient_id, status").eq("id", str(request_id)).maybe_single().execute()
            
            if not req_resp.data:
                raise HTTPException(status_code=404, detail="Request not found.")
                
            if req_resp.data.get('recipient_id') != str(current_user.id):
                raise HTTPException(status_code=403, detail="You are not the recipient of this request.")

            if req_resp.data.get('status') != 'pending':
                raise HTTPException(status_code=400, detail="This request is no longer pending and cannot be rejected.")

            db_manager.admin_client.table("partner_requests").update({
                "status": "rejected",
                "updated_at": "now()"
            }).eq("id", str(request_id)).execute()
        except HTTPException:
            raise # Re-raise our own HTTP exceptions
        except Exception as e:
            logger.error(f"Error rejecting request {request_id} by user {current_user.id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Could not reject request.")
    
    return None # Returns 204 No Content on success

@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_partner(
    current_user: UserPublic = Depends(get_current_active_user)
):
    if not current_user.partner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="You do not have a partner to disconnect from.")

    partner_id = current_user.partner_id
    logger.info(f"User {current_user.id} initiating disconnect from partner {partner_id}.")

    try:
        # This is not atomic, but it's the best we can do without adding a new RPC
        db_manager.admin_client.table("users").update({"partner_id": None}).eq("id", str(current_user.id)).execute()
        db_manager.admin_client.table("users").update({"partner_id": None}).eq("id", str(partner_id)).execute()
        
        logger.info(f"Successfully disconnected user {current_user.id} from {partner_id}.")
        return None
    except Exception as e:
        logger.error(f"Error disconnecting partner for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not disconnect from partner.")

    