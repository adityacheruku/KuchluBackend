from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks, Request
from fastapi.security import OAuth2PasswordRequestForm
from uuid import UUID, uuid4
from datetime import datetime, timezone
import random
from typing import List

from app.auth.schemas import UserLogin, UserUpdate, UserPublic, Token, PhoneSchema, VerifyOtpRequest, VerifyOtpResponse, CompleteRegistrationRequest, PasswordChangeRequest, DeleteAccountRequest, FirebaseSignupRequest, FirebaseLoginRequest, ActivityHistoryEvent
from app.auth.dependencies import get_current_user, get_current_active_user, get_user_from_refresh_token
from app.utils.security import get_password_hash, verify_password, create_access_token, create_refresh_token, create_registration_token, verify_registration_token
from app.database import db_manager
from app.config import settings
from app.utils.email_utils import send_login_notification_email, send_email_async
from app.utils.logging import logger
from postgrest.exceptions import APIError
from app.websocket import manager as ws_manager
from app.notifications.service import notification_service, ADMIN_EMAIL
from app.redis_client import get_redis_client
from app.auth.firebase_service import firebase_service

auth_router = APIRouter(prefix="/auth", tags=["Authentication"])
user_router = APIRouter(prefix="/users", tags=["Users"])

@user_router.get("/me/activity-history", response_model=List[ActivityHistoryEvent], summary="Get user activity history")
async def get_activity_history(current_user: UserPublic = Depends(get_current_active_user)):
    """
    Retrieves a combined history of mood updates and 'Thinking of You' pings
    for the current user and their partner.
    """
    user_id = str(current_user.id)
    partner_id = str(current_user.partner_id) if current_user.partner_id else None

    if not partner_id:
        # If there's no partner, only fetch the user's own mood updates
        mood_updates_resp = db_manager.admin_client.table("mood_analytics").select("id, created_at, mood_name, source").eq("user_id", user_id).eq("source", "profile_update").execute()
        mood_events = mood_updates_resp.data or []
    else:
        # Fetch events for both user and partner
        mood_updates_resp = db_manager.admin_client.table("mood_analytics").select("id, created_at, mood_name, source, user_id").in_("user_id", [user_id, partner_id]).execute()
        mood_events = mood_updates_resp.data or []

    history_events: List[ActivityHistoryEvent] = []

    for event in mood_events:
        event_user_id = str(event['user_id'])
        if event.get('source') == 'profile_update' and event_user_id == user_id:
            history_events.append(ActivityHistoryEvent(
                id=str(event['id']),
                type='mood_update',
                mood=event.get('mood_name'),
                timestamp=event['created_at'],
                user_id=user_id
            ))
        elif event.get('source') == 'assistive_touch_ping':
            if event_user_id == user_id:
                history_events.append(ActivityHistoryEvent(
                    id=str(event['id']),
                    type='ping_sent',
                    recipient_id=partner_id,
                    timestamp=event['created_at'],
                    user_id=user_id
                ))
            elif partner_id and event_user_id == partner_id:
                history_events.append(ActivityHistoryEvent(
                    id=str(event['id']),
                    type='ping_received',
                    sender_id=partner_id,
                    timestamp=event['created_at'],
                    user_id=user_id
                ))
    
    # Sort events chronologically descending
    history_events.sort(key=lambda x: x.timestamp, reverse=True)
    
    return history_events


@auth_router.post("/firebase/signup", response_model=Token, summary="Sign up with Firebase")
async def firebase_signup(request_data: FirebaseSignupRequest):
    """
    Sign up user using Firebase authentication.
    Verifies Firebase ID token and creates user in database.
    """
    try:
        # Verify Firebase token
        decoded_token = firebase_service.verify_id_token(request_data.firebase_token)
        if not decoded_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Firebase token")
        
        phone_number = decoded_token.get("phone_number")
        firebase_uid = decoded_token.get("uid")
        
        if not phone_number:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone number not found in Firebase token")
        
        # Check if user already exists
        existing_user_resp = db_manager.get_table("users").select("id").eq("phone", phone_number).maybe_single().execute()
        if existing_user_resp.data:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone number already registered")
        
        # Create new user
        user_id = uuid4()
        new_user_data = {
            "id": str(user_id),
            "phone": phone_number,
            "firebase_uid": firebase_uid,
            "display_name": f"User{phone_number[-4:]}",  # Default display name
            "avatar_url": f"https://placehold.co/100x100.png?text={phone_number[-1].upper()}",
            "mood": "Neutral",
            "is_active": True,
            "is_online": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        
        try:
            insert_response_obj = db_manager.admin_client.table("users").insert(new_user_data).execute()
            if not insert_response_obj.data:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create user")
        except APIError as e:
            logger.error(f"PostgREST APIError during user insert: {e}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: {e.message}")
        
        created_user_raw = insert_response_obj.data[0]
        user_public_info = UserPublic.model_validate(created_user_raw)
        
        access_token = create_access_token(data={"sub": phone_number, "user_id": str(user_id)})
        refresh_token = create_refresh_token(data={"sub": phone_number, "user_id": str(user_id)})
        
        logger.info(f"User {phone_number} successfully signed up via Firebase")
        return Token(access_token=access_token, refresh_token=refresh_token, token_type="bearer", user=user_public_info)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Firebase signup error: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

@auth_router.post("/firebase/login", response_model=Token, summary="Login with Firebase")
async def firebase_login(request_data: FirebaseLoginRequest, background_tasks: BackgroundTasks):
    """
    Login user using Firebase authentication.
    Verifies Firebase ID token and returns user data.
    """
    try:
        # Verify Firebase token
        decoded_token = firebase_service.verify_id_token(request_data.firebase_token)
        if not decoded_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Firebase token")
        
        phone_number = decoded_token.get("phone_number")
        firebase_uid = decoded_token.get("uid")
        
        if not phone_number:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone number not found in Firebase token")
        
        # Find user in database
        try:
            user_response_obj = db_manager.get_table("users").select("*").eq("phone", phone_number).maybe_single().execute()
        except APIError as e:
            logger.error(f"Supabase APIError during login for phone {phone_number}: {e}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Error communicating with the authentication service")
        
        user_dict_from_db = user_response_obj.data if user_response_obj else None
        
        if not user_dict_from_db:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found. Please sign up first.")
        
        # Update firebase_uid if not set
        if not user_dict_from_db.get("firebase_uid"):
            db_manager.get_table("users").update({"firebase_uid": firebase_uid}).eq("id", str(user_dict_from_db["id"])).execute()
        
        # Email notification for specific user
        if user_dict_from_db.get("phone") == "8309605626":
            try:
                subject = f"{user_dict_from_db['display_name']} (8309605626) has opened the app!"
                body = f"<p>{user_dict_from_db['display_name']} (8309605626) has opened the app.</p>"
                background_tasks.add_task(send_email_async, subject, ADMIN_EMAIL, body)
                logger.info(f"Login email sent to {ADMIN_EMAIL}")
            except Exception as e:
                logger.error(f"Failed to send login email: {e}")

        user_public_info = UserPublic.model_validate(user_dict_from_db)
        access_token = create_access_token(data={"sub": phone_number, "user_id": str(user_dict_from_db["id"])})
        refresh_token = create_refresh_token(data={"sub": phone_number, "user_id": str(user_dict_from_db["id"])})
        
        logger.info(f"User {phone_number} successfully logged in via Firebase")
        return Token(access_token=access_token, refresh_token=refresh_token, token_type="bearer", user=user_public_info)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Firebase login error: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

@auth_router.post("/send-otp", status_code=status.HTTP_200_OK)
async def send_otp(phone_data: PhoneSchema):
    """
    Checks if a phone number is available and sends an OTP.
    For development, the OTP is logged to the console.
    """
    phone = phone_data.phone
    logger.info(f"OTP requested for phone: {phone}")
    
    existing_user_resp = db_manager.get_table("users").select("id").eq("phone", phone).maybe_single().execute()
    if existing_user_resp.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone number already registered.")

    otp = f"{random.randint(100000, 999999)}"
    redis = await get_redis_client()
    await redis.set(f"otp:{phone}", otp, ex=300)

    logger.info(f"====== DEV ONLY: OTP for {phone} is {otp} ======")
    
    return {"message": "OTP has been sent."}

@auth_router.post("/verify-otp", response_model=VerifyOtpResponse)
async def verify_otp(request_data: VerifyOtpRequest):
    """
    Verifies the provided OTP for a phone number and returns a temporary registration token.
    """
    phone = request_data.phone
    otp = request_data.otp
    
    redis = await get_redis_client()
    stored_otp = await redis.get(f"otp:{phone}")

    if not stored_otp:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP expired or not found. Please request a new one.")
    
    if stored_otp != otp:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OTP.")
    
    await redis.delete(f"otp:{phone}")

    registration_token = create_registration_token(phone=phone)
    
    return VerifyOtpResponse(registration_token=registration_token)

@auth_router.post("/complete-registration", response_model=Token, summary="Complete user registration")
async def complete_registration(reg_data: CompleteRegistrationRequest):
    """
    Completes user registration using a valid registration token.
    """
    phone = verify_registration_token(reg_data.registration_token)
    if not phone:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired registration token.")

    existing_user_resp = db_manager.get_table("users").select("id").eq("phone", phone).maybe_single().execute()
    if existing_user_resp.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone number was registered by another user. Please start over.")

    hashed_password = get_password_hash(reg_data.password)
    user_id = uuid4()
    
    new_user_data = {
        "id": str(user_id), "phone": phone, "email": reg_data.email,
        "hashed_password": hashed_password, "display_name": reg_data.display_name,
        "avatar_url": f"https://placehold.co/100x100.png?text={reg_data.display_name[:1].upper()}",
        "mood": "Neutral", "is_active": True, "is_online": False,
        "created_at": datetime.now(timezone.utc).isoformat(), "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    
    logger.info(f"Attempting to complete registration for user with phone {phone}")
    try:
        insert_response_obj = db_manager.admin_client.table("users").insert(new_user_data).execute()
        if not insert_response_obj.data:
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create user after database operation.")
    except APIError as e:
        logger.error(f"PostgREST APIError during user insert: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: {e.message}")
    
    created_user_raw = insert_response_obj.data[0]
    user_public_info = UserPublic.model_validate(created_user_raw)

    access_token = create_access_token(data={"sub": phone, "user_id": str(user_id)})
    refresh_token = create_refresh_token(data={"sub": phone, "user_id": str(user_id)})
    
    return Token(access_token=access_token, refresh_token=refresh_token, token_type="bearer", user=user_public_info)

@auth_router.post("/login", response_model=Token)
async def login(request: Request, background_tasks: BackgroundTasks, form_data: OAuth2PasswordRequestForm = Depends()):
    logger.info(f"Login attempt for phone: {form_data.username}")

    try:
        user_response_obj = db_manager.get_table("users").select("*").eq("phone", form_data.username).maybe_single().execute()
    except APIError as e:
        logger.error(f"Supabase APIError during login for phone {form_data.username}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Error communicating with the authentication service.")
    
    user_dict_from_db = user_response_obj.data if user_response_obj else None
    
    if not user_dict_from_db or not verify_password(form_data.password, user_dict_from_db["hashed_password"]):
        logger.warning(f"Login attempt failed for phone: {form_data.username} - User not found or incorrect password.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect phone number or password", headers={"WWW-Authenticate": "Bearer"})

    logger.info(f"User {form_data.username} ({user_dict_from_db['display_name']}) successfully logged in.")

    # Email notification for specific user
    if user_dict_from_db.get("phone") == "7981118025":
        try:
            subject = f"{user_dict_from_db['display_name']} (8309605626) has opened the app!"
            body = f"<p>{user_dict_from_db['display_name']} (8309605626) has opened the app.</p>"
            background_tasks.add_task(send_email_async, subject, ADMIN_EMAIL, body)
            logger.info(f"Login email sent to {ADMIN_EMAIL}")
        except Exception as e:
            logger.error(f"Failed to send login email: {e}")

    user_public_info = UserPublic.model_validate(user_dict_from_db)
    access_token = create_access_token(data={"sub": user_dict_from_db["phone"], "user_id": str(user_dict_from_db["id"])})
    refresh_token = create_refresh_token(data={"sub": user_dict_from_db["phone"], "user_id": str(user_dict_from_db["id"])})
    
    if settings.NOTIFICATION_EMAIL_TO:
        client_host = request.client.host if request.client else "Unknown IP"
        background_tasks.add_task(
            send_login_notification_email,
            logged_in_user_name=user_dict_from_db["display_name"],
            logged_in_user_phone=user_dict_from_db.get("phone"),
            login_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            client_host=client_host
        )

    return Token(access_token=access_token, refresh_token=refresh_token, token_type="bearer", user=user_public_info)

@auth_router.post("/refresh", response_model=Token, summary="Refresh access token")
async def refresh_access_token(current_user: UserPublic = Depends(get_user_from_refresh_token)):
    logger.info(f"Refreshing tokens for user {current_user.id}")
    access_token = create_access_token(data={"sub": current_user.phone, "user_id": str(current_user.id)})
    refresh_token = create_refresh_token(data={"sub": current_user.phone, "user_id": str(current_user.id)})
    return Token(access_token=access_token, refresh_token=refresh_token, token_type="bearer", user=current_user)

@user_router.get("/me", response_model=UserPublic)
async def read_users_me(current_user: UserPublic = Depends(get_current_active_user)):
    return current_user

@user_router.get("/{user_id}", response_model=UserPublic)
async def get_user(user_id: UUID, current_user_dep: UserPublic = Depends(get_current_user)):
    user_response_obj = db_manager.get_table("users").select("id, display_name, avatar_url, mood, phone, email, is_online, last_seen, partner_id").eq("id", str(user_id)).maybe_single().execute()
    if not user_response_obj.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserPublic(**user_response_obj.data)

@user_router.put("/me/profile", response_model=UserPublic)
async def update_profile(profile_update: UserUpdate, current_user: UserPublic = Depends(get_current_active_user)):
    update_data = profile_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")
    
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    if "password" in update_data: del update_data["password"]

    logger.info(f"User {current_user.id} updating profile with data: {update_data}")
    db_manager.get_table("users").update(update_data).eq("id", str(current_user.id)).execute()
    updated_user_response_obj = db_manager.get_table("users").select("*").eq("id", str(current_user.id)).maybe_single().execute()
    
    if not updated_user_response_obj.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found or update failed")

    refreshed_user_data = updated_user_response_obj.data
    await ws_manager.broadcast_user_profile_update(user_id=current_user.id, updated_data={"mood": refreshed_user_data['mood']})
    
    if "mood" in update_data and refreshed_user_data.get('mood') != current_user.mood:
        await notification_service.send_mood_change_notification(user=current_user, new_mood=refreshed_user_data['mood'])

    return UserPublic.model_validate(refreshed_user_data)

@user_router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(password_data: PasswordChangeRequest, current_user: UserPublic = Depends(get_current_active_user)):
    user_response_obj = db_manager.get_table("users").select("hashed_password").eq("id", str(current_user.id)).single().execute()
    
    if not verify_password(password_data.current_password, user_response_obj.data["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect current password.")

    new_hashed_password = get_password_hash(password_data.new_password)
    db_manager.get_table("users").update({"hashed_password": new_hashed_password, "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", str(current_user.id)).execute()
    logger.info(f"User {current_user.id} successfully changed their password.")
    return None

@user_router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    delete_request: DeleteAccountRequest,
    current_user: UserPublic = Depends(get_current_active_user)
):
    user_resp = db_manager.get_table("users").select("hashed_password").eq("id", str(current_user.id)).single().execute()
    
    if not verify_password(delete_request.password, user_resp.data["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password. Account not deleted.",
        )

    try:
        # Use admin client to perform deletion. Assumes RLS is set up to allow this
        # or that cascading deletes are configured in the database schema.
        db_manager.admin_client.table("users").delete().eq("id", str(current_user.id)).execute()
        logger.info(f"User {current_user.id} successfully deleted their account.")
    except Exception as e:
        logger.error(f"Error during account deletion for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A server error occurred while trying to delete the account.",
        )
    
    return None

@user_router.post("/me/avatar", response_model=UserPublic)
async def upload_avatar_route(file: UploadFile = File(...), current_user: UserPublic = Depends(get_current_active_user)):
    from app.routers.uploads import upload_avatar_to_cloudinary 
    file_url = await upload_avatar_to_cloudinary(file)
    update_data = {"avatar_url": file_url, "updated_at": datetime.now(timezone.utc).isoformat()}
    db_manager.get_table("users").update(update_data).eq("id", str(current_user.id)).execute()
    updated_user_response_obj = db_manager.get_table("users").select("*").eq("id", str(current_user.id)).maybe_single().execute()
    
    if not updated_user_response_obj.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found or avatar update failed")
    
    refreshed_user_data = updated_user_response_obj.data
    await ws_manager.broadcast_user_profile_update(user_id=current_user.id, updated_data={"avatar_url": refreshed_user_data["avatar_url"]})
    return UserPublic.model_validate(refreshed_user_data)

@user_router.post("/{recipient_user_id}/ping-thinking-of-you", status_code=status.HTTP_200_OK)
async def http_ping_thinking_of_you(recipient_user_id: UUID, current_user: UserPublic = Depends(get_current_active_user)):
    logger.info(f"User {current_user.id} sending 'Thinking of You' ping to user {recipient_user_id} via HTTP.")
    recipient_check_resp_obj = db_manager.get_table("users").select("id").eq("id", str(recipient_user_id)).maybe_single().execute()
    if not recipient_check_resp_obj.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipient user not found.")

    if recipient_user_id == current_user.id:
        return {"status": "Ping to self noted, not sent."}

    await ws_manager.broadcast_to_users(
        user_ids=[recipient_user_id],
        payload={"event_type": "thinking_of_you_received", "sender_id": str(current_user.id), "sender_name": current_user.display_name}
    )
    await notification_service.send_thinking_of_you_notification(sender=current_user, recipient_id=recipient_user_id)
    return {"status": "Ping sent"}

    
